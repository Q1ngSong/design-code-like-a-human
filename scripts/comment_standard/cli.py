"""刷新命令:codegraph 同步 → docstring 回填 → 规则校验。

三步必须绑在一起。sync 会删除重建变动文件的全部节点,清空上一次的回填结果;
只 sync 不回填,注释会静默消失。所以本仓库的技能文档中不出现裸的
`codegraph sync`(注释标准 spec 三章)。

两种输出并存:默认是给人看的分组文本;`--json` 是给 agent 的结构化文档,
stdout 只含一个 JSON 对象,连出错也是 —— agent 才能统一解析。
"""
import argparse
import datetime
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

from . import (backfill, cgconfig, project, rules_ast, rules_fs, rules_git,
               rules_sql, rules_write)

# 汇报时的规则说明,让读者不用翻 spec 就知道每条在说什么。
RULE_TITLES = {
    "R0": "缺 docstring 或角色标记",
    "R1": "零调用者 —— 大概率是死代码",
    "R2": "[一次性] 放错层 —— 应移到最外层",
    "R3": "主线调用旁支 —— 本次实验用得到它吗?",
    "R4": "参数未在 Args 中介绍",
    "R5": "有返回值但缺 Returns",
    "R6": "Args 里写了 def 那一行没有的参数 —— 改参数后没同步文档",
    "D1": "依赖方向违规 —— 内层引用外层,模块化崩坏",
    "C1": "改了已有函数却没留变更记录 —— 补一行「变更:」",
    "D2": "实验输出区未被 .gitignore 忽略 —— 结果文件会进版本库",
    "D3": "写盘点直接写死输出路径 —— 决策散在各处,结果就散在各处",
}


def _git_state(root):
    """读当前分支与 HEAD。[基础设施]

    codegraph 的 project_metadata 里不含任何 git 状态 —— 索引不知道自己
    是从哪个分支建的。走 refresh 时 sync 会自愈,但 agent 直接调 MCP 的
    codegraph_search / codegraph_explore 时不会,读到上个分支的代码却毫无提示。
    把分支记进报告,至少让「什么时候建的索引」有据可查。

    Args:
        root: 项目根路径。

    Returns:
        dict {"branch", "head"};不是 git 仓库或 git 不可用时返回 None。
    """
    if shutil.which("git") is None:
        return None
    try:
        run = lambda a: subprocess.run(
            ["git", "-C", str(root), *a],
            capture_output=True, text=True, timeout=10,
        )
        branch = run(["rev-parse", "--abbrev-ref", "HEAD"])
        head = run(["rev-parse", "--short", "HEAD"])
    except (subprocess.TimeoutExpired, OSError):
        return None
    if branch.returncode != 0 or head.returncode != 0:
        return None
    return {"branch": branch.stdout.strip(), "head": head.stdout.strip()}


def _unattended(root):
    """读无人值守哨兵。[主线]

    Args:
        root: 项目根路径。

    Returns:
        (bool, str|None):是否无人值守、开始时间(ISO,到分钟)。哨兵是
        `.codegraph/unattended`,**存在且 mtime 在 24 小时内**即为真。文件内容
        不参与判断(里面是分支名,给人看的)。24 小时照 ARIS 的 state file 规矩:
        忘了删的哨兵不该在一周后还生效。
    """
    f = Path(root) / ".codegraph" / "unattended"
    if not f.exists():
        return False, None
    since = datetime.datetime.fromtimestamp(f.stat().st_mtime)
    fresh = (datetime.datetime.now() - since) < datetime.timedelta(hours=24)
    return fresh, since.isoformat(timespec="minutes")


