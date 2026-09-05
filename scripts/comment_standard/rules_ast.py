"""基于 AST 的规则:R0 缺角色标记、R4 参数未介绍、R5 缺 Returns、R6 陈旧 Args 条目。

这类规则要比对签名与文档,因此与语言绑定,当前只覆盖 Python。
纯 SQL 的 R1/R2/R3 在 rules_sql.py,那三条天然跨语言。

R4 与 R6 常成对出现:一次参数改名而 docstring 未同步,会让 R4 报新名未介绍、
R6 报旧名不存在,从两侧夹住同一处改动。
"""
import ast
import re
from dataclasses import dataclass

from . import parser

_RETURNS_HEADER = re.compile(r"^(Returns|Yields):", re.M)
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass(frozen=True)
class Finding:
    """一条不合规记录。[主线]"""

    rule: str
    file: str
    line: int
    name: str
    message: str


def check_file(path, rel, contract=True):
    """校验一个 Python 源文件。[主线]

    Args:
        path: 文件的绝对路径。
        rel: 相对项目根的路径,用于告警文案。
        contract: 是否检查输入输出契约(R4/R5/R6)。最外层传 False ——
            那里的一次性代码不会被外人调用,逐参数介绍会退化成为填而填。
            R0 不受此开关影响:摘要与角色标记是审计的输入,任何层都要有。

    Returns:
        list[Finding],按出现顺序。语法错误的文件返回空列表 ——
        语法本身该由解释器和 linter 报,不是本规则的职责。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []

    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, _DEFS) or parser.is_dunder(fn.name):
            continue

        doc = ast.get_docstring(fn) or ""
        if not doc:
            out.append(Finding("R0", rel, fn.lineno, fn.name, "缺 docstring"))
            continue
        if parser.role_of(doc) is None:
            out.append(Finding("R0", rel, fn.lineno, fn.name, "缺角色标记"))

        if not contract:
            continue

        sig = parser.signature_args(fn)
        documented = parser.parse_args_section(doc)
        if not sig and documented:
            # 无参数却留着 Args 条目:参数删光了但文档没跟上,同样是不同步。
            out.append(Finding(
                "R6", rel, fn.lineno, fn.name,
                "函数已无参数,Args 里仍写着: " + ", ".join(sorted(documented)),
            ))
        if sig:
            if documented is None:
                out.append(Finding(
                    "R4", rel, fn.lineno, fn.name,
                    "缺 Args 段,未介绍: " + ", ".join(sig),
                ))
            else:
                missing = [a for a in sig if a not in documented]
                if missing:
                    out.append(Finding(
                        "R4", rel, fn.lineno, fn.name,
                        "未介绍: " + ", ".join(missing),
                    ))
                extra = documented - set(sig)
                if extra:
                    out.append(Finding(
                        "R6", rel, fn.lineno, fn.name,
                        "def 那一行没有这些参数: " + ", ".join(sorted(extra)),
                    ))
        if parser.returns_a_value(fn) and not _RETURNS_HEADER.search(doc):
            out.append(Finding("R5", rel, fn.lineno, fn.name, "有返回值但缺 Returns"))
    return out


def check_project(proj):
    """遍历项目审计范围内的全部 .py 文件。[主线]

    Args:
        proj: Project 实例。

    Returns:
        list[Finding],按 (文件, 行号, 规则) 排序。范围由 Project.in_scope 决定 ——
        靠排除定义,除实验输出区与噪声目录外全部纳入,不管源码分布在几个文件夹。
        第三方代码(vendored)额外跳过:那不是我们写的,不按我们的标准审注释。

    严格度随层级递减:最外层豁免输入输出契约(R4/R5/R6),只留 R0。
    越靠核心的代码越会被外人读和复用,要求越严;最外层的一次性代码
    不会被别人调,逐参数介绍是负担而非信息。
    """
    out = []
    for path in sorted(proj.root.rglob("*.py")):
        rel = path.relative_to(proj.root).as_posix()
        if not proj.in_scope(rel) or proj.is_vendored(rel):
            continue
        out += check_file(path, rel, contract=not proj.is_outermost(rel))
    return sorted(out, key=lambda f: (f.file, f.line, f.rule))
