#!/usr/bin/env python3
"""Register, finish and check experiment records using the standard library."""
import argparse
import csv
from datetime import date
import os
import tempfile
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

COLUMNS = ["task", "简介", "指标", "结论", "输出目录"]
TEST_SET_LINE = re.compile(r"^ {0,3}[-*]\s*正式测试集[:：](.*)$", re.M)
NUMBER_END = r"(?!\w|[.,，]\d)"
TEST_SET = re.compile(r"\s*(\S+)(.*)")
COUNT = re.compile(r"(?<![A-Za-z0-9_])N\s*=\s*(\S*)")
FIELD = re.compile(r"^ {0,3}[-*]\s*(对照方|训练条件|调参)[:：][ \t]*(\S.*)$", re.M)
PROTOCOL_HEADING = re.compile(r"^##[ \t]*对照协议(?:[ \t]*[（(][^）)\n]*[）)])?[ \t]*$", re.M)
BUDGET = r"(?:每方(?:自动调参)?\s*(?P<n>\d+)\s*次|不调参)"
CONFIRMED = re.compile(BUDGET + r"\s*[（(]用户\s*(?P<date>\d{4}-\d{2}-\d{2})\s*确认[）)]")
INHERITED = re.compile(r"沿用\s*(?P<src>\S+?)\s*的\s*" + BUDGET + r"\s*[，,]\s*未确认")
EVALUATION_ONLY = re.compile(r"只评测[，,]\s*不调参(?:\s*[（(][^）)]*[）)])?")


def unfenced(text):
    """Yield (line number, line) outside fenced code; examples there are not records."""
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is None:
            yield number, line


def readme_text(folder):
    """The folder's README outside fenced code, or empty when there is none."""
    path = folder / "README.md"
    if not path.is_file():
        return ""
    return "\n".join(line for _, line in unfenced(path.read_text(encoding="utf-8")))


def protocol_fields(text):
    """Fields of the `## 对照协议` section, or None when the text has no such section."""
    heading = PROTOCOL_HEADING.search(text)
    if not heading:
        return None
    section = re.split(r"^#{1,2}[ \t]", text[heading.end():], maxsplit=1, flags=re.M)[0]
    return dict(FIELD.findall(section))


def formal_test_sets(folder, records, own_first=False):
    """Collect 正式测试集 as {path: N or None} from folder up to records.

    None means the whole path is tested. A lower level may add a set, never change one declared above.
    With `own_first` (an evaluation-only group), sets declared in the group itself replace the inherited ones.

    变更: 2026-09-24 evaluation-only groups may evaluate on their own benchmarks instead of the inherited sets.
    """
    sets, problems = {}, []
    while folder.is_relative_to(records):
        for line in TEST_SET_LINE.findall(readme_text(folder)):
            declared = TEST_SET.match(line)
            if not declared:
                problems.append("正式测试集要写路径，只测一部分时加 N=数量")
                continue
            count = COUNT.search(declared[2])
            size = count and re.match(r"[1-9]\d*" + NUMBER_END, count[1])
            if count and not size:
                problems.append(f"正式测试集的 N 要写成正整数，现在是「{line.strip()}」")
                continue
            path, size = declared[1].rstrip("/") or "/", size and int(size[0])
            if sets.setdefault(path, size) != size:
                problems.append(f"正式测试集 {path} 被声明了不同的 N，只能保留一个")
        if own_first and (sets or problems):
            break
        folder = folder.parent
    return sets, problems


def tuning_problem(line, records, latest=False):
    """Why a 调参 line is none of the accepted forms; None when it is one.

    A reused budget must come from a user confirmation under records. `latest` is checked only when
    the group is opened, so a later confirmation elsewhere never invalidates a frozen protocol.
    `只评测，不调参` needs no confirmation: the group only evaluates frozen methods.

    变更: 2026-09-24 accept `只评测，不调参` for groups that neither train nor tune.
    """
    if CONFIRMED.fullmatch(line.strip()) or EVALUATION_ONLY.fullmatch(line.strip()):
        return None
    inherited = INHERITED.fullmatch(line.strip())
    if not inherited:
        return ("调参只能写成「每方自动调参 N 次（用户 YYYY-MM-DD 确认）」「不调参（用户 YYYY-MM-DD 确认）」"
                "「沿用 <组> 的每方 N 次，未确认」，只评测已冻结的方法时写「只评测，不调参」")
    confirmed = {}
    for readme in records.rglob("README.md"):
        answer = CONFIRMED.fullmatch((protocol_fields(readme_text(readme.parent)) or {}).get("调参", "").strip())
        if answer:
            confirmed[readme.parent.resolve()] = (answer["date"], int(answer["n"] or 0))
    source = confirmed.get((records / inherited["src"]).resolve())
    if not source or source[1] != int(inherited["n"] or 0):
        return f"调参沿用的 {inherited['src']} 里没有用户确认过的相同次数"
    if latest and source[0] != max(date for date, _ in confirmed.values()):
        return f"调参沿用的 {inherited['src']} 不是记录里最近一次用户确认的组"
    return None