def _sync(root):
    """建立或增量更新 codegraph 索引。[主线]

    索引不存在就先建。用户不该为了跑一次审计而记住 codegraph 的子命令 ——
    配置、建索引、同步都由这一个入口负责,这也是把 codegraph 包起来的理由。

    Args:
        root: 项目根路径。

    Returns:
        str,面向用户的一行状态。codegraph 未安装或命令失败都不抛异常 ——
        AST 类规则不依赖索引(审计范围由配置决定,索引落后不影响它们),
        不该因为索引出问题就整个罢工。
    """
    if shutil.which("codegraph") is None:
        return "codegraph 未安装,跳过索引(npm i -g @colbymchenry/codegraph)"

    first_time = not (Path(root) / ".codegraph" / "codegraph.db").exists()
    argv = ["codegraph", "init", "-y", str(root)] if first_time \
        else ["codegraph", "sync", str(root)]
    what = "建索引" if first_time else "同步索引"

    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return f"codegraph {what}超时,继续用现有索引校验"
    if proc.returncode != 0:
        return f"codegraph {what}失败(退出码 {proc.returncode}),继续用现有索引校验"
    return f"codegraph {what}完成"


def _mark_changed(findings, changes, files, proj):
    """给落在改动上的 finding 打 changed 标。[主线]

    两级判定:

    1. 落在改了签名、体或 docstring 的函数范围内。按行号归属,不按名字:AST 规则的 finding
       带裸名,changed_functions 的键是限定名,对不上;而行号对所有规则通用 ——
       R0/R4/R5/R6/C1 的 line 是 def 行,D3 的是调用行,R1/R2/R3 的是 codegraph 的
       start_line,D1 的是边所在行,都落在函数的 [line, end_line] 内。
    2. 不在任何改动函数里、但文件改了、且不在任何函数里 —— 模块级语句
       (顶层的 torch.save、模块级 import)。这一级靠「文件改了」兜底,会把改动
       文件里原有的模块级告警也标上;宁可多看一条,不能让新文件里写死的路径
       被当成存量、退出码给 0。

    抓不到的是图效应:删了一处调用点,让别的文件里没动过的函数新报 R1 ——
    那个 finding 既不在改动函数里也不在改动文件里。合并前以 --base 指定实际接收分支，
    同时查看存量 R1 是为这个。D2 是文件级的,不会被标。

    Args:
        findings: 全量 finding 列表。
        changes: changed_functions 的结果。
        files: changed_files 的结果(含未跟踪的新文件)。
        proj: Project,读改动文件算函数范围用。

    Returns:
        新列表,命中的元素是 replace(changed=True) 后的副本。
    """
    spans_cache = {}
    out = []
    for f in findings:
        spans = changes.get(f.file, {})
        if any(c.new.line <= f.line <= c.new.end_line for c in spans.values()):
            out.append(replace(f, changed=True))
            continue
        if f.file in files:
            if f.file not in spans_cache:
                try:
                    src = (proj.root / f.file).read_text(encoding="utf-8")
                except OSError:
                    src = ""
                spans_cache[f.file] = [
                    (fn.line, fn.end_line) for fn in rules_git.functions_of(src).values()
                ]
            if not any(a <= f.line <= b for a, b in spans_cache[f.file]):
                out.append(replace(f, changed=True))
                continue
        out.append(f)
    return out


