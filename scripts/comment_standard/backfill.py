"""把写在函数体内的 docstring 回填进 codegraph 索引。

codegraph 的全部语言提取器统一读「前置注释」,而 Python 的文档惯例是把
docstring 放在函数体内,于是 nodes.docstring 恒为 NULL。

回填结果不是持久的:codegraph sync 会 deleteNodesByFile + INSERT OR REPLACE,
把整个文件的节点删除重建,连带清空本模块写入的内容;而且 node id 里含行号,
插一行就会让下方所有 id 失效,所以旁挂一张 sidecar 表也行不通。
唯一可行的做法是每次 sync 之后重跑 —— 好在全库也只要几十毫秒。

已知缺口(spec 五):只处理函数、方法与类,不处理模块级 docstring。
"""
import ast
import sqlite3

_DOCUMENTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def docstrings_for(path):
    """取出一个源文件里所有定义的体内 docstring。[主线]

    Args:
        path: .py 文件路径。

    Returns:
        dict,键是 def/class 所在行号(与 codegraph 的 start_line 对齐),
        值是去缩进并 strip 过的 docstring。文件语法错误或编码异常时返回空 dict ——
        原型代码经常处于半成品状态,不应因此中断整次回填。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return {}
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, _DOCUMENTED):
            doc = ast.get_docstring(node)
            if doc:
                out[node.lineno] = doc.strip()
    return out


def run(proj, only=None):
    """把体内 docstring 写回索引。[主线]

    Args:
        proj: Project 实例。
        only: 相对路径集合,限定只处理这些文件;None 表示全部在审计范围内的。
            sync 只动了少数文件时传它,可省去无谓的解析。

    Returns:
        int,实际写入的节点数。索引不存在时返回 0 而不报错 ——
        调用方(cli)负责在更靠前的位置给出「先建索引」的提示。
    """
    if not proj.db_path.exists():
        return 0
    con = sqlite3.connect(proj.db_path)
    try:
        rows = con.execute(
            "SELECT id, file_path, start_line FROM nodes"
            " WHERE kind IN ('function','method','class') AND file_path LIKE '%.py'"
        ).fetchall()

        by_file = {}
        for node_id, file_path, start_line in rows:
            if only is not None and file_path not in only:
                continue
            if not proj.in_scope(file_path):
                continue
            by_file.setdefault(file_path, []).append((node_id, start_line))

        updates = []
        for file_path, nodes in by_file.items():
            docs = docstrings_for(proj.root / file_path)
            for node_id, start_line in nodes:
                doc = docs.get(start_line)
                if doc:
                    updates.append((doc, node_id))

        con.executemany("UPDATE nodes SET docstring = ? WHERE id = ?", updates)
        con.commit()
        return len(updates)
    finally:
        con.close()
