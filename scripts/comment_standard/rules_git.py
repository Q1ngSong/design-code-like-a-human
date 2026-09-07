"""基于 git 的规则:C1 改了已有函数却没留变更记录。

注释标准的「变更锚点」判据是「这次改动前该函数是否已经存在」。
我们一度认为它无法机械校验 —— 那是判断错了,`git diff` 正好能回答。

做法:取工作区当前源码与基线提交的源码,各自解析成 AST,按限定名配对,
**递归剥掉所有 docstring(含嵌套定义的)之后比 AST 指纹**。这样:

- 只改注释措辞、只改格式、只加 `#` 注释 —— 指纹不变,不报
- 逻辑真的动了 —— 指纹变化,若 docstring 里没新增「变更:」行则违规

changed_functions 是 C1 和差异审阅打标的共同依赖,它把只改了 docstring 的函数
也算进改动集合 —— 打标需要(删一行 Args 新报的 R4 得算这次的);C1 自己再按指纹过滤。

比 AST 而非比文本,是为了不误报;剥 docstring 是为了让「补写注释」这个动作
本身不被算成改动。
"""
import ast
import copy
import subprocess
from dataclasses import dataclass

from . import parser
from .rules_ast import Finding


@dataclass(frozen=True)
class _Fn:
    """一个函数在某个版本里的样子。[基础设施]"""

    fingerprint: str
    anchors: int
    doc: str        # 原样 docstring;指纹剥掉了它,打标要靠这个看出只改注释的函数
    line: int
    end_line: int   # 含。行号归属用:finding.line 落在 [line, end_line] 内就算这个函数的


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


def _strip_all_docstrings(body):
    """递归去掉函数体里所有定义开头的 docstring,包括嵌套的。[基础设施]

    Args:
        body: ast 语句列表。会被深拷贝,原树不动 —— 调用方之后还要用原节点
            算 anchors 并递归登记嵌套定义。

    Returns:
        新的语句列表。只剥外层的话,嵌套函数的 docstring 会留在外层的指纹里,
        改一句嵌套注释就让外层被判「函数体变了」。注释不是代码,不论在哪一层。
    """
    body = _strip_docstring(copy.deepcopy(body))
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                node.body = _strip_docstring(node.body)
    return body


_SCOPE_OPENERS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _scope_statements(node):
    """按源码顺序产出一个作用域里的全部语句,展开控制流块。[基础设施]

    `if` / `try` / `with` / `for` / `while` / `match` 的各个块都会被进入,
    因为条件导入、平台分支、`try: import torch` 里定义的函数和顶层的一样是
    这个作用域的成员。嵌套的函数和类**不**进入 —— 它们是新作用域,
    由 walk 用新的限定名前缀递归处理。

    Args:
        node: 带 `body` 的作用域节点(模块、函数、类)。

    Returns:
        生成器,逐个产出语句节点。
    """
    stack = list(reversed(node.body))
    while stack:
        stmt = stack.pop()
        yield stmt
        if isinstance(stmt, _SCOPE_OPENERS):
            continue
        blocks = []
        for field in ("body", "orelse", "finalbody"):
            blocks.extend(getattr(stmt, field, None) or ())
        for h in getattr(stmt, "handlers", None) or ():
            blocks.extend(h.body)
        for c in getattr(stmt, "cases", None) or ():
            blocks.extend(c.body)
        stack.extend(reversed(blocks))


def _fingerprint(node, body):
    """算一个函数的指纹:签名 + 装饰器 + 返回注解 + 去掉 docstring 的函数体。[基础设施]

    只算函数体的话,加参数、改默认值、加装饰器一律不报 —— 而这些恰恰是
    调用方能感知的契约改动,C1 该报。

    Args:
        node: ast.FunctionDef 或 ast.AsyncFunctionDef。
        body: 已剥 docstring 的语句列表。

    Returns:
        str。
    """
    parts = [type(node).__name__, ast.dump(node.args)]  # def ↔ async def 也是契约改动
    parts += [ast.dump(d) for d in node.decorator_list]
    parts.append(ast.dump(node.returns) if node.returns is not None else "")
    parts.append(ast.dump(ast.Module(body=body, type_ignores=[])))
    return "|".join(parts)


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
        for child in _scope_statements(node):
            if isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                # 同一作用域里同名的定义(if/else 两支、try/except 两支)各自保留,
                # 第二个起加 #1、#2 序号;否则后者覆盖前者,前者的改动永远比不到。
                key, n = name, 0
                while key in out:
                    n += 1
                    key = f"{name}#{n}"
                body = _strip_all_docstrings(child.body)
                doc = ast.get_docstring(child, clean=False) or ""
                out[key] = _Fn(
                    fingerprint=_fingerprint(child, body),
                    anchors=doc.count("变更:"),
                    doc=doc,
                    line=child.lineno,
                    end_line=child.end_lineno,
                )
                walk(child, f"{key}.")

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