def read_protocol(csv_path, records, opening=False):
    """Return the group's comparison protocol, or None when its README has none."""
    fields = protocol_fields(readme_text(csv_path.parent))
    if fields is None:
        return None
    problems = [f"缺少「{name}」" for name in ("对照方", "训练条件", "调参") if name not in fields]
    arms = [arm for arm in re.split(r"[,，、\s]+", fields.get("对照方", "")) if arm]
    evaluation_only = bool(EVALUATION_ONLY.fullmatch(fields.get("调参", "").strip()))
    if "对照方" in fields and (len(arms) < (1 if evaluation_only else 2) or len(set(arms)) < len(arms)):
        problems.append("对照方要写至少两个不同的名字（只评测的组可以只有一个）")
    if "调参" in fields and (issue := tuning_problem(fields["调参"], records, latest=opening)):
        problems.append(issue)
    test_sets, set_problems = formal_test_sets(csv_path.parent, records, own_first=evaluation_only)
    if not test_sets and not set_problems:
        set_problems = ["缺少「正式测试集」（写法：- 正式测试集: <路径>，只测一部分时加 N=数量）"]
    return {"readme": csv_path.parent / "README.md", "problems": problems + set_problems,
            "arms": arms, "test_sets": test_sets}


def check_protocol_metrics(metrics, protocol, location, report):
    """Require every mention of each formal test set to claim a full run.

    With N declared the claim is `@data/coco5k 5000/5000`; without N it is `@data/coco5k 全部`,
    and the sample count is deliberately not verified.
    """
    for path, size in protocol["test_sets"].items():
        tag = "@" + re.escape(path) + "/?"
        full = rf"\s+{size}\s*/\s*{size}" + NUMBER_END if size else r"\s+全部"
        mentions = re.findall(tag + r"(?!\S)", metrics)
        if not mentions or len(re.findall(tag + full, metrics)) != len(mentions):
            expected = f"{size}/{size}" if size else "全部"
            report("ERROR", location, f"metrics must be measured on the full formal test set: @{path} {expected}")


