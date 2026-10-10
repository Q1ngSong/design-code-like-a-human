"""Pull the outputs generated on a remote machine into the same relative paths locally, hash-verified. [基础设施]

Run on the local machine, repeatedly while remote jobs are running, and once with `--final` after they stop.
Everything project-specific comes from a JSON config (see sync_config.example.json).

What one pass does:
- The remote lists files with size and sha256. A directory matching a `units` rule is one work item; its files are
  listed only when its completion condition holds. Matching is outermost-first and the first matching rule wins;
  nothing inside a unit is matched again. Files outside every unit directory are always listed.
- A local file counts as synced only if size and sha256 both match. Missing or different files are fetched over
  parallel ssh connections into a staging directory, verified, then moved into place.
- In result paths, a local file that differs from the remote copy, and a local file inside a finished unit that the
  remote does not have, is moved to `<state_dir>/displaced/<time>-<pid>/<same relative path>`; never deleted.
  Files under `<state_dir>/logs` and `<state_dir>/unfinished` are copies of remote files and are replaced in place.
- `--final` ignores both hash caches, also fetches unfinished units into `<state_dir>/unfinished/`, and succeeds
  only if no writer process is running and a second remote listing is identical to the first.

Not supported, reported and counted as not synced: symbolic links, names that Windows cannot store, two remote
paths that differ only by letter case, a remote top-level entry named like `state_dir`.

Exit codes: 0 synced (or dry-run finished), 1 some files not synced or the remote changed during --final,
2 bad command line, 3 not enough local disk, 4 another pass is running, 5 crashed, 6 --final refused.
The last output line starts with `SYNC`.
"""

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath

CHUNK = 8 << 20  # files above this are fetched as byte ranges, one connection each
BATCH_BYTES = 12 << 20
BATCH_FILES = 200
BATCH_TIMEOUT = 600  # seconds for one batch connection, including remote exit
GIT_SSH = Path("C:/Program Files/Git/usr/bin/ssh.exe")
WINDOWS_BAD = set('<>:"\\|?*')
WINDOWS_RESERVED = {"con", "prn", "aux", "nul"} | {f"{p}{i}" for p in ("com", "lpt") for i in range(1, 10)}

# Runs on the remote. argv: <config json> <final 0|1>. Prints one JSON object per line:
#   {"unit": rel}                      a unit directory whose completion condition holds
#   {"withheld": rel}                  an unfinished unit directory, not listed in this pass
#   {"skipped": rel, "why": text}      something that cannot be synced (vanished, symlink, reserved name)
#   {"src","rel","size","sha256"}      a file allowed to leave the remote in this pass
REMOTE_MANIFEST = r'''
import fnmatch, hashlib, json, os, shutil, sys
CFG, FINAL = json.loads(sys.argv[1]), sys.argv[2] == "1"
ROOT, STATE = CFG["remote_root"].rstrip("/"), CFG["state_dir"]
EXCLUDE = set(CFG.get("exclude_dirs", []))
CACHE = ROOT + "/.sync_hash_cache.json"
cache = {}
if not FINAL:  # the final listing re-reads every file
    try:
        cache = json.load(open(CACHE))
    except Exception:
        cache = {}
seen = {}

def skip(rel, why):
    print(json.dumps({"skipped": rel, "why": why}))

def emit(src, rel):
    try:
        st = os.stat(src)
        key = [st.st_size, st.st_mtime_ns]
        hit = cache.get(src)
        if hit and hit[:2] == key:
            digest = hit[2]
        else:
            h = hashlib.sha256()
            with open(src, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
            digest = h.hexdigest()
    except OSError:
        skip(rel, "vanished while listing")
        return
    seen[src] = key + [digest]
    print(json.dumps({"src": src, "rel": rel, "size": st.st_size, "sha256": digest}))

def rule_for(rel):
    parts = rel.split("/")
    for rule in CFG.get("units", []):
        pattern = rule["glob"].split("/")
        if len(pattern) == len(parts) and all(fnmatch.fnmatchcase(a, b) for a, b in zip(parts, pattern)):
            return rule
    return None

def finished(path, rule):
    marker = path + "/" + rule["done_file"]
    if not os.path.isfile(marker):
        return False
    if "json_len" not in rule:
        return True
    try:
        value = json.load(open(marker, encoding="utf-8"))
    except Exception:
        return False
    return isinstance(value, list) and len(value) >= rule["json_len"]

def walk(path, rel, in_unit, target):
    """target: prefix put before rel in the local path ("" for the live tree)."""
    for name in sorted(os.listdir(path)):
        child, child_rel = path + "/" + name, (rel + "/" + name if rel else name)
        if os.path.islink(child):
            skip(target + child_rel, "symbolic link")
        elif os.path.isdir(child):
            if name in EXCLUDE:
                continue
            if not rel and name == STATE:
                skip(child_rel, "remote entry uses the reserved state_dir name")
                continue
            rule = None if in_unit else rule_for(child_rel)
            if rule is None:
                walk(child, child_rel, in_unit, target)
            elif finished(child, rule):
                print(json.dumps({"unit": child_rel}))
                walk(child, child_rel, True, target)
            elif FINAL:
                walk(child, child_rel, True, STATE + "/unfinished/")
            else:
                print(json.dumps({"withheld": child_rel}))
        elif child not in (CACHE, CACHE + ".tmp"):
            emit(child, target + child_rel)

walk(ROOT, "", False, "")

# Logs keep growing while jobs run; ship a frozen copy so the listed hash and the bytes sent agree.
logs = (CFG.get("remote_logs") or "").rstrip("/")
if logs and os.path.isdir(logs):
    snap = logs + "/.sync_snapshot"
    shutil.rmtree(snap, ignore_errors=True)
    shutil.copytree(logs, snap, symlinks=True, ignore=lambda d, names: [".sync_snapshot"] if d == logs else [])
    walk(snap, "", True, STATE + "/logs/")

if not FINAL:
    tmp = CACHE + ".tmp"
    json.dump(seen, open(tmp, "w"))
    os.replace(tmp, CACHE)
'''


