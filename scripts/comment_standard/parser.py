"""注释标准的纯解析函数。

本模块不做任何 I/O —— 输入是 AST 节点或字符串,输出是数据结构。
校验规则(rules_ast)与回填(backfill)都建立在这些函数之上。
"""
import ast
import re

ROLES = ("[主线]", "[旁支]", "[基础设施]", "[一次性]")

# 实例方法与类方法的首参不是调用方需要了解的输入,不要求在 Args 中介绍。
SKIP_ARGS = frozenset({"self", "cls"})


def is_dunder(name):
    """判断是否为 __dunder__ 名称。[基础设施]

    Args:
        name: 函数或方法名。

    Returns:
        bool。仅两端都是双下划线时为真;`__mangled` 这类前缀私有返回假。
    """
    return name.startswith("__") and name.endswith("__") and len(name) > 4


def signature_args(fn):
    """列出函数签名中调用方需要了解的参数名。[主线]

    Args:
        fn: ast.FunctionDef 或 ast.AsyncFunctionDef 节点。

    Returns:
        list[str],**按参数在签名中书写的顺序**排列:
        positional-only → 位置 → *args → keyword-only → **kwargs。
        告警文案「未介绍: a, b」因此与读者眼中的签名顺序一致。
        self / cls 已剔除。
    """
    a = fn.args
    names = [x.arg for x in a.posonlyargs + a.args]
    if a.vararg:
        names.append(a.vararg.arg)
    names += [x.arg for x in a.kwonlyargs]
    if a.kwarg:
        names.append(a.kwarg.arg)
    return [n for n in names if n not in SKIP_ARGS]


# Args 段的终止边界。本标准不设 Raises 字段(异常写在对应的 Args 行里),
# 但仍把它列进终止符:第三方代码里出现 Raises 时,下面的条目不该被
# 当成 Args 的一部分。
_SECTION_END = re.compile(r"^(Returns|Yields|Raises|变更):", re.M)

_ARGS_HEADER = re.compile(r"^Args:\s*$", re.M)

# 条目形如 `    name: 说明`、`    name (str): 说明`、`    *args: 说明`、
# `    **kwargs: 说明`,必须有缩进。Google 风格的可变参数带星号,匹配时剥掉。
_ARG_ENTRY = re.compile(r"^[ \t]+\*{0,2}([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:", re.M)


def parse_args_section(doc):
    """取出 docstring 的 Args 段里列出的参数名。[主线]

    Args:
        doc: 已去缩进的 docstring 文本(ast.get_docstring 的输出)。

    Returns:
        set[str];**没有 Args 段时返回 None**。二者含义不同:None 表示
        「作者根本没写这一段」,空集合表示「写了段但没有条目」,
        R4 对这两种情况给出不同的告警文案。
    """
    m = _ARGS_HEADER.search(doc)
    if not m:
        return None
    tail = doc[m.end():]
    stop = _SECTION_END.search(tail)
    if stop:
        tail = tail[: stop.start()]
    return set(_ARG_ENTRY.findall(tail))


def _own_body_nodes(fn):
    """遍历函数自身的语句,不进入嵌套的函数与类。[基础设施]

    Args:
        fn: ast.FunctionDef 或 ast.AsyncFunctionDef 节点。

    Returns:
        生成器,逐个产出属于本函数作用域的 AST 节点。嵌套定义整体跳过 ——
        否则内层函数的 return 会被误算成外层有返回值。
    """
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def returns_a_value(fn):
    """判断函数是否产出值。[主线]

    Args:
        fn: ast.FunctionDef 或 ast.AsyncFunctionDef 节点。

    Returns:
        bool。`return`(裸)与 `return None` 不算;`yield` / `yield from` 算,
        因为调用方仍需知道产出什么。嵌套函数的 return 不计入。
    """
    for node in _own_body_nodes(fn):
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return True
        if isinstance(node, ast.Return) and node.value is not None:
            is_none = isinstance(node.value, ast.Constant) and node.value.value is None
            if not is_none:
                return True
    return False


_ROLE_RE = re.compile(r"\[(主线|旁支|基础设施|一次性)\]")
_ROLE_TAIL_RE = re.compile(r"\[(主线|旁支|基础设施|一次性)\]\s*$")


def roles_in_summary(doc):
    """列出摘要行里出现的全部角色标记。[基础设施]

    Args:
        doc: docstring 文本，允许为空串。

    Returns:
        list[str]，去掉方括号的角色名，按出现顺序。用来判断标记是不是唯一。
    """
    summary = doc.split("\n", 1)[0] if doc else ""
    return _ROLE_RE.findall(summary)


def role_of(doc):
    """取出摘要行末尾的角色标记。[主线]

    Args:
        doc: docstring 文本，允许为空串。

    Returns:
        去掉方括号的角色名（如 "主线"）；不合规时返回 None。

    要求标记是**摘要行末尾唯一的那个**（允许尾随空白）。两条约束各有来由：

    - **行末**是唯一能区分「这是标记」和「文字里引用了标记」的语法边界。
      「解析 `[旁支]` 标记并生成报告。[基础设施]」若只做子串搜索会误判成旁支——
      讨论标记的代码里这种摘要很常见。
    - **唯一**是因为两个标记互相矛盾，不该由 ROLES 的排列顺序悄悄裁决。
      而且 SQL 那几条规则各自独立匹配，`[主线][旁支]` 会让同一个函数
      既当 R3 的调用方又当被调用方，Python 这边取哪个都救不了。
    """
    if len(roles_in_summary(doc)) != 1:
        return None
    summary = doc.split("\n", 1)[0] if doc else ""
    m = _ROLE_TAIL_RE.search(summary)
    return m.group(1) if m else None