def check_csv(path, root, outputs, report, *, check_outputs=True, protocol=None):
    """Report CSV shape, state and output-reference problems without editing it.

    变更: 2026-09-08 写入时可跳过输出可用性检查；exp-check 仍报告缺失产物。
    变更: 2026-09-23 有对照协议的组检查对照方前缀、正式测试集全量、crash/timeout 不填数字，
    以及 summary 前各方都已重跑。
    """
    count = 0
    seen = set()
    finished = {arm: 0 for arm in protocol["arms"]} if protocol else {}
    summary = None
    claimed = False
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        if reader.fieldnames != COLUMNS:
            report("ERROR", path, "expected columns: " + ",".join(COLUMNS))
            return count
        for row in reader:
            location = f"{path}:{reader.line_num}"
            count += 1
            if None in row or any(value is None for value in row.values()):
                report("ERROR", location, "malformed CSV row")
                continue
            task = row["task"]
            if not task.strip() or task in {".", ".."} or "/" in task or "\\" in task:
                report("ERROR", location, "invalid task")
            if task in seen:
                report("ERROR", location, f"duplicate task: {task}")
            seen.add(task)
            output = row["输出目录"]
            if task == "summary":
                if protocol:
                    summary = location
                    claimed = row["指标"].strip() not in {"", "—"}
                    if claimed:
                        check_protocol_metrics(row["指标"], protocol, location, report)
                # Summary may reference the winner, an analysis directory, or no baseline.
                if check_outputs and output.strip() not in {"", "—"} and not (root / output).is_dir():
                    report("ERROR", location, f"summary output missing: {output}")
                continue
            if not row["简介"].strip():
                report("ERROR", location, "missing experiment plan")
            arm = next((a for a in finished if re.match(re.escape(a) + r"\s*[:：]", row["简介"])), None)
            if protocol and arm is None:
                report("ERROR", location, "简介 must start with its 对照方: " + ", ".join(protocol["arms"]))
            if output.strip() in {"", "—"}:
                report("ERROR", location, "missing output path")
                continue
            destination = (root / output).resolve()
            if Path(output).name != task:
                report("ERROR", location, "output leaf does not match task")
            if destination in outputs:
                report("WARN", location, f"output also referenced by {outputs[destination]}")
            else:
                outputs[destination] = location
            conclusion = row["结论"].strip()
            if conclusion:
                if not re.match(r"^(keep|discard|crash|timeout)(?:\s|:|：)", conclusion):
                    report("ERROR", location, "invalid conclusion status")
                if not row["指标"].strip():
                    report("ERROR", location, "missing metrics; use — when unavailable")
                if protocol and re.match(r"^(keep|discard)", conclusion):
                    check_protocol_metrics(row["指标"], protocol, location, report)
                    if arm:
                        finished[arm] += 1
                elif protocol and row["指标"].strip() != "—":
                    report("ERROR", location, "crash/timeout in a comparison group records 指标 as —; "
                           "partial numbers stay in the logs")
                if check_outputs and not destination.is_dir():
                    report("ERROR", location, f"finished output missing: {output}")
            elif check_outputs and destination.exists() and not destination.is_dir():
                report("ERROR", location, f"output is not a directory: {output}")
    # Like output availability, group completeness is left to exp-check: adding the missing rerun must stay possible.
    # Only a group where no arm reached the formal test set may close without comparing every arm.
    if summary and check_outputs and (claimed or any(finished.values())):
        absent = [arm for arm, n in finished.items() if n == 0]
        if absent:
            report("ERROR", summary, "summary before every 对照方 was rerun in this group: " + ", ".join(absent))
        elif len(set(finished.values())) > 1:
            counts = ", ".join(f"{arm}={n}" for arm, n in finished.items())
            report("WARN", summary, f"对照方 finished unequal numbers of runs ({counts}); check the tuning budget")
    return count


def check_links(path, report):
    """Check supported inline local links outside Markdown code."""
    # Deliberately limited to inline Markdown links; fenced code is not evidence.
    for number, line in unfenced(path.read_text(encoding="utf-8")):
        line = re.sub(r"(`+).*?\1", "", line)
        for match in re.finditer(r"\[[^\]\n]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+\"[^\"]*\")?\s*\)", line):
            target = match[1] or match[2]
            parts = urlsplit(target)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            destination = path.parent / unquote(parts.path)
            if not destination.exists():
                report("ERROR", f"{path}:{number}", f"broken local link: {target}")


def check_experiments(args):
    """Scan only the requested scope and return bounded diagnostics."""
    counts = {"ERROR": 0, "WARN": 0}

    def report(level, location, message):
        """Count every finding but print only the requested number."""
        counts[level] += 1
        if sum(counts.values()) <= max(0, args.limit):
            print(f"{level} {location}: {message}")

    try:
        root = args.root.resolve()
        records = (root / args.records).resolve()
        scope = (records / args.scope).resolve() if args.scope else records
        if not records.is_dir() or not records.is_relative_to(root):
            raise ValueError("records must be an existing directory inside root")
        if not scope.exists() or not scope.is_relative_to(records):
            raise ValueError("scope must exist inside records")
        files = sorted(scope.rglob("*")) if scope.is_dir() else [scope]
        files = [p for p in files if p.is_file() and p.suffix.lower() in {".csv", ".md"}]
        if not files:
            raise ValueError("no CSV or Markdown files in scope")
        outputs = {}
        rows = csv_count = md_count = 0
        for path in files:
            try:
                if path.suffix.lower() == ".csv":
                    csv_count += 1
                    protocol = read_protocol(path, records)
                    if protocol and protocol["problems"]:
                        report("ERROR", protocol["readme"], "对照协议有问题：" + "；".join(protocol["problems"]))
                    rows += check_csv(path, root, outputs, report, protocol=protocol)
                else:
                    md_count += 1
                    check_links(path, report)
            except (OSError, ValueError, csv.Error) as error:
                report("ERROR", path, str(error))
        print(f"Checked scope={scope}; CSV={csv_count}, rows={rows}, Markdown={md_count}; "
              f"errors={counts['ERROR']}, warnings={counts['WARN']}")
        omitted = sum(counts.values()) - max(0, args.limit)
        if omitted > 0:
            print(f"{omitted} diagnostics omitted; increase --limit for details")
        return 1 if counts["ERROR"] else 0
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1


