"""基于文件系统的规则:D2 输出区未被 .gitignore 忽略。

既不解析源码也不查索引,只看目录和 .gitignore。
前提是输出区目录**实际存在** —— output_roots 有默认值,若以「声明了」为前提,
一个还没跑过实验的新项目会被提示去 ignore 一个不存在的目录。
"""
from .rules_ast import Finding


def _ignores(gitignore_lines, name):
    """判断 .gitignore 里是否有忽略该顶层目录的行。[主线]

    Args:
        gitignore_lines: .gitignore 的各行,未 strip。
        name: 顶层目录名,如 `runs`。

    Returns:
        bool。接受 `runs`、`runs/`、`/runs`、`/runs/` 与 glob 形式 `runs*`、
        `runs*/`、`/runs*/`。glob 形式是为换根冻结准备的 —— 一条 `runs*/`
        覆盖 runs、runs-v2、runs-v3。按整行比较而非前缀:`runs_archive/`
        不算忽略了 `runs/`。
    """
    for raw in gitignore_lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pat = line.lstrip("/").rstrip("/")
        if pat == name:
            return True
        if pat.endswith("*") and name.startswith(pat[:-1]):
            return True
    return False


def check_project(proj):
    """跑 D2。[主线]

    Args:
        proj: Project 实例。

    Returns:
        list[Finding]。输出区目录不存在时返回空列表。
    """
    gitignore = proj.root / ".gitignore"
    try:
        lines = gitignore.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        lines = []

    out = []
    for root in proj.output_roots:
        if not (proj.root / root).is_dir():
            continue  # 还没跑过实验的项目,不提示去 ignore 一个不存在的目录
        if _ignores(lines, root):
            continue
        out.append(Finding(
            "D2", ".gitignore", 0, root,
            f"实验输出区 {root}/ 已存在但未被 .gitignore 忽略,"
            f"加一行 `{root}*/`(覆盖换根后的所有版本)",
        ))
    return out
