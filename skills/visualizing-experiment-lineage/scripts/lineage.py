#!/usr/bin/env python3
"""把实验组的 CSV 记录和 git 历史拼成一张自顶向下的谱系页。

节点来自 CSV(为什么试、指标、结论),边来自 git(哪次基于哪份代码),叙述来自
各级 README。不新增任何数据:页面是派生物,改了记录重跑一次就行。

一个节点 = 一次决策 = 一个 commit:标题含 task 名、且改动了本组 CSV。批量扫描
一个 commit 多行,就是一个节点多行。节点的父 = 沿 first-parent 往上遇到的第一个
「带 task 行且改了代码」的 commit:

- 快速迭代里 discard 只提交记录、代码进 stash,下一次 keep 的父自然跳过它;
- 构建期失败代码也进分支,下一次确实基于它,就照实画;
- 途中遇到合并节点就钻进第二个父,找到被合并那组最后一次带代码的决策 —— 跨组边。

没有 git、或某行对不上 commit,退回行序:父 = 同一 CSV 里上一个 keep 行,标成推断。
"""
import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

COLUMNS = ["task", "简介", "指标", "结论", "输出目录"]
STATUS_RE = re.compile(r"^(keep|discard|crash|timeout)(?=\s|:|：|$)")
TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "lineage.html"
MARK = "/*__LINEAGE_DATA__*/"


def status_of(conclusion):
    """从结论列读出状态词。[基础设施]

    Args:
        conclusion: CSV「结论」原文。

    Returns:
        keep / discard / crash / timeout;空串是 pending(还没跑完),
        非空但不以状态词开头是 unknown —— 页面要把它标出来,不猜。
    """
    text = conclusion.strip()
    if not text:
        return "pending"
    m = STATUS_RE.match(text)
    return m.group(1) if m else "unknown"


def read_group(path, records, notes):
    """读一个组:CSV 各行、summary 行、组 README 的第一段。[主线]

    Args:
        path: CSV 绝对路径。
        records: 记录根目录(绝对路径),组 id 相对它。
        notes: list,列结构不对时往里追加一条,页脚要列出。

    Returns:
        dict:id / section / csv / readme / intro / summary / rows。
        `exploration/attn/results.csv` 和旧布局 `exploration/attn.csv` 都算组
        `exploration/attn`。列结构不对时 rows 为空,组仍返回,页面上能看到它被跳过。
    """
    rel = path.relative_to(records).as_posix()
    gid = rel[:-4]
    if gid.endswith("/results"):
        gid = gid[:-len("/results")]
    group = {"id": gid, "section": gid.split("/")[0], "csv": rel,
             "readme": None, "intro": "", "summary": None, "rows": []}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != COLUMNS:
            notes.append(f"{rel}:列结构不是标准五列,整组跳过")
            return group
        for raw in reader:
            if None in raw or any(v is None for v in raw.values()):
                notes.append(f"{rel}:{reader.line_num} 行格式坏了,跳过")
                continue
            row = {"task": raw["task"].strip(), "purpose": raw["简介"], "metrics": raw["指标"],
                   "conclusion": raw["结论"], "status": status_of(raw["结论"]),
                   "output": raw["输出目录"], "line": reader.line_num, "stash": None}
            if row["task"] == "summary":
                group["summary"] = row
            else:
                group["rows"].append(row)
    readme = path.parent / "README.md" if path.name == "results.csv" else None
    if readme and readme.is_file():
        group["readme"] = readme.relative_to(records).as_posix()
        group["intro"] = first_paragraph(readme.read_text(encoding="utf-8"))
    return group


def first_paragraph(text):
    """取 Markdown 里标题之后的第一段正文。[基础设施]

    Args:
        text: README 全文。

    Returns:
        str,行间用空格连起来;没有正文返回空串。
    """
    lines = []
    for line in text.splitlines():
        if line.startswith("#") or (not lines and not line.strip()):
            continue
        if not line.strip():
            break
        lines.append(line.strip())
    return " ".join(lines)


def section_summaries(records):
    """从总览 README 的表格里取各部分的「当前结论」。[旁支]

    Args:
        records: 记录根目录(绝对路径)。

    Returns:
        dict,{部分名: 当前结论}。表格按 memory.md 的模板:第一列部分、第二列结论。
        没有 README 或没有表格返回空 dict。
    """
    readme = records / "README.md"
    out = {}
    if not readme.is_file():
        return out
    for line in readme.read_text(encoding="utf-8").splitlines():
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] and not set(cells[0]) <= set("-: "):
            out.setdefault(cells[0], cells[1])
    return out


def git_out(root, *args):
    """跑一条 git 命令,失败返回 None。[基础设施]

    Args:
        root: 仓库内任意路径。
        *args: git 子命令和参数。

    Returns:
        stdout 文本;不是仓库、没有提交等一切失败都返回 None。
    """
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else None