def write_experiment(args):
    """Append a plan or finish one pending row; validate before replacing the CSV.

    变更: 2026-09-08 输出存在或缺失不再阻止登记；格式与覆盖保护保留。
    """
    root = args.root.resolve()
    records = (root / args.records).resolve()
    path = (records / args.csv).resolve()
    if not records.is_relative_to(root) or not path.is_relative_to(records) or path.suffix != ".csv":
        raise ValueError("CSV must be inside records and end in .csv")
    if args.task == "summary":
        raise ValueError("summary is a group conclusion, not an experiment attempt")
    planning = args.operation == "plan"
    if not planning and not path.is_file():
        raise ValueError("experiment CSV not found")
    protocol = read_protocol(path, records, opening=planning and not path.exists())
    if protocol and protocol["problems"]:
        raise ValueError("对照协议有问题：" + "；".join(protocol["problems"]) + f"（{protocol['readme']}）")
    if planning and protocol is None and any(formal_test_sets(path.parent, records)):
        print("WARN: a formal test set is declared but this group has no 对照协议; "
              "write one before comparing methods")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    # Exclusive lock protects read-modify-write among these CLI writers; never steal a stale lock.
    with lock.open("x"):
        pass
    temporary = None
    try:
        original = path.read_bytes() if path.exists() else None
        rows = []
        if original is not None:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream, strict=True)
                if reader.fieldnames != COLUMNS:
                    raise ValueError("expected standard five-column experiment CSV")
                rows = list(reader)
                if any(None in row or any(value is None for value in row.values()) for row in rows):
                    raise ValueError("malformed existing CSV row")
        matches = [row for row in rows if row["task"] == args.task]
        if planning:
            if matches:
                raise ValueError("task already registered; inspect it before resuming")
            rows.append(dict(zip(COLUMNS, [args.task, args.purpose, "", "", args.output])))
        else:
            if len(matches) != 1:
                raise ValueError("expected exactly one registered task")
            if matches[0]["结论"].strip():
                raise ValueError("result already recorded; review corrections explicitly")
            if not args.conclusion.strip():
                raise ValueError("conclusion reason is required")
            matches[0].update({"指标": args.metrics, "结论": args.status + "：" + args.conclusion})
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                         prefix="." + path.name, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        errors = []
        def report(level, location, message):
            """Reject invalid candidate records before touching the original CSV."""
            if level == "ERROR":
                errors.append(message)
            else:
                print(f"WARN: {message}")
        check_csv(temporary, root, {}, report, check_outputs=False, protocol=protocol)
        if errors:
            raise ValueError("; ".join(errors[:5]))
        if (path.read_bytes() if path.exists() else None) != original:
            raise ValueError("CSV changed outside this command; retry after inspection")
        if original is not None:
            os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
        print(f"Recorded {args.task}: {path}")
        return 0
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink()


CONSOLIDATED = "record: 整理结论"


def records_root(args):
    """Resolve the records directory for exp-changes."""
    root = args.root.resolve()
    records = (root / args.records).resolve()
    if not records.is_dir() or not records.is_relative_to(root):
        raise ValueError("records must be an existing directory inside root")
    return records


def git(records, *args):
    """Run git inside records and return stdout; any failure becomes a readable error.

    `--no-optional-locks` keeps `git status` from rewriting the index, so the command stays read-only
    while other sessions use the same repository.
    """
    result = subprocess.run(["git", "--no-optional-locks", "-C", str(records), *args], capture_output=True, text=True)
    if result.returncode:
        raise ValueError("git " + args[0] + " failed: " + (result.stderr.strip() or "records must be in a git repository"))
    return result.stdout