def ref_exists(root, ref):
    """判断 ref 是否指向这个仓库里的一个提交。[基础设施]

    cli 用它在跑审计之前把 `--base` 校验掉:ref 写错是用法错误,
    该立刻报,而不是让 changed_functions 静默返回空、报告假装没有改动。

    Args:
        root: 仓库内的任意路径。
        ref: 分支名、标签、提交号或 HEAD~N 这类表达式。

    Returns:
        bool。不是 git 仓库也返回 False。
    """
    return _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") is not None


@dataclass(frozen=True)
class _Change:
    """一个函数相对 base 的变化。[基础设施]"""

    new: _Fn          # 工作区里的样子
    old: object       # base 里的样子(_Fn);None 表示 base 里没有 —— 新增函数


def changed_files(proj, base="HEAD"):
    """相对 base 有改动的 .py 文件,含未跟踪的新文件。[主线]

    `git diff` 只列已跟踪的文件;快速迭代里新建的探针脚本还没 `git add`,
    不算上它,新文件里写死的输出路径就会被当成存量、退出码给 0。

    Args:
        proj: Project 实例。
        base: git ref。

    Returns:
        set[str],相对项目根;只含审计范围内、工作区里存在的。
        不是 git 仓库或 base 不存在时返回空集。
    """
    if _git(proj.root, "rev-parse", "--show-prefix") is None:
        return set()
    # -z:NUL 分隔、路径原样;否则非 ASCII 路径会被 git 转义加引号,中文文件名对不上。
    tracked = _git(proj.root, "diff", "--name-only", "-z", "--relative", base, "--", "*.py")
    if tracked is None:
        return set()
    untracked = _git(proj.root, "ls-files", "--others", "--exclude-standard", "-z", "--", "*.py") or ""
    out = set()
    for rel in (tracked + "\0" + untracked).split("\0"):
        rel = rel.strip()
        if rel and proj.in_scope(rel) and (proj.root / rel).is_file():
            out.add(rel)
    return out


def changed_functions(proj, base="HEAD"):
    """相对 base,工作区里哪些函数是新增的或改了签名/体/docstring 的。[主线]

    这是 C1 和差异审阅打标的共同依赖,改动集合只在这里算一次。

    Args:
        proj: Project 实例。
        base: git ref。`HEAD` 是工作区里未提交的改动(快速迭代跑前审计看这个,
            那时这次尝试还没 commit);合并前传实际接收分支（可能是 main、master 或者上一级分支等），比较完整的待合并差异。

    Returns:
        dict,{相对路径: {限定名: _Change}}。文件集合来自 changed_files
        (含未跟踪的新文件);只含新增、指纹变了、或 docstring 变了的函数。
        不是 git 仓库、或 base 不存在时返回空 dict —— 调用方负责在更早的位置校验 ref。
    """
    # git show 需要仓库根相对路径,而项目根可能是仓库的子目录(monorepo),
    # 所以要用 prefix 换算。
    prefix = _git(proj.root, "rev-parse", "--show-prefix")
    if prefix is None:
        return {}
    prefix = prefix.strip()

    out = {}
    for rel in sorted(changed_files(proj, base)):
        path = proj.root / rel
        old_src = _git(proj.root, "show", f"{base}:{prefix}{rel}")
        old = functions_of(old_src) if old_src is not None else {}
        new = functions_of(path.read_text(encoding="utf-8"))
        changes = {}
        for name, fn in new.items():
            prev = old.get(name)
            if prev is None or fn.fingerprint != prev.fingerprint or fn.doc != prev.doc:
                changes[name] = _Change(new=fn, old=prev)
        if changes:
            out[rel] = changes
    return out

def check_project(proj, base="HEAD", changes=None):
    """找出改了函数体却没留变更记录的函数。[主线]

    Args:
        proj: Project 实例。
        base: 比对的 git ref,默认 HEAD(未提交的改动)。差异审阅传 --base 的值。
        changes: 已算好的 changed_functions 结果;传了就不再跑 git。
            cli 为打标已经算过一次,C1 不该再算第二次。

    Returns:
        list[Finding]。不是 git 仓库时返回空列表 —— 没有历史不等于不合规。
        新增函数不报:它整体就是新增,git 已经记录。
    """
    if changes is None:
        changes = changed_functions(proj, base)
    out = []
    for rel, fns in changes.items():
        for name, ch in fns.items():
            if ch.old is None:
                continue  # 新增函数,git 已经记录
            if ch.new.fingerprint == ch.old.fingerprint:
                continue  # 只改了 docstring,补写注释不算逻辑改动
            # 同名去重给第二支加了 `#n`,判 dunder 前先剥掉,否则 `__call__#1`
            # 因 endswith("__") 为假而失去豁免。
            if parser.is_dunder(name.rpartition(".")[2].split("#")[0]):
                continue
            if ch.new.anchors > ch.old.anchors:
                continue
            out.append(Finding(
                "C1", rel, ch.new.line, name,
                "函数体已改但 docstring 里没加「变更:」行",
            ))
    return out