def git_history(root):
    """一次读完仓库历史:每个 commit 的父、标题、改了哪些文件。[主线]

    Args:
        root: 项目根目录。

    Returns:
        (prefix, history) —— prefix 是项目根相对仓库根的前缀(monorepo 时非空),
        history 是 {sha: {"parents", "subject", "files"}}。合并提交的 files 为空,
        这是 git 的默认行为,正好让合并节点永远不算「改了代码」。
        不是 git 仓库返回 (None, None);空仓库返回 (prefix, {})。
    """
    prefix = git_out(root, "rev-parse", "--show-prefix")
    if prefix is None:
        return None, None
    log = git_out(root, "log", "--branches", "--tags", "--remotes", "--topo-order",
                  "--format=%x1e%H%x1f%P%x1f%s", "--name-only") or ""
    history = {}
    for record in log.split("\x1e")[1:]:
        head, _, files = record.partition("\n")
        sha, parents, subject = head.split("\x1f")
        history[sha] = {"parents": parents.split(), "subject": subject,
                        "files": [f for f in files.split("\n") if f.strip()]}
    return prefix.strip(), history


def stash_refs(root):
    """本机 stash 列表,用来给 discard 行标上代码在哪。[旁支]

    Args:
        root: 项目根目录。

    Returns:
        list[(ref, message)],如 ("stash@{0}", "On exp/x: exploration/attn/a2")。
    """
    out = git_out(root, "stash", "list", "--format=%gd%x1f%gs") or ""
    return [tuple(line.split("\x1f", 1)) for line in out.splitlines() if "\x1f" in line]


def name_re(name):
    """task 名的整词匹配。[基础设施]

    Args:
        name: task 名。

    Returns:
        编译好的正则。`rank8` 不能命中 `rank8_v2`,所以两侧不能紧挨着名字里会出现的字符。
    """
    return re.compile(r"(?<![\w.\-])" + re.escape(name) + r"(?![\w.\-])")


def match_decisions(groups, history, prefix, records_name):
    """把每一行 CSV 记录配到它的决策 commit 上。[主线]

    Args:
        groups: read_group 的结果列表(范围内外都要,解析跨组边需要)。
        history: git_history 的 history。
        prefix: git_history 的 prefix。
        records_name: 记录根目录相对项目根的名字,判断「改了代码」要排除它。

    Returns:
        dict,{sha: {"group": 组 id, "rows": [行...], "code": 是否改了记录以外的文件}}。
        一行只认最早提到它的那个 commit —— 跑完提交的那次;之后总结行再提它,不算。
        同名 task 可能出现在不同组,所以还要求这个 commit 改过本组的 CSV。
    """
    records_prefix = f"{prefix}{records_name}/"
    csv_of = {f"{records_prefix}{g['csv']}": g for g in groups}
    decisions = {}
    for sha in reversed(list(history)):        # topo 序是新到旧,反过来最早的先配
        entry = history[sha]
        for path in entry["files"]:
            group = csv_of.get(path)
            if group is None:
                continue
            rows = [r for r in group["rows"]
                    if r.get("commit") is None and name_re(r["task"]).search(entry["subject"])]
            if not rows:
                continue
            for r in rows:
                r["commit"] = sha
            code = any(not f.startswith(records_prefix) for f in entry["files"])
            decisions[sha] = {"group": group["id"], "rows": rows, "code": code}
            break
    return decisions


def walk(sha, history, decisions, dive, memo):
    """从 sha 起沿 first-parent 找第一个带代码的决策。[主线]

    Args:
        sha: 起点(含)。
        history: git_history 的 history。
        decisions: match_decisions 的结果。
        dive: 遇到合并提交时要不要钻进第二个父。跨组边靠它;找本组上一步时不钻,
            否则把主分支合进实验分支那一下会把父指到别的组去。
        memo: dict,同一 dive 模式下的缓存,避免长历史反复走。

    Returns:
        决策 commit 的 sha;走到根都没有返回 None。
    """
    path = []
    result = None
    while sha is not None:
        if sha in memo:
            result = memo[sha]
            break
        path.append(sha)
        entry = history.get(sha)
        if sha in decisions and decisions[sha]["code"]:
            result = sha
            break
        if entry is None:
            break
        if dive and len(entry["parents"]) > 1:
            found = walk(entry["parents"][1], history, decisions, True, memo)
            if found:
                result = found
                break
        sha = entry["parents"][0] if entry["parents"] else None
    for s in path:
        memo[s] = result
    return result


def parent_of(sha, gid, history, decisions, memos):
    """一次决策的父决策。[主线]

    Args:
        sha: 这次决策的 commit。
        gid: 它所属的组。
        history: git_history 的 history。
        decisions: match_decisions 的结果。
        memos: {dive: memo} 两份缓存,两种走法各一份。

    Returns:
        父决策的 sha 或 None。先只沿 first-parent 找,落在本组就是它;
        本组里没有(这是组的第一步)再钻合并节点找跨组的来源。
    """
    start = history[sha]["parents"][0] if history[sha]["parents"] else None
    own = walk(start, history, decisions, False, memos[False])
    if own and decisions[own]["group"] == gid:
        return own
    return walk(start, history, decisions, True, memos[True]) or own