def audit(proj, do_sync=True, base=None):
    """跑完整流程,返回结构化结果。[主线]

    Args:
        proj: Project 实例。
        do_sync: 是否先调 codegraph sync。测试里关掉以免依赖外部命令。
        base: 差异审阅的 git ref。None 是全仓库审阅,C1 比工作区 vs HEAD。给了就
            两件事:C1 的比较基线换成它(报的是「相对 ref 改了没记」),以及在
            全量结果上把落在改动上的 finding 标出来 —— 审计不过滤,0 token 没理由省,
            标记只是给注意力指方向。

    Returns:
        dict,含 project / sync / backfilled / index_present / unindexed_files /
        base / changed_functions / findings / summary / total / exit_code / rules。
        两种输出格式都从它渲染,保证人看的和 agent 看的是同一份数据。
    """
    # 必须在 sync 之前:否则这次同步仍按旧的 codegraph.json 建索引,
    # 用户刚改的范围要等下一次刷新才生效。
    cg_msg = cgconfig.sync(proj)
    sync_msg = _sync(proj.root) if do_sync else None
    filled = backfill.run(proj)
    index_present = proj.db_path.exists()
    # sync 没成功但索引还在:图规则跑的是上一次的索引,内容可能已经过时。
    # 不逐文件比哈希,只把这个事实报出来 —— 便宜,而且够用。
    index_stale = bool(sync_msg) and index_present and not sync_msg.endswith("完成")
    # 索引只是辅助文件,不决定审计范围;但它落后于磁盘时图规则会漏掉新文件,
    # 这里把差集算出来点名 —— 让「索引过时」从悄无声息变成报告第一屏可见。
    unindexed = []
    if index_present:
        indexed = proj.indexed_files() or set()
        unindexed = [f for f in proj.py_files_in_scope() if f not in indexed]

    # 改动集合只算一次:C1 用它判「改了没记」,打标用它判「落没落在改动上」。
    changes = rules_git.changed_functions(proj, base or "HEAD")

    findings = (rules_ast.check_project(proj)
                + rules_write.check_project(proj)
                + rules_sql.check_project(proj)
                + rules_fs.check_project(proj)
                + rules_git.check_project(proj, changes=changes))
    if base:
        findings = _mark_changed(findings, changes, rules_git.changed_files(proj, base), proj)
    findings.sort(key=lambda f: (f.rule, f.file, f.line))

    summary = {}
    for f in findings:
        summary[f.rule] = summary.get(f.rule, 0) + 1

    unattended, unattended_since = _unattended(proj.root)
    return {
        "project": str(proj.root),
        "git": _git_state(proj.root),
        "unattended": unattended,
        "unattended_since": unattended_since,
        "codegraph_config": cg_msg,
        "sync": sync_msg,
        "backfilled": filled,
        "index_present": index_present,
        "index_stale": index_stale,
        "unindexed_files": unindexed,
        "base": base,
        "changed_functions": (
            {rel: sorted(fns) for rel, fns in changes.items()} if base else {}
        ),
        "findings": [asdict(f) for f in findings],
        "summary": dict(sorted(summary.items())),
        "total": len(findings),
        # 带 --base 时退出码只看本轮:存量告警每轮都在,拿它当"这轮有没有问题"永远是 1。
        "exit_code": 1 if (any(f.changed for f in findings) if base else findings) else 0,
        "rules": RULE_TITLES,
    }

REPORT_DIR = ".codegraph"   # 与索引放一起:同为派生物,且建索引时已把它写进 .gitignore
REPORT_MD = "audit.md"
REPORT_JSON = "audit.json"


def _rule_tables(findings, level):
    """按规则分组渲染成 Markdown 表。[基础设施]

    Args:
        findings: finding 字典列表。
        level: 规则标题的 `#` 个数。全仓库审阅是 2;差异审阅里规则在
            「本次改动」/「存量」之下,是 3。

    Returns:
        list[str],Markdown 行。
    """
    lines = []
    by_rule = {}
    for f in findings:
        by_rule.setdefault(f["rule"], []).append(f)
    for rule in sorted(by_rule):
        lines += [
            f"{'#' * level} {rule}  {RULE_TITLES.get(rule, '')}",
            "",
            "| 位置 | 名称 | 说明 |",
            "|---|---|---|",
        ]
        for f in by_rule[rule]:
            lines.append(f"| {f['file']}:{f['line']} | `{f['name']}` | {f['message']} |")
        lines.append("")
    return lines


