"""基于 codegraph 索引的规则:R1 零调用者、R2 一次性放错层、R3 主线调用旁支、D1 依赖方向。

这四条只查 nodes / edges,不解析源码,因此与语言无关 —— 将来扩展到 Go、
TypeScript 时无需改动。需要比对签名与文档的 R0/R4/R5/R6 在 rules_ast.py。

R2 以 `layers` 声明为前提,D1 以 `layers` 或 `vendored` 为前提。
未声明时静默跳过 —— 我们只校验用户自己声明过的东西,不校验我们的偏好
(目录规范 spec 第〇节)。

第三方代码(vendored)不跑 R1/R2/R3:官方库里大量函数我们本来就不用,
R1 报它们全是噪声;R2/R3 依赖角色标记,它没有。但它参与 D1 ——
官方代码被改成依赖我们的代码,是必须抓的。

R3 是角色标记的核心价值:「静态可达但不在主线上」原本必须人读实验计划才能
判定,有了标记后降级为一次连接查询。

D1 是痛点 1(代码不够模块化)第一个可机械判定的形态:内层引用外层意味着
核心功能再也没法脱离脚本单独复用。
"""
import sqlite3

from . import parser
from .rules_ast import Finding


def _dirs(group):
    """把一层的目录元组渲染成 `a/ 或 b/`。[基础设施]

    Args:
        group: 一层的目录名元组。

    Returns:
        str,单目录层就是 `a/`。
    """
    return " 或 ".join(f"{d}/" for d in group)

# LIKE 中的 `_` 是单字符通配符,过滤 dunder 必须转义。
# 写成 NOT LIKE '__%' 会滤掉每一个函数,让 R1 静默返回空。
# 角色标记的判定统一交给 parser.role_of，SQL 只负责把 docstring 取回来。
# 判定规则不止「含有某个标记」那么简单：标记必须是摘要行末尾唯一的那个，
# 否则「摘要里引用了标记」和「标了两个互相矛盾的标记」都会被误判——
# 后者尤其危险，`[主线][一次性]` 会让一段死代码骗过 R1 的豁免。
# 用 SQL 表达这套规则既难读又容易和 Python 那边走偏，所以只留一份实现。

_NOT_DUNDER = r"n.name NOT LIKE '\_\_%' ESCAPE '\'"

_DEP_KINDS = "('calls','imports','references','instantiates')"

# [一次性] 按定义就没有调用者,R1 不再重复报告 —— 标记本身已经说了。
# 连调用方的文件路径一起取出,交给 Python 侧按范围过滤。
#
# `e.source <> n.id` 排除自指边:自己调自己不算有人用,
# 否则递归写法的死代码永远抓不到(实测复现)。
#
# 不能只写 NOT EXISTS —— 那样任何一条入边都算「有人调」,包括输出区里
# 一次性脚本的调用。实测:runs/exp1/scratch_run.py 引用 ovam.m.really_dead,
# R1 就放过了这个真死代码,反而去报真正的对外接口。输出区本该被 gitignore
# 从而不进索引,但那正是 D2 要治的病 —— D2 未修复时 R1 不该跟着被削弱。
_R1 = f"""
SELECT n.id, n.name, n.file_path, n.start_line, n.docstring, s.file_path AS caller_file
FROM nodes n
LEFT JOIN edges e ON e.target = n.id AND e.kind IN {_DEP_KINDS}
                 AND e.source <> n.id
LEFT JOIN nodes s ON s.id = e.source
WHERE n.kind IN ('function','method')
  AND {_NOT_DUNDER}
ORDER BY n.file_path, n.start_line
"""

_R2 = """
SELECT name, file_path, start_line, docstring
FROM nodes
WHERE docstring IS NOT NULL
ORDER BY file_path, start_line
"""

_R3 = """
SELECT s.name, t.name, s.file_path, e.line, s.docstring, t.docstring, t.file_path
FROM edges e
JOIN nodes s ON s.id = e.source
JOIN nodes t ON t.id = e.target
WHERE e.kind = 'calls'
  AND s.docstring IS NOT NULL AND t.docstring IS NOT NULL
ORDER BY s.file_path, e.line
"""

_D1 = f"""
SELECT DISTINCT s.file_path, t.file_path, e.kind, e.line
FROM edges e
JOIN nodes s ON s.id = e.source
JOIN nodes t ON t.id = e.target
WHERE s.file_path <> t.file_path
  AND e.kind IN {_DEP_KINDS}
ORDER BY s.file_path, e.line, t.file_path
"""