def sha256_file(path):
    """整文件 sha256。[基础设施]"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def unstorable(rels):
    """清单里本地(Windows)无法无损保存的相对路径及原因。[基础设施]

    Returns:
        {rel: 原因}:含反斜杠或 `..`、含 Windows 非法字符或保留名、以点或空格结尾、与另一路径仅大小写不同。
    """
    bad, folded = {}, {}
    for rel in rels:
        parts = rel.split("/")
        if "\\" in rel or ".." in parts or "" in parts:
            bad[rel] = "path escapes or is malformed"
        elif any(set(p) & WINDOWS_BAD or p.split(".")[0].lower() in WINDOWS_RESERVED or p[-1] in ". " for p in parts):
            bad[rel] = "name not storable on Windows"
        elif folded.setdefault(rel.lower(), rel) != rel:
            bad[rel] = f"differs only by case from {folded[rel.lower()]}"
    return bad


class Remote:
    """远端一侧:ssh 调用、清单、写入者检查。[基础设施]"""

    def __init__(self, cfg):
        """按配置组装 ssh 前缀;主机密钥首次连接时记录到独立文件,之后校验。[基础设施]"""
        self.cfg = cfg
        ssh = cfg.get("ssh") or (str(GIT_SSH) if GIT_SSH.exists() else "ssh")
        expand = lambda value: Path(value).expanduser().as_posix()
        self.base = [ssh, "-i", expand(cfg["key"]), "-p", str(cfg.get("port", 22)), "-o", "BatchMode=yes",
                     "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={expand(cfg['known_hosts'])}",
                     "-o", "ConnectTimeout=40", "-o", "ServerAliveInterval=30", "-o", "LogLevel=ERROR", cfg["host"]]

    def run(self, command, data=b"", timeout=1800):
        """在远端执行一条命令并取回全部 stdout;非零退出抛错。[基础设施]"""
        done = subprocess.run(self.base + [command], input=data, capture_output=True, timeout=timeout)
        if done.returncode != 0:
            raise RuntimeError(f"remote command failed ({done.returncode}): {done.stderr.decode('utf-8', 'replace')[-400:]}")
        return done.stdout

    def manifest(self, final):
        """让远端列出本轮可取回的文件。[基础设施]

        Returns:
            dict:files 为 {rel: {src,size,sha256}};units 为已完成任务项的相对目录集合;withheld 为未完成而
            不取的任务项目录;skipped 为 {rel: 原因}(消失、符号链接、保留名)。
        """
        remote_cfg = {k: self.cfg[k] for k in ("remote_root", "state_dir", "units", "exclude_dirs", "remote_logs") if k in self.cfg}
        command = f"{shlex.quote(self.cfg['remote_python'])} - {shlex.quote(json.dumps(remote_cfg))} {int(final)}"
        listing = dict(files={}, units=set(), withheld=[], skipped={})
        for line in self.run(command, REMOTE_MANIFEST.encode()).decode("utf-8").splitlines():
            row = json.loads(line)
            if "unit" in row:
                listing["units"].add(row["unit"])
            elif "withheld" in row:
                listing["withheld"].append(row["withheld"])
            elif "skipped" in row:
                listing["skipped"][row["skipped"]] = row["why"]
            else:
                listing["files"][row["rel"]] = row
        return listing

    def writers_running(self):
        """远端是否还有命令行匹配 writer_pattern 的进程;检查本身失败则抛错。[基础设施]

        模式经标准输入传入,执行检查的远端 shell 的命令行里不含模式文本。
        """
        out = self.run('n=$(pgrep -fc -- "$(cat)"); echo "$? ${n:-0}"', self.cfg["writer_pattern"].encode()).decode().split()
        code, count = int(out[0]), int(out[1])
        if code > 1:
            raise RuntimeError(f"pgrep failed with exit {code}; cannot tell whether writers are running")
        return count > 0


class LocalTree:
    """本地一侧:哈希缓存、是否已同步、校验落盘、移走不同的本地文件。[基础设施]"""

    def __init__(self, root, state_dir, stamp):
        """root 为本地输出根;state_dir 为其下存放回传状态的目录名;stamp 用于本轮备份目录名。[基础设施]"""
        self.root = Path(root)
        self.state = state_dir
        self.meta = self.root / state_dir
        self.meta.mkdir(parents=True, exist_ok=True)
        self.displaced_dir = self.meta / "displaced" / f"{stamp}-{os.getpid()}"
        self.displaced = []
        self.cache_path = self.meta / "local_hash_cache.json"
        try:
            self.cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.cache = {}
        self.lock = threading.Lock()

    def digest(self, rel, trust_cache=True):
        """本地文件的 sha256;按 (size, mtime_ns) 缓存。[基础设施]"""
        path = self.root / rel
        st = path.stat()
        key = [st.st_size, st.st_mtime_ns]
        hit = self.cache.get(rel)
        if trust_cache and hit and hit[:2] == key:
            return hit[2]
        value = sha256_file(path)
        with self.lock:
            self.cache[rel] = key + [value]
        return value

    def in_sync(self, rel, row, trust_cache=True):
        """本地该路径的大小和 sha256 是否都与远端清单一致。[基础设施]"""
        path = self.root / rel
        return path.is_file() and path.stat().st_size == row["size"] and self.digest(rel, trust_cache) == row["sha256"]

    def displace(self, rel):
        """把本地现有文件移到本轮备份目录的同一相对路径,不删除。[基础设施]"""
        target = self.displaced_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(self.root / rel, target)
        self.displaced.append(rel)

    def install(self, staged, rel, row):
        """校验暂存文件后放到目标路径;结果路径上已有的不同文件先移走。[基础设施]

        Args:
            staged: 与 root 同一磁盘的暂存文件。
            rel: 相对 root 的目标路径。
            row: 远端清单行,含 size 与 sha256。
        """
        if staged.stat().st_size != row["size"] or sha256_file(staged) != row["sha256"]:
            staged.unlink()
            raise ValueError(f"verification failed for {rel}")
        dest = self.root / rel
        with self.lock:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() and not rel.startswith(self.state + "/"):  # under state_dir both copies came from the remote
                self.displace(rel)
            os.replace(staged, dest)
            st = dest.stat()
            self.cache[rel] = [st.st_size, st.st_mtime_ns, row["sha256"]]

    def strays(self, units, files, exclude):
        """远端已完成的任务项目录里,本地有而远端清单没有的文件。[基础设施]"""
        found = []
        for unit in sorted(units):
            base = self.root / unit
            if not base.is_dir():
                continue
            for path in base.rglob("*"):
                rel = path.relative_to(self.root).as_posix()
                if path.is_file() and not exclude.intersection(path.parts) and rel not in files:
                    found.append(rel)
        return found

    def save(self):
        """落盘哈希缓存。[基础设施]"""
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache), encoding="utf-8")
        os.replace(tmp, self.cache_path)


def make_jobs(pending):
    """把待取文件切成传输任务:小文件按批打 tar,大文件按字节区间。[基础设施]

    Args:
        pending: [(rel, row)],按清单顺序。
    Returns:
        (batches, big):batches 为若干 [(rel,row)] 列表,big 为需分段的 [(rel,row)]。
    """
    batches, big, current, size = [], [], [], 0
    for rel, row in pending:
        if row["size"] > CHUNK:
            big.append((rel, row))
            continue
        if current and (size + row["size"] > BATCH_BYTES or len(current) >= BATCH_FILES):
            batches.append(current)
            current, size = [], 0
        current.append((rel, row))
        size += row["size"]
    if current:
        batches.append(current)
    return batches, big


def fetch_batch(remote, tree, batch, stage):
    """一条连接取回一批小文件:远端 tar 流 → 暂存 → 逐个校验落盘。[基础设施]

    文件名清单在独立线程里写入,与读取 tar 流并行;整条连接(含远端退出)超过 BATCH_TIMEOUT 秒则终止。
    单个成员失败不打断同批其余成员。

    Returns:
        本批落盘的字节数;有成员缺失或失败则抛错并列出原因(已落盘的保留)。
    """
    by_member = {row["src"].lstrip("/"): (rel, row) for rel, row in batch}
    names = "\0".join(by_member).encode("utf-8")
    got, bad = 0, []
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(remote.base + ["tar -C / -cf - --hard-dereference --null -T -"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=err)
        watchdog = threading.Timer(BATCH_TIMEOUT, proc.kill)
        watchdog.start()

        def feed():
            """把文件名清单写给远端 tar 后关闭其标准输入。[基础设施]"""
            try:
                proc.stdin.write(names)
                proc.stdin.close()
            except OSError:
                pass  # the connection died; the reader below reports it

        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()
        try:
            with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
                for member in archive:
                    if not member.isfile() or member.name not in by_member:
                        bad.append(f"unexpected tar member {member.name!r}")
                        continue
                    rel, row = by_member.pop(member.name)
                    staged = stage / f"{row['sha256'][:24]}.{threading.get_ident()}.part"
                    try:
                        with open(staged, "wb") as fh:
                            shutil.copyfileobj(archive.extractfile(member), fh, 1 << 20)
                        tree.install(staged, rel, row)
                        got += row["size"]
                    except (OSError, ValueError) as error:
                        bad.append(f"{rel}: {error!r}")
        except (OSError, tarfile.TarError) as error:  # truncated stream
            bad.append(repr(error))
        finally:
            proc.stdout.close()
            code = proc.wait()  # bounded by the watchdog
            watchdog.cancel()
            feeder.join(5)
        if bad or by_member or code != 0:
            err.seek(0)
            raise RuntimeError(f"batch incomplete: {len(by_member)} not received, {len(bad)} failed {bad[:3]}; "
                               f"ssh/tar exit {code}: {err.read().decode('utf-8', 'replace')[-300:]}")
    return got


def fetch_big(remote, tree, rel, row, stage, workers):
    """大文件按字节区间多连接并取,拼接后整体校验落盘。[基础设施]"""
    src = shlex.quote(row["src"])
    ranges = [(off, min(CHUNK, row["size"] - off)) for off in range(0, row["size"], CHUNK)]
    parts = stage / f"{row['sha256'][:24]}.parts"
    parts.mkdir(exist_ok=True)

    def one(index):
        """取一个区间;已有且长度正确的分片复用。[基础设施]"""
        off, length = ranges[index]
        part = parts / f"{index:06d}"
        if part.is_file() and part.stat().st_size == length:
            return
        data = remote.run(f"tail -c +{off + 1} {src} | head -c {length}", timeout=3600)
        if len(data) != length:
            raise RuntimeError(f"short range {index} of {rel}: {len(data)} != {length}")
        tmp = part.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, part)

    with ThreadPoolExecutor(workers) as pool:
        for future in as_completed([pool.submit(one, i) for i in range(len(ranges))]):
            future.result()
    staged = stage / f"{row['sha256'][:24]}.whole.part"
    with open(staged, "wb") as fh:
        for index in range(len(ranges)):
            with open(parts / f"{index:06d}", "rb") as part:
                shutil.copyfileobj(part, fh, 1 << 20)
    try:
        tree.install(staged, rel, row)
    finally:  # verified → not needed; failed → a part is bad and must not be reused
        shutil.rmtree(parts, ignore_errors=True)
    return row["size"]


def unit_counts(units, files, tree):
    """按上级目录汇总:远端已完成的任务项数 / 其中本地已同步的个数。[基础设施]"""
    counts = {}
    for unit in sorted(units):
        parent = str(PurePosixPath(unit).parent)
        entry = counts.setdefault(parent, {"remote_finished": 0, "local_in_sync": 0})
        entry["remote_finished"] += 1
        entry["local_in_sync"] += all(tree.in_sync(rel, row) for rel, row in files.items() if rel.startswith(unit + "/"))
    return counts


def hold_lock(path):
    """对锁文件加操作系统级独占锁并保持句柄;进程结束(含被杀)时系统自动释放。[基础设施]

    Returns:
        已加锁的文件对象;另一进程持有时返回 None。
    """
    handle = open(path, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def main():
    """读配置、取锁、跑一轮回传;任何异常记入状态文件并以 5 退出。[基础设施]"""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("config", type=Path, help="JSON config; see sync_config.example.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be fetched and displaced; no result file is fetched or moved")
    parser.add_argument("--final", action="store_true", help="last pass, after every remote writer is stopped")
    args = parser.parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tree = lock = None
    try:
        cfg = json.loads(args.config.read_text(encoding="utf-8"))
        cfg.setdefault("state_dir", "_remote_sync")
        if not cfg["state_dir"] or "/" in cfg["state_dir"] or cfg["state_dir"] in (".", ".."):
            raise ValueError("state_dir must be a single directory name")
        tree = LocalTree(Path(cfg["local_root"]).expanduser(), cfg["state_dir"], stamp)
        waited = 0
        while (lock := hold_lock(tree.meta / "sync.lock")) is None:
            if not args.final or waited >= 3600:  # a periodic pass yields; the final pass waits for the running one
                print("SYNC SKIPPED: another pass is running")
                return 4
            time.sleep(15)
            waited += 15
        return sync(args, cfg, Remote(cfg), tree, stamp)
    except Exception as error:
        if tree is not None:
            crash = dict(time=stamp, final=args.final, error=repr(error)[:500])
            (tree.meta / "sync_state.json").write_text(json.dumps(crash, indent=1, ensure_ascii=False), encoding="utf-8")
            with open(tree.meta / "sync_history.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(crash, ensure_ascii=False) + "\n")
        print(f"SYNC CRASHED: {error!r}")
        return 5
    finally:
        if tree is not None and lock is not None:
            try:
                tree.save()
            finally:
                lock.close()


def sync(args, cfg, remote, tree, stamp):
    """一轮回传:取清单 → 判差异 → 并行取回并校验 → 移走本地多余文件 → 写状态。[基础设施]"""
    if args.final:
        if "writer_pattern" not in cfg:
            print("SYNC REFUSED: --final needs writer_pattern in the config")
            return 6
        if remote.writers_running():
            print("SYNC REFUSED: --final while remote writers are running")
            return 6
    exclude = set(cfg.get("exclude_dirs", []))
    workers = int(cfg.get("workers", 16))
    listing = remote.manifest(args.final)
    files, units = listing["files"], listing["units"]
    blocked = {**listing["skipped"], **unstorable(files)}
    for rel in unstorable(files):
        files.pop(rel)
    trust = not args.final
    pending = [(rel, row) for rel, row in files.items() if not tree.in_sync(rel, row, trust)]
    need = sum(row["size"] for _, row in pending)
    largest = max((row["size"] for _, row in pending if row["size"] > CHUNK), default=0)  # parts + assembled copy
    free = shutil.disk_usage(tree.root).free
    in_units = sum(any(rel.startswith(u + "/") for u in units) for rel in files)
    print(f"manifest: {len(files)} files, {sum(r['size'] for r in files.values()) / 2**30:.2f} GiB "
          f"({len(units)} finished units holding {in_units} files, {len(listing['withheld'])} unfinished units withheld); "
          f"to fetch: {len(pending)} files, {need / 2**30:.2f} GiB; local free {free / 2**30:.1f} GiB")
    for rel, why in list(blocked.items())[:20]:
        print(f"  NOT SYNCABLE {rel}: {why}")
    if need + largest + (2 << 30) > free:
        print("SYNC REFUSED: not enough local disk space (fetch size + largest ranged file + 2 GiB)")
        return 3
    if args.dry_run:
        moves = [rel for rel, _ in pending if (tree.root / rel).exists() and not rel.startswith(tree.state + "/")]
        moves += tree.strays(units, files, exclude)
        (tree.meta / "dry_run_displace.txt").write_text("\n".join(moves), encoding="utf-8")
        print(json.dumps(unit_counts(units, files, tree), indent=1))
        print(f"SYNC DRY-RUN: would fetch {len(pending)} files and displace {len(moves)} local files "
              f"(list: {tree.meta / 'dry_run_displace.txt'}); {len(blocked)} not syncable")
        return 0

    stage = tree.meta / ".staging"
    stage.mkdir(exist_ok=True)
    for leftover in stage.glob("*.part"):
        leftover.unlink()
    fetched, failures, started = 0, [], time.time()
    for attempt in range(3):  # retry only what is still missing
        if attempt:
            pending = [(rel, row) for rel, row in files.items() if not tree.in_sync(rel, row)]
            if not pending:
                break
            print(f"  retry {attempt}: {len(pending)} files still missing", flush=True)
            time.sleep(10)
        failures = []
        batches, big = make_jobs(pending)
        for rel, row in big:
            try:
                fetched += fetch_big(remote, tree, rel, row, stage, workers)
            except Exception as error:  # one bad file must not block the rest of the pass
                failures.append(f"{rel}: {error}")
        with ThreadPoolExecutor(workers) as pool:
            futures = [pool.submit(fetch_batch, remote, tree, batch, stage) for batch in batches]
            for count, future in enumerate(as_completed(futures), 1):
                try:
                    fetched += future.result()
                except Exception as error:
                    failures.append(str(error)[:400])
                if count % 20 == 0 or count == len(futures):
                    rate = fetched / 2**20 / max(time.time() - started, 1)
                    print(f"  {count}/{len(futures)} batches, {fetched / 2**30:.2f} GiB, {rate:.1f} MiB/s", flush=True)

    left = [rel for rel, row in files.items() if not tree.in_sync(rel, row)]
    if not left:  # tidy strays only once every listed file is verified in place
        for rel in tree.strays(units, files, exclude):
            with tree.lock:
                tree.displace(rel)
    settled = True
    if args.final:  # the remote must be quiet and unchanged for "final" to mean anything
        again = remote.manifest(True)
        same = lambda a, b: ({r: (v["size"], v["sha256"]) for r, v in a["files"].items()} ==
                             {r: (v["size"], v["sha256"]) for r, v in b["files"].items()})
        again_files = dict(again["files"])
        for rel in unstorable(again_files):
            again_files.pop(rel)
        settled = (same({"files": again_files}, {"files": files}) and again["units"] == units
                   and again["skipped"] == listing["skipped"] and not remote.writers_running())
    with open(tree.meta / "manifest.jsonl", "w", encoding="utf-8") as fh:  # what this pass verified, file by file
        for rel, row in files.items():
            fh.write(json.dumps(dict(rel=rel, size=row["size"], sha256=row["sha256"], in_sync=rel not in left)) + "\n")
    state = dict(time=stamp, final=args.final, manifest_files=len(files), fetched_bytes=fetched,
                 not_in_sync=left, not_syncable=blocked, withheld_unfinished=listing["withheld"], settled=settled,
                 displaced=tree.displaced, displaced_dir=str(tree.displaced_dir), failures=failures,
                 units=unit_counts(units, files, tree))
    (tree.meta / "sync_state.json").write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    with open(tree.meta / "sync_history.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(state, ensure_ascii=False) + "\n")
    for line in failures[:10]:
        print("  FAIL", line)
    for rel in left[:20]:
        print("  NOT IN SYNC", rel)
    ok = not left and not blocked and settled
    if ok and args.final:
        verdict = "VERIFIED FINAL"
    elif ok:
        verdict = "UP-TO-DATE"
    elif not settled:
        verdict = "INCOMPLETE (remote changed or writers appeared during --final)"
    else:
        verdict = "INCOMPLETE"
    print(f"SYNC {verdict}: {len(files) - len(left)}/{len(files)} files in place, {len(blocked)} not syncable, "
          f"{len(listing['withheld'])} unfinished units withheld, fetched {fetched / 2**30:.2f} GiB, "
          f"displaced {len(tree.displaced)} local files, {time.strftime('%H:%M:%S')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