def show_changes(args):
    """List committed changes under records since the last consolidation on the main line. Read-only.

    The last consolidation is the newest first-parent commit whose subject starts with `record: 整理结论`;
    without one, every committed file counts as not yet consolidated. Paths come NUL-separated so git
    never escapes non-ASCII names.
    """
    records = records_root(args)
    last = None
    for line in git(records, "log", "--first-parent", "--format=%H %cs %s").splitlines():
        sha, day, subject = line.split(" ", 2)
        if subject.startswith(CONSOLIDATED):
            last = (sha, day)
            break
    if last:
        fields = git(records, "diff", "--relative", "--no-renames", "--name-status", "-z", last[0], "HEAD", "--", ".")
        fields = fields.split("\0")
        kinds = {"A": "新增", "D": "删除"}
        changed = [(kinds.get(status[0], "改动"), path) for status, path in zip(fields[::2], fields[1::2])]
    else:
        tree = git(records, "ls-tree", "-r", "--name-only", "-z", "HEAD", "--", ".")
        changed = [("未整理", path) for path in tree.split("\0") if path]
    folders = {}
    for kind, path in changed:
        folder, _, name = path.rpartition("/")
        folders.setdefault(folder, {}).setdefault(kind, []).append(name)
    if not last:
        print(f"还没整理过（主线上没有标题以「{CONSOLIDATED}」开头的提交）：{len(folders)} 个目录都算未整理")
    elif not folders:
        print(f"上次整理：{last[1]}（{last[0][:7]}）；之后没有变化")
    else:
        commits = git(records, "log", "--first-parent", "--format=%cs %s", f"{last[0]}..HEAD", "--", ".").splitlines()
        print(f"上次整理：{last[1]}（{last[0][:7]}）；之后主线上的提交 {len(commits)} 个：")
        for line in commits:
            print(f"  {line}")
        print(f"有变化的目录 {len(folders)} 个：")
    for folder, names in folders.items():
        print(f"  {folder + '/' if folder else '（根目录）'}  " + "；".join(f"{kind} {'、'.join(files)}" for kind, files in names.items()))
    days = (date.today() - date.fromisoformat(last[1])).days if last else 0
    if folders and (not last or len(folders) >= 3 or days >= 7):
        reason = "还没整理过" if not last else f"{len(folders)} 个目录有变化" + (f"，距上次整理 {days} 天" if days else "")
        print(f"建议现在整理：{reason}")
    if folders:
        print(f"整理完提交「{CONSOLIDATED} —— <概要>」；看过不用改就提交空提交：git commit --allow-empty -m "
              f"\"{CONSOLIDATED} —— 看过，无需修改\"")
    if git(records, "status", "--porcelain", "--", "."):
        print("记录根目录下有未提交的改动，没算在内")
    return 0


# Public names live here; rename a key without changing the operation or implementation.
COMMANDS = {
    "exp-plan": (write_experiment, "plan"),
    "exp-finish": (write_experiment, "finish"),
    "exp-check": (check_experiments, "check"),
    "exp-changes": (show_changes, "changes"),
}


def main():
    """Parse experiment-specific commands; report failures without modifying old records.

    变更: 2026-09-08 check renamed exp-check; added explicit plan and finish writes.
    变更: 2026-09-23 added exp-changes for periodic conclusion review.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, (handler, operation) in COMMANDS.items():
        command = commands.add_parser(name)
        command.set_defaults(handler=handler, operation=operation)
        command.add_argument("--root", type=Path, required=True, help="project root and CSV output-path base")
        command.add_argument("--records", type=Path, required=True, help="records directory relative to root")
        if operation == "check":
            command.add_argument("--scope", type=Path, help="file/subdirectory relative to records")
            command.add_argument("--limit", type=int, default=20, help="maximum diagnostic lines")
        elif operation in ("plan", "finish"):
            command.add_argument("--csv", type=Path, required=True, help="CSV path relative to records")
            command.add_argument("--task", required=True)
            if operation == "plan":
                command.add_argument("--purpose", required=True, help="why this experiment is needed")
                command.add_argument("--output", required=True, help="actual output path relative to root")
            else:
                command.add_argument("--metrics", required=True)
                command.add_argument("--status", required=True, choices=["keep", "discard", "crash", "timeout"])
                command.add_argument("--conclusion", required=True, help="reason and next step")
    args = parser.parse_args()
    try:
        return args.handler(args)
    except (OSError, ValueError, csv.Error, KeyError, TypeError) as error:
        print(f"ERROR: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
