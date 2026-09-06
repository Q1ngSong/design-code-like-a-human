"""基于 AST 的规则:D3 写盘点直接写死输出路径。

**判据不是「禁止 cwd 依赖」。** `out = Path("runs") / task` 照样相对 cwd,
在 scripts/ 里跑就落到 scripts/runs/ —— 一条真正禁止 cwd 依赖的规则会把
推荐写法自己也判违规。

判据是**路径表达式的根是不是变量**:

- 根是变量(`out / "ckpt.pt"`)—— 说明有一处地方专门决定了这次输出去哪,
  同一次实验的 checkpoint、日志、图会一起落进去。放行。
- 根是字面量(`"ckpt.pt"`、`Path("runs") / x`、`f"runs/{n}.png"`)——
  这个写盘点自己拍了板,决策就散开了。十个写盘点十个决定,
  正是「实验跑十次,结果散在八个目录」的成因。报。

收益是把 N 个分散的路径决策收敛成 1 个。将来要改成 CLI 参数或锚到项目根,
只改那一处。它不消灭 cwd 依赖,只让 cwd 依赖收敛到一个点。

只收高置信的写盘 API,用**全限定名**匹配:裸名字 `save` / `dump` 会让
`business.save("v1.0")` 这类业务方法误报。`json.dump` / `pickle.dump` 的
目标是文件对象而非路径,不收 —— 由写模式的 `open()` 负责发现。
"""
import ast

from .rules_ast import Finding

# 写盘 API → 路径参数的位置下标与关键字名。
# 键是「点号后的最后一段 + 可选的限定前缀」,见 _call_name。
_WRITE_APIS = {
    "torch.save": (1, "f"),        # torch.save(obj, f=...) 与位置形式同义
    "np.save": (0, "file"),
    "numpy.save": (0, "file"),
    "np.savez": (0, "file"),
    "numpy.savez": (0, "file"),
    "np.savez_compressed": (0, "file"),
    "joblib.dump": (1, "filename"),
    "savefig": (0, "fname"),
    "imwrite": (0, "filename"),
    "to_csv": (0, "path_or_buf"),
    "to_json": (0, "path_or_buf"),
    "to_parquet": (0, "path"),
}

_WRITE_MODE_CHARS = frozenset("wax+")


def _call_name(node):
    """取调用的名字,属性调用给出「前缀.末段」与「末段」两种形式。[基础设施]

    Args:
        node: ast.Call 节点。

    Returns:
        set[str],可能的名字。`torch.save(...)` 给出 {"torch.save", "save"},
        `open(...)` 给出 {"open"}。调用方只拿它去比 _WRITE_APIS 的键,
        因此 `save` 这种裸名字不会匹配上 —— 表里只有 `torch.save`。
    """
    fn = node.func
    if isinstance(fn, ast.Name):
        return {fn.id}
    if isinstance(fn, ast.Attribute):
        names = {fn.attr}
        if isinstance(fn.value, ast.Name):
            names.add(f"{fn.value.id}.{fn.attr}")
        return names
    return set()


def _path_root_literal(node):
    """取路径表达式的根,若根是字符串字面量则返回它。[主线]

    只看根,不递归进整个表达式 —— `out / "ckpt.pt"` 里确实有字符串字面量,
    但根是变量 `out`,那正是我们要的写法。

    Args:
        node: 路径参数的 AST 节点。

    Returns:
        str,根处的字面量;根是变量或无法判定时返回 None。
        认这三种根:裸字符串、`Path("...")` 构造、f-string 的首段。
    """
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        node = node.left            # a / b / c 左结合,一路走到最左
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        for part in node.values:    # f"runs/{n}.png" 的首段是字面量
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                return part.value
            return None
        return None
    if isinstance(node, ast.Call):
        names = _call_name(node)
        if "Path" in names or "PosixPath" in names:
            return _path_root_literal(node.args[0]) if node.args else None
    return None


def _path_argument(node, index, keyword):
    """取写盘调用的路径参数。[基础设施]

    Args:
        node: ast.Call 节点。
        index: 路径参数的位置下标。
        keyword: 路径参数的关键字名,没有则为 None。

    Returns:
        AST 节点;调用里没给出路径参数时返回 None。
    """
    if index is not None and len(node.args) > index:
        return node.args[index]
    for kw in node.keywords:
        if kw.arg is not None and kw.arg == keyword:
            return kw.value
    return None


def _open_is_write(node):
    """判断 open() 是否为写模式。[基础设施]

    Args:
        node: 名字为 open 的 ast.Call 节点。

    Returns:
        bool。模式必须是静态可知的字符串字面量;默认(不给模式)与 `r`、`rb`
        判为读,放行 —— 读配置文件写死路径是正当的。
    """
    mode = _path_argument(node, 1, "mode")
    if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
        return False
    return bool(_WRITE_MODE_CHARS & set(mode.value))


def check_file(path, rel):
    """扫一个 Python 源文件里的写盘调用。[主线]

    Args:
        path: 文件的绝对路径。
        rel: 相对项目根的路径,用于告警文案。

    Returns:
        list[Finding],按出现顺序。语法错误的文件返回空列表。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []

    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        names = _call_name(node)

        if "open" in names:
            if not _open_is_write(node):
                continue
            api, (index, keyword) = "open", (0, "file")
        else:
            matched = names & set(_WRITE_APIS)
            if not matched:
                continue
            api = sorted(matched, key=len)[-1]   # 有全限定名就用它
            index, keyword = _WRITE_APIS[api]

        arg = _path_argument(node, index, keyword)
        if arg is None:
            continue
        literal = _path_root_literal(arg)
        if literal is None:
            continue
        out.append(Finding(
            "D3", rel, node.lineno, api,
            f"路径根 {literal!r} 是写死的。在脚本入口定一次输出目录,"
            f"这里改成从它派生",
        ))
    return out


def check_project(proj):
    """遍历项目审计范围内的全部 .py 文件。[主线]

    Args:
        proj: Project 实例。

    Returns:
        list[Finding],按 (文件, 行号) 排序。第三方代码跳过 —— 那不是我们写的,
        它把结果写去哪不归我们管。
    """
    out = []
    for path in sorted(proj.root.rglob("*.py")):
        rel = path.relative_to(proj.root).as_posix()
        if not proj.in_scope(rel) or proj.is_vendored(rel):
            continue
        out += check_file(path, rel)
    return sorted(out, key=lambda f: (f.file, f.line))