def build(root, records_name, scope):
    """读记录、读 git、算边,产出页面要的全部数据。[主线]

    Args:
        root: 项目根目录(Path)。
        records_name: 记录根目录相对项目根的名字。
        scope: 相对记录根的路径,部分或组;只画它,但整个记录根都读进来参与解析。

    Returns:
        dict:generated / root / records / scope / git / section_summary /
        groups / external / notes。节点 id 是 `组@短 sha`,没 commit 的行是 `组#行号`。
    """
    records = root / records_name
    if not (records / scope).exists():
        sys.exit(f"范围不存在:{records / scope}")
    notes = []
    groups = [read_group(p, records, notes) for p in sorted(records.rglob("*.csv"))]
    in_scope = [g for g in groups
                if scope in ("", ".") or g["id"] == scope or g["id"].startswith(scope + "/")]

    prefix, history = git_history(root)
    decisions = {}
    if history is not None:
        decisions = match_decisions(groups, history, prefix, records_name)
        for ref, message in stash_refs(root):
            for g in groups:
                for r in g["rows"]:
                    if r["stash"] is None and name_re(f"{g['id']}/{r['task']}").search(message):
                        r["stash"] = ref

    node_ids = {}                 # 决策 sha → 节点 id
    nodes_of = {}                 # 组 id → 节点列表
    for g in groups:
        nodes = []
        for sha, d in decisions.items():
            if d["group"] == g["id"]:
                node = {"id": f"{g['id']}@{sha[:12]}", "commit": sha[:12],
                        "subject": history[sha]["subject"], "rows": d["rows"],
                        "parent": None, "parent_source": "git"}
                node_ids[sha] = node["id"]
                nodes.append(node)
        for r in g["rows"]:
            if r.get("commit") is None:
                nodes.append({"id": f"{g['id']}#{r['line']}", "commit": None, "subject": None,
                              "rows": [r], "parent": None, "parent_source": "order"})
                if history is not None and r["status"] != "pending":
                    notes.append(f"{g['csv']}:{r['line']} {r['task']} 跑完了却找不到带它名字的 commit,父按行序推断")
        nodes.sort(key=lambda n: n["rows"][0]["line"])
        nodes_of[g["id"]] = nodes

    memos = {False: {}, True: {}}
    for g in groups:
        node_by_row = {r["line"]: n for n in nodes_of[g["id"]] for r in n["rows"]}
        for node in nodes_of[g["id"]]:
            if node["commit"] is not None:
                sha = node["rows"][0]["commit"]
                p = parent_of(sha, g["id"], history, decisions, memos)
                node["parent"] = node_ids.get(p) if p else None
            else:
                line = node["rows"][0]["line"]
                keeps = [r for r in g["rows"] if r["line"] < line and r["status"] == "keep"]
                node["parent"] = node_by_row[keeps[-1]["line"]]["id"] if keeps else None
        for r in g["rows"]:
            r.pop("commit", None)

    scope_ids = {g["id"] for g in in_scope}
    external = {}
    for g in in_scope:
        for node in nodes_of[g["id"]]:
            pid = node["parent"]
            if pid and pid.split("@")[0].split("#")[0] not in scope_ids:
                src = next(n for og in groups for n in nodes_of[og["id"]] if n["id"] == pid)
                external[pid] = {"id": pid, "group": pid.split("@")[0].split("#")[0],
                                 "commit": src["commit"], "tasks": [r["task"] for r in src["rows"]]}

    return {
        "generated": datetime.now().isoformat(timespec="minutes"),
        "root": str(root), "records": records_name, "scope": scope,
        "git": history is not None,
        "section_summary": section_summaries(records),
        "groups": [{**{k: v for k, v in g.items() if k != "rows"}, "nodes": nodes_of[g["id"]]}
                   for g in in_scope],
        "external": list(external.values()),
        "notes": notes,
    }


def render(data, out):
    """把数据注进模板,写成单文件 HTML。[主线]

    Args:
        data: build 的结果。
        out: 输出路径(Path)。父目录不存在就建。
    """
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace(MARK, payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")


def main():
    """命令行入口:读记录 + git,写页面或打印 JSON。[主线]"""
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--root", default=".", help="项目根目录")
    ap.add_argument("--records", default="experiments", help="记录根目录,相对项目根")
    ap.add_argument("--scope", default="exploration", help="只画这个部分或组,相对记录根")
    ap.add_argument("--out", help="页面路径,相对项目根;默认 outputs/lineage/<scope>.html")
    ap.add_argument("--json", action="store_true", help="只打印数据,不写页面")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    data = build(root, args.records, args.scope.strip("/"))
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return
    out = root / (args.out or f"outputs/lineage/{data['scope'].replace('/', '-')}.html")
    render(data, out)
    total = sum(len(g["nodes"]) for g in data["groups"])
    print(f"已写 {out}:{len(data['groups'])} 组、{total} 个节点" + ("" if data["git"] else ";没有 git,边全按行序推断"))
    for note in data["notes"]:
        print("  -", note)


if __name__ == "__main__":
    main()