def check_project(proj):
    """在 codegraph 索引上跑 R1 / R2 / R3 / D1。[主线]

    Args:
        proj: Project 实例。

    Returns:
        list[Finding]。索引文件不存在时返回空列表 —— 未建索引不是不合规,
        提示建索引是 cli 的职责。所有规则都只看审计范围内的节点。
    """
    if not proj.db_path.exists():
        return []
    con = sqlite3.connect(proj.db_path)
    try:
        out = []

        def ours(file_path):
            """是不是我们自己写的、且在审计范围内的文件。[基础设施]

            Args:
                file_path: 相对项目根的路径。

            Returns:
                bool。第三方代码不按我们的标准审。
            """
            return proj.in_scope(file_path) and not proj.is_vendored(file_path)

        # ── 两个判据的分工,不要「顺手统一」──────────────────────────
        #
        # in_scope(f)  这个文件在审计范围内吗(索引说了算)
        # ours(f)      = in_scope 且非第三方,即「该按我们的标准审」
        #
        # 用哪个取决于问的是什么:
        #
        # | 位置              | 判据       | 为什么                              |
        # |-------------------|-----------|-------------------------------------|
        # | R1 报谁           | ours      | 第三方没人调是常态,不该报它         |
        # | R1 谁的调用算数   | in_scope  | 第三方引用了我们的函数,那就不是死代码 |
        # | R2 报谁           | ours      | 第三方没有我们的角色标记            |
        # | R3 两端           | ours      | 不审第三方的角色标记,两端都要是我们的 |
        # | D1 两端           | in_scope  | 要抓「第三方反向依赖我们」,必须纳入   |
        #
        # 曾经踩过的:R1 拿 ours 判断调用方,把 sd15/ 的正常引用一并否定,
        # 被引用的函数被误报成死代码。R3 只过滤调用方,于是「主线调用了
        # 第三方里带 [旁支] 的函数」也会被报 —— 那个标记还不是我们写的。

        # 按节点归并入边:只有来自审计范围内的调用方才算数。
        # 输出区里的一次性脚本不算 —— 否则真死代码会静默逃过 R1(实测复现)。
        #
        # 判据用 in_scope 而不是 ours():第三方代码(vendored)引用了我们的
        # 函数,那个函数就不是死代码。ours() 的语义是「该按我们标准审的文件」,
        # 拿它判断「谁的调用算数」会把 sd15/ 的正常引用一并否定掉。
        # 按 node id 归并 —— schema 只保证 id 唯一,(名字, 文件, 行号)
        # 三元组的唯一性没人担保。
        callers = {}
        for nid, name, file_path, line, doc, caller_file in con.execute(_R1):
            entry = callers.setdefault(nid, [name, file_path, line, doc, False])
            if caller_file is not None and proj.in_scope(caller_file):
                entry[4] = True
        for name, file_path, line, doc, has_caller in callers.values():
            # 一次性代码按定义没有调用者,豁免。两条判据:
            #
            #   标了 [一次性]     —— 作者明说了它是一次性的
            #   位于最外层        —— 那一层装的就是一次性脚本
            #
            # 位置这条不能省:最外层最容易漏写 docstring,而漏写已经被 R0 报了,
            # 再叠一条「零调用者」是同一个毛病报两遍 —— 补上标记后 R1 那条
            # 自己就消失,说明它从来不是独立的问题。
            if parser.role_of(doc or "") == "一次性" or proj.is_outermost(file_path):
                continue
            if not has_caller and ours(file_path):
                out.append(Finding("R1", file_path, line, name, "零调用者"))

        if proj.layers:
            for name, file_path, line, doc in con.execute(_R2):
                if parser.role_of(doc or "") != "一次性":
                    continue
                if not ours(file_path) or proj.layer_of(file_path) is None:
                    continue
                if not proj.is_outermost(file_path):
                    out.append(Finding(
                        "R2", file_path, line, name,
                        (f"标记为 [一次性] 却在唯一的一层 {_dirs(proj.layers[0])} 里 —— "
                         f"单层就是核心,一次性代码该移出去,或再声明一个外层来放它")
                        if len(proj.layers) < 2 else
                        f"标记为 [一次性] 却不在最外层 {_dirs(proj.layers[-1])}",
                    ))

        # 两端都要在范围内:目标不归我们管的话,报出来用户也无从处置。
        for src, tgt, file_path, line, s_doc, t_doc, tgt_file in con.execute(_R3):
            if parser.role_of(s_doc or "") != "主线":
                continue
            if parser.role_of(t_doc or "") != "旁支":
                continue
            if ours(file_path) and ours(tgt_file):
                out.append(Finding(
                    "R3", file_path, line or 0, src,
                    f"主线 {src} 调用旁支 {tgt}",
                ))

        if proj.layers or proj.vendored:
            for src_file, tgt_file, kind, line in con.execute(_D1):
                if not (proj.in_scope(src_file) and proj.in_scope(tgt_file)):
                    continue
                if proj.may_depend(src_file, tgt_file):
                    continue
                if proj.is_vendored(src_file):
                    msg = (f"第三方代码 --{kind}--> {tgt_file},"
                           f"官方代码被改成依赖我们的代码,以后没法跟上游同步")
                else:
                    msg = (f"[{proj.layer_of(src_file)}] --{kind}--> "
                           f"[{proj.layer_of(tgt_file)}] {tgt_file},内层引用外层")
                out.append(Finding("D1", src_file, line or 0, kind, msg))

        return out
    finally:
        con.close()