def render_markdown(result):
    """把审计结果渲染成给人看的 Markdown 报告。[主线]

    比终端文本多的东西:时间戳、概览表、每条规则一张定位表。
    这是要留在项目里反复打开的文档,不是一闪而过的终端输出。

    Args:
        result: audit() 的返回值。

    Returns:
        str,完整的 Markdown 文档。
    """
    name = Path(result["project"]).name
    when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    skipped = [] if result["index_present"] else ["R1", "R2", "R3", "D1"]
    unindexed = result.get("unindexed_files") or []
    stale = bool(result.get("index_stale"))  # 同步失败:图规则跑了,但查的是旧图
    idx = "有" if result["index_present"] else "无"
    if unindexed:
        idx = f"有,但落后 {len(unindexed)} 个文件"
    if result.get("index_stale"):
        idx = "有,但本次同步失败,内容可能过时"
    git = result.get("git")
    where = f"  ·  分支 `{git['branch']}` @ `{git['head']}`" if git else ""
    base = result.get("base")
    n_changed = sum(len(v) for v in (result.get("changed_functions") or {}).values())
    diff = f"  ·  差异 vs `{base}`,{n_changed} 个函数改动" if base else ""
    lines = [
        f"# 审计报告 —— {name}",
        "",
        f"{when}{where}{diff}  ·  索引:{idx}  ·  回填 {result['backfilled']} 条  ·  "
        f"**{result['total']} 处不合规**"
        + ("（**结果不完整**）" if (skipped or unindexed or stale) else ""),
        "",
    ]
    if skipped:
        lines += [
            f"> **结果不完整。** 本次没有索引，{'、'.join(skipped)} 未执行，",
            "> 下面只有注释规则的结果。条数比完整审计少是因为规则没跑，",
            "> 不代表这些问题已经解决。",
            "",
        ]
    if result["sync"]:
        lines += [f"> {result['sync']}", ""]

    lines += ["## 概览", "", "| 规则 | 说明 | 条数 |", "|---|---|---:|"]
    for rule, n in result["summary"].items():
        lines.append(f"| {rule} | {RULE_TITLES.get(rule, '')} | {n} |")
    for rule in skipped:
        lines.append(f"| {rule} | {RULE_TITLES.get(rule, '')} | **未执行** |")
    if not result["summary"]:
        # 有规则没跑就不能说「全部合规」—— 那只是已跑的那几条没发现。
        lines.append("| — | 已执行的规则无发现 | 0 |" if (skipped or unindexed or stale) else "| — | 全部合规 | 0 |")
    lines.append("")

    if base:
        changed = [f for f in result["findings"] if f["changed"]]
        existing = [f for f in result["findings"] if not f["changed"]]
        lines += [f"## 本次改动（{len(changed)}）", "",
                  "落在改动上的:改了签名、体或 docstring 的函数、新文件、改动文件里的模块级语句。先看这些。", ""]
        lines += _rule_tables(changed, 3) if changed else ["（无）", ""]
        lines += [f"## 存量（{len(existing)}）", "",
                  "其余的:没动过的代码,以及图效应——删了调用点让别处的函数新报 R1,"
                  "那种落不到改动上。审计不省略它们。", ""]
        lines += _rule_tables(existing, 3) if existing else ["（无）", ""]
    else:
        lines += _rule_tables(result["findings"], 2)

    if not result["index_present"]:
        lines += ["---", "", "本次没有索引,图规则(R1/R2/R3/D1)已跳过。"
                  "建索引没成功,看开头 sync 那行的原因;解决后重跑。", ""]
    elif unindexed:
        lines += ["---", "",
                  f"**索引落后于磁盘。** 下面 {len(unindexed)} 个文件在审计范围内但不在索引里,"
                  "注释规则(R0/R4/R5/R6/D3/C1)已查过它们,图规则(R1/R2/R3/D1)没有:",
                  ""]
        lines += [f"- `{f}`" for f in unindexed]
        lines += ["", "看开头 sync 那行是不是失败了,或者是不是带了 --no-sync。解决后重跑。", ""]
    return "\n".join(lines)


def write_reports(proj, result):
    """把两份报告写进项目的 .codegraph/。[主线]

    无条件覆盖。报告反映的是本次运行,不与上一次比较 —— 留旧数据会让人
    对着一份已经修好的清单去查。运行不完整时由 render_markdown 在报告
    最显眼处标明,而不是靠保留旧文件来补救。

    Args:
        proj: Project 实例。
        result: audit() 的返回值,会被原地加上 reports 字段。

    Returns:
        dict,{"markdown": 路径, "json": 路径}。
    """
    out_dir = proj.root / REPORT_DIR
    out_dir.mkdir(exist_ok=True)
    md_path = out_dir / REPORT_MD
    js_path = out_dir / REPORT_JSON
    result["reports"] = {"markdown": str(md_path), "json": str(js_path)}
    md_path.write_text(render_markdown(result), encoding="utf-8")
    js_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result["reports"]


