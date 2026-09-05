"""基于 git 的规则:C1 改了已有函数却没留变更记录。

注释标准的「变更锚点」判据是「这次改动前该函数是否已经存在」。
我们一度认为它无法机械校验 —— 那是判断错了,`git diff` 正好能回答。

做法:取工作区当前源码与基线提交的源码,各自解析成 AST,按限定名配对,
**剥掉 docstring 之后比 AST 指纹**。这样:

- 只改注释措辞、只改格式、只加 `#` 注释 —— 指纹不变,不报
- 逻辑真的动了 —— 指纹变化,若 docstring 里没新增「变更:」行则违规

比 AST 而非比文本,是为了不误报;剥 docstring 是为了让「补写注释」这个动作
本身不被算成改动。
"""
import ast
import subprocess
from dataclasses import dataclass

from . import parser
from .rules_ast import Finding


@dataclass(frozen=True)
class _Fn:
    """一个函数在某个版本里的样子。[基础设施]"""

    fingerprint: str
    anchors: int
    line: int


def _strip_docstring(body):
    """去掉函数体开头的 docstring 语句。[基础设施]

    Args:
        body: ast 语句列表。

    Returns:
        新的语句列表。补写注释这个动作本身不该被算成逻辑改动。
    """
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        return body[1:]
    return body


def functions_of(source):
    """把源码解析成 {限定名: _Fn}。[主线]

    Args:
        source: Python 源码文本。

    Returns:
        dict。限定名形如 `f` 或 `A.run` —— 不同类里的同名方法必须区分开,
        否则改了 B.run 会被记到 A.run 头上。语法错误返回空 dict。
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return {}

    out = {}

    def walk(node, prefix):
        """递归收集定义，用限定名区分不同类里的同名方法。[基础设施]

        Args:
            node: 当前作用域节点。
            prefix: 已累积的限定名前缀，如 `A.`。
        """
        for child in node.body:
            if isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                body = _strip_docstring(child.body)
                out[name] = _Fn(
                    fingerprint=ast.dump(ast.Module(body=body, type_ignores=[])),
                    anchors=(ast.get_docstring(child) or "").count("变更:"),
                    line=child.lineno,
                )
                walk(child, f"{name}.")

    walk(tree, "")
    return out


def _git(root, *args):
    """跑一条 git 命令。[基础设施]

    Args:
        root: 仓库内的任意路径。
        *args: git 子命令与参数。

    Returns:
        stdout 文本;命令失败返回 None(不是空串 —— 要区分「文件是新增的」
        和「文件存在但内容为空」)。
    """
    proc = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
    )
    return proc.stdout if proc.returncode == 0 else None


def check_project(proj):
    """找出改了函数体却没留变更记录的函数。[主线]

    Args:
        proj: Project 实例。

    Returns:
        list[Finding]。比的是工作区与 HEAD,也就是尚未提交的改动。
        不是 git 仓库时返回空列表 —— 没有历史不等于不合规。
        审计范围外的文件跳过。
    """
    # git 返回的路径相对仓库根,而项目根可能是仓库的子目录(monorepo)。
    # --relative 让 diff 列表相对 cwd;git show 仍需仓库根相对路径,
    # 所以两边都要用 prefix 换算。
    prefix = _git(proj.root, "rev-parse", "--show-prefix")
    if prefix is None:
        return []
    prefix = prefix.strip()

    changed = _git(proj.root, "diff", "--name-only", "--relative", "HEAD", "--", "*.py")
    if changed is None:
        return []

    out = []
    for rel in sorted(filter(None, changed.splitlines())):
        if not proj.in_scope(rel):
            continue
        old_src = _git(proj.root, "show", f"HEAD:{prefix}{rel}")
        if old_src is None:
            continue  # 新增文件,整体是新增
        path = proj.root / rel
        if not path.is_file():
            continue  # 已删除
        old = functions_of(old_src)
        new = functions_of(path.read_text(encoding="utf-8"))
        for name, fn in new.items():
            prev = old.get(name)
            if prev is None:
                continue  # 新增函数,git 已经记录
            if parser.is_dunder(name.rpartition(".")[2]):
                continue
            if fn.fingerprint == prev.fingerprint:
                continue
            if fn.anchors > prev.anchors:
                continue
            out.append(Finding(
                "C1", rel, fn.line, name,
                "函数体已改但 docstring 里没加「变更:」行",
            ))
    return out
