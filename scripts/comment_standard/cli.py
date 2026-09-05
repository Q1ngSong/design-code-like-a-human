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
from dataclasses import asdict
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


def _sync(root):
    """建立或增量更新 codegraph 索引。[主线]

    索引不存在就先建。用户不该为了跑一次审计而记住 codegraph 的子命令 ——
    配置、建索引、同步都由这一个入口负责,这也是把 codegraph 包起来的理由。

    Args:
        root: 项目根路径。

    Returns:
        str,面向用户的一行状态。codegraph 未安装或命令失败都不抛异常 ——
        AST 类规则不依赖索引,不该因为索引出问题就整个罢工。
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


def audit(proj, do_sync=True):
    """跑完整流程,返回结构化结果。[主线]

    Args:
        proj: Project 实例。
        do_sync: 是否先调 codegraph sync。测试里关掉以免依赖外部命令。

    Returns:
        dict,含 project / sync / backfilled / index_present / findings /
        summary / total / exit_code / rules。两种输出格式都从它渲染,
        保证人看的和 agent 看的是同一份数据。
    """
    # 必须在 sync 之前:否则这次同步仍按旧的 codegraph.json 建索引,
    # 用户刚改的范围要等下一次刷新才生效。
    cg_msg = cgconfig.sync(proj)
    sync_msg = _sync(proj.root) if do_sync else None
    filled = backfill.run(proj)
    index_present = proj.db_path.exists()
    findings = (rules_ast.check_project(proj)
                + rules_write.check_project(proj)
                + rules_sql.check_project(proj)
                + rules_fs.check_project(proj)
                + rules_git.check_project(proj))
    findings.sort(key=lambda f: (f.rule, f.file, f.line))

    summary = {}
    for f in findings:
        summary[f.rule] = summary.get(f.rule, 0) + 1

    return {
        "project": str(proj.root),
        "git": _git_state(proj.root),
        "codegraph_config": cg_msg,
        "sync": sync_msg,
        "backfilled": filled,
        "index_present": index_present,
        "findings": [asdict(f) for f in findings],
        "summary": dict(sorted(summary.items())),
        "total": len(findings),
        "exit_code": 1 if findings else 0,
        "rules": RULE_TITLES,
    }


REPORT_DIR = ".codegraph"   # 与索引放一起:同为派生物,且建索引时已把它写进 .gitignore
REPORT_MD = "audit.md"
REPORT_JSON = "audit.json"


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
    idx = "有" if result["index_present"] else "无"
    git = result.get("git")
    where = f"  ·  分支 `{git['branch']}` @ `{git['head']}`" if git else ""
    lines = [
        f"# 审计报告 —— {name}",
        "",
        f"{when}{where}  ·  索引:{idx}  ·  回填 {result['backfilled']} 条  ·  "
        f"**{result['total']} 处不合规**"
        + ("（**结果不完整**）" if skipped else ""),
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
        lines.append("| — | 全部合规 | 0 |")
    lines.append("")

    by_rule = {}
    for f in result["findings"]:
        by_rule.setdefault(f["rule"], []).append(f)
    for rule in sorted(by_rule):
        lines += [
            f"## {rule}  {RULE_TITLES.get(rule, '')}",
            "",
            "| 位置 | 名称 | 说明 |",
            "|---|---|---|",
        ]
        for f in by_rule[rule]:
            lines.append(f"| {f['file']}:{f['line']} | `{f['name']}` | {f['message']} |")
        lines.append("")

    if not result["index_present"]:
        lines += ["---", "", "本次没有索引,图规则(R1/R2/R3/D1)已跳过。"
                  "建索引没成功,看开头 sync 那行的原因;解决后重跑。", ""]
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
    lines.append(f"回填 {result['backfilled']} 条 docstring")
    if not result["index_present"]:
        lines.append("未找到 codegraph 索引,已跳过 R1/R2/R3/D1。"
                     "建索引没成功,看上面 sync 那行的原因。")

    by_rule = {}
    for f in result["findings"]:
        by_rule.setdefault(f["rule"], []).append(f)
    for rule in sorted(by_rule):
        items = by_rule[rule]
        lines.append(f"\n{rule}  {RULE_TITLES.get(rule, '')}  ({len(items)})")
        for f in items:
            lines.append(f"  {f['file']}:{f['line']}  {f['name']}  {f['message']}")

    lines.append(f"\n{result['total']} 处不合规")
    if "reports" in result:
        lines.append(f"报告:{result['reports']['markdown']}")
        lines.append(f"      {result['reports']['json']}")
    return "\n".join(lines)


def main(argv=None):
    """命令入口。[主线]

    Args:
        argv: 参数列表,None 时取 sys.argv[1:]。
            位置参数是项目路径(默认当前目录);
            --no-sync 跳过 codegraph 同步;--json 输出结构化结果给 agent。

    Returns:
        int 退出码:0 全部合规,1 存在不合规,2 项目未启用或配置损坏。
    """
    ap = argparse.ArgumentParser(prog="comment-standard refresh")
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--no-sync", action="store_true", help="跳过 codegraph sync")
    ap.add_argument("--json", action="store_true", help="输出 JSON 给 agent 解析")
    args = ap.parse_args(argv)

    try:
        proj = project.load(Path(args.path))
    except (project.NotEnabled, project.BadConfig) as exc:
        if args.json:
            print(json.dumps({"error": str(exc), "exit_code": 2}, ensure_ascii=False))
        else:
            print(exc)
        return 2

    result = audit(proj, do_sync=not args.no_sync)
    write_reports(proj, result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_text(result))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