def render_text(result):
    """把审计结果渲染成给人看的分组文本。[主线]

    Args:
        result: audit() 的返回值。

    Returns:
        str,多行。
    """
    lines = []
    if result.get("codegraph_config"):
        lines.append(result["codegraph_config"])
    if result["sync"]:
        lines.append(result["sync"])
    if result.get("index_stale"):
        lines.append("索引可能过时:本次同步失败,R1/R2/R3/D1 跑的是上一次的索引")
    lines.append(f"回填 {result['backfilled']} 条 docstring")
    unindexed = result.get("unindexed_files") or []
    if unindexed:
        lines.append(f"索引落后于磁盘:{len(unindexed)} 个文件不在索引里,图规则没查到它们 —— "
                     + ", ".join(unindexed[:5]) + (" …" if len(unindexed) > 5 else ""))
    if not result["index_present"]:
        lines.append("未找到 codegraph 索引,已跳过 R1/R2/R3/D1。"
                     "建索引没成功,看上面 sync 那行的原因。")

    def _group(items):
        by_rule = {}
        for f in items:
            by_rule.setdefault(f["rule"], []).append(f)
        for rule in sorted(by_rule):
            lines.append(f"\n{rule}  {RULE_TITLES.get(rule, '')}  ({len(by_rule[rule])})")
            for f in by_rule[rule]:
                lines.append(f"  {f['file']}:{f['line']}  {f['name']}  {f['message']}")

    if result.get("base"):
        changed = [f for f in result["findings"] if f["changed"]]
        existing = [f for f in result["findings"] if not f["changed"]]
        lines.append(f"\n===== 本次改动(vs {result['base']}):{len(changed)} =====")
        _group(changed)
        lines.append(f"\n===== 存量:{len(existing)} =====")
        _group(existing)
    else:
        _group(result["findings"])

    lines.append(f"\n{result['total']} 处不合规")
    if "reports" in result:
        lines.append(f"报告:{result['reports']['markdown']}")
        lines.append(f"      {result['reports']['json']}")
    return "\n".join(lines)


def main(argv=None):
    """命令入口。[主线]

    变更: 2026-09-07 --base 帮助改为实际接收分支，保留原有参数和审计行为。

    Args:
        argv: 参数列表,None 时取 sys.argv[1:]。
            位置参数是项目路径(默认当前目录);
            --no-sync 跳过 codegraph 同步;--json 输出结构化结果给 agent;
            --base REF 差异审阅,标出相对 REF 改过的函数上的告警;省略则全仓库审阅。

    Returns:
        int 退出码:0 已执行的检查没有 finding(带 --base 时:没有 changed=true 的),
        1 存在不合规,2 项目未启用、配置损坏或 --base 的 ref 不存在。
    """
    ap = argparse.ArgumentParser(prog="comment-standard refresh")
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--no-sync", action="store_true", help="跳过 codegraph sync")
    ap.add_argument("--json", action="store_true", help="输出 JSON 给 agent 解析")
    ap.add_argument("--base", metavar="REF",
                    help="差异审阅:标出相对这个 git ref 改过的函数上的告警。"
                         "快速迭代跑前用 HEAD(圈出工作区里这次的改动),合并前用实际接收分支（main、master或者上一级分支等）。"
                         "省略则全仓库审阅")
    args = ap.parse_args(argv)

    try:
        proj = project.load(Path(args.path))
    except (project.NotEnabled, project.BadConfig) as exc:
        if args.json:
            print(json.dumps({"error": str(exc), "exit_code": 2}, ensure_ascii=False))
        else:
            print(exc)
        return 2

    if args.base and not rules_git.ref_exists(proj.root, args.base):
        msg = f"--base {args.base!r} 不是这个仓库里的有效 ref(不是 git 仓库,或分支/提交不存在)"
        if args.json:
            print(json.dumps({"error": msg, "exit_code": 2}, ensure_ascii=False))
        else:
            print(msg)
        return 2

    result = audit(proj, do_sync=not args.no_sync, base=args.base)
    write_reports(proj, result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_text(result))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
