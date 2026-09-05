"""项目定位、审计范围与代码分层。

`.comment-standard.json` 的存在与否是这套规范在某个项目上的总开关:
SessionStart hook 靠它判断要不要介入,命令靠它给出可操作的提示。

三个概念:

**审计范围** —— 靠排除定义,不靠列举。除了实验输出区(`output_roots`)与
`.git` / `__pycache__` 这类噪声,项目里其余一切都纳入索引与审计。
科研原型的源码不会都待在一个文件夹里,列举注定漏。

**分层** —— `layers` 由核心到外围排序,顺序本身就是规则:依赖只能由外向内。
`["ovam", "scripts", "temp_scripts"]` 意味着 temp_scripts 可以调 scripts 和
ovam,scripts 可以调 ovam,反向一律禁止。内层引用外层是模块化崩坏的确切信号。


**第三方代码** —— `vendored` 列出复制进来的外部代码(如官方 sd15 实现)。
它要被索引(追踪谁调了它),但不按我们的标准审注释 —— 那不是我们写的。
依赖方向上它是最内层:谁都能依赖它,它不能反过来依赖我们的代码,
否则以后没法跟上游同步。

未声明进任何层的路径不参与层级校验 —— 那是"没说",不是"违规"。
"""
import json
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

CONFIG_NAME = ".comment-standard.json"
# experiments/ 也在默认里:实验记录是产物不是代码,和 runs/ 一样不入库,
# 放进输出区让 D2 顺带检查它有没有被 .gitignore。
DEFAULT_OUTPUT_ROOTS = ("runs", "experiments")

# 任何项目都不该审计的目录,与配置无关。
ALWAYS_EXCLUDED = frozenset({
    ".git", ".codegraph", "__pycache__", ".venv", "venv",
    "node_modules", ".pytest_cache", ".mypy_cache", ".tox",
})


class NotEnabled(Exception):
    """项目尚未启用本规范。[基础设施]"""


class BadConfig(Exception):
    """配置文件存在但无法解析。[基础设施]"""


def _top_segment(rel_path):
    """取相对路径的第一段。[基础设施]

    Args:
        rel_path: 相对项目根的路径。

    Returns:
        str;路径为空时返回 None。按路径段切分而非字符串前缀,
        所以 `runs_archive/` 不会被 `runs` 误判命中。
    """
    parts = Path(rel_path).parts
    return parts[0] if parts else None


def _matches_prefix(rel_path, patterns):
    """按路径段前缀匹配 gitignore 风格的目录模式。[基础设施]

    Args:
        rel_path: 相对项目根的路径。
        patterns: 模式串,如 `static/`、`assets/theme`、`vendor/**`。

    Returns:
        bool。只处理目录前缀这一种常见形态 —— 降级路径够用,
        精确判断交给索引。按段比较,`vendor_theme_mine/` 不会被 `vendor_theme/` 命中。
    """
    parts = Path(rel_path).parts
    for pat in patterns:
        pat_parts = Path(pat.rstrip("/").replace("/**", "")).parts
        if pat_parts and parts[:len(pat_parts)] == pat_parts:
            return True
    return False


@dataclass(frozen=True)
class Project:
    """一个已启用本规范的项目。[主线]"""

    root: Path
    db_path: Path
    output_roots: tuple   # 实验输出区,可有多个;排除在索引与审计之外
    layers: tuple   # 层名,由核心到外围
    vendored: tuple = ()      # 第三方代码目录
    codegraph: object = None  # 写出成 codegraph.json 的内容
    _indexed: object = None      # indexed_files 的缓存,勿直接读
    _cg_patterns: object = None  # codegraph.json 的 include/exclude 缓存
    _git_files: object = None    # git 可见文件集缓存

    def indexed_files(self):
        """codegraph 索引里的文件集合。[主线]

        Returns:
            set[str],项目根相对路径;没有索引或表不可读时返回 None。

        这是审计范围的权威来源 —— 索引是 `.gitignore`、`codegraph.json` 的
        include/exclude、以及 codegraph 内置默认三者的最终结果。直接问它,
        就不必重新实现一遍 gitignore 匹配,也不会与 codegraph 的看法漂移。
        用户想指定解析哪些文件夹,写 codegraph.json 即可,我们跟着走。
        """
        if self._indexed is not None:
            return self._indexed or None
        if not self.db_path.exists():
            return None
        try:
            con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            try:
                rows = con.execute("SELECT path FROM files").fetchall()
            finally:
                con.close()
        except sqlite3.Error:
            return None
        object.__setattr__(self, "_indexed", {r[0] for r in rows})
        return self._indexed or None

    def in_scope(self, rel_path):
        """判断路径是否纳入索引与审计。[主线]

        Args:
            rel_path: 相对项目根的路径。

        Returns:
            bool。实验输出区与通用噪声目录一律排除 —— 输出区装的是运行时产物,
            偶尔出现的 .py 多半是保存下来的配置快照或临时脚本,
            按主代码的注释标准去审它们没有意义。
            其余部分有索引时以索引为准(用户通过 codegraph.json 说了算),
            没有索引时降级为全部纳入:源码分布在哪些文件夹是项目自己的事,
            列举必然漏。
        """
        top = _top_segment(rel_path)
        if top is None or top in ALWAYS_EXCLUDED or top in self.output_roots:
            return False
        indexed = self.indexed_files()
        if indexed is not None:
            return rel_path in indexed
        return self._fallback_in_scope(rel_path)

    def _codegraph_patterns(self):
        """读 codegraph.json 的 include / exclude。[基础设施]

        Returns:
            (include, exclude) 两个元组。文件不存在或解析失败时返回两个空元组 ——
            那不是我们的文件,坏了不该让整个审计罢工。
        """
        if self._cg_patterns is not None:
            return self._cg_patterns
        include = exclude = ()
        raw = self.codegraph
        try:
            if raw is None:
                cfg = self.root / "codegraph.json"
                raw = json.loads(cfg.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                include = tuple(x for x in (raw.get("include") or ()) if isinstance(x, str))
                exclude = tuple(x for x in (raw.get("exclude") or ()) if isinstance(x, str))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass
        object.__setattr__(self, "_cg_patterns", (include, exclude))
        return self._cg_patterns

    def _git_visible(self):
        """git 认为属于这个项目的文件(已跟踪 + 未跟踪且未被忽略)。[基础设施]

        Returns:
            set[str],项目根相对路径;不是 git 仓库时返回 None。
            一次调用拿到全集,不逐文件问 —— `git check-ignore` 每文件一次太慢。
        """
        if self._git_files is not None:
            return self._git_files or None
        proc = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard"],
            cwd=self.root, capture_output=True, text=True,
        )
        files = set(proc.stdout.splitlines()) if proc.returncode == 0 else set()
        object.__setattr__(self, "_git_files", files)
        return files or None

    def _fallback_in_scope(self, rel_path):
        """没有索引时的降级判断。[主线]

        优先级 **codegraph.json > .gitignore**,与 codegraph 建索引时一致:

        1. `exclude` 命中 → 出局(它能排掉已被 git 跟踪的目录)
        2. `include` 命中 → 纳入(它能拉回被 .gitignore 丢掉的源码)
        3. 否则看 git 是否忽略了它
        4. 不是 git 仓库 → 纳入,不猜

        Args:
            rel_path: 相对项目根的路径。

        Returns:
            bool。这是近似判断 —— 只支持目录前缀与路径段匹配,
            不实现完整的 gitignore 通配语义。建了索引之后走精确路径。
        """
        include, exclude = self._codegraph_patterns()
        if _matches_prefix(rel_path, exclude):
            return False
        if _matches_prefix(rel_path, include):
            return True
        visible = self._git_visible()
        if visible is None:
            return True
        return rel_path in visible

    def is_vendored(self, rel_path):
        """判断路径是否为复制进来的第三方代码。[主线]

        Args:
            rel_path: 相对项目根的路径。

        Returns:
            bool。按路径段比较,`sd15_patched/` 不会被 `sd15` 误判命中。
        """
        return _top_segment(rel_path) in self.vendored

    def layer_of(self, rel_path):
        """取路径所属的层名。[主线]

        Args:
            rel_path: 相对项目根的路径。

        Returns:
            层名字符串;不属于任何已声明层时返回 None。
            None 表示"未声明",层级规则会跳过它,而不是判它违规。
        """
        top = _top_segment(rel_path)
        return top if top in self.layers else None

    def _layer_index(self, rel_path):
        """取路径所属层的序号,0 为最内层。[基础设施]

        Args:
            rel_path: 相对项目根的路径。

        Returns:
            int;未分层时返回 None。
        """
        layer = self.layer_of(rel_path)
        return self.layers.index(layer) if layer is not None else None

    def may_depend(self, src_path, tgt_path):
        """判断源文件是否允许依赖目标文件。[主线]

        依赖只能由外向内或同层内部。核心功能不该知道脚本的存在 ——
        一旦知道,核心就没法脱离脚本单独复用,模块化即告崩坏。

        Args:
            src_path: 发起依赖的文件,相对项目根。
            tgt_path: 被依赖的文件,相对项目根。

        Returns:
            bool。任一方未分层时返回 True —— 未声明不等于违规,
            要校验就先把它声明进某一层。第三方代码不受此限:
            即使没声明 layers,「第三方依赖了我们的代码」也判违规。
        """
        # 第三方代码是最内层:被依赖永远合法,主动依赖我们的代码永远违规。
        if self.is_vendored(tgt_path):
            return True
        if self.is_vendored(src_path):
            return False
        src = self._layer_index(src_path)
        tgt = self._layer_index(tgt_path)
        if src is None or tgt is None:
            return True
        return src >= tgt

    def is_outermost(self, rel_path):
        """判断路径是否位于最外层。[主线]

        最外层是 `[一次性]` 代码的唯一合法住处:依赖规则保证没有内层能依赖
        外层,放在最外层就等于没有任何东西能依赖它 —— 正是一次性代码
        该有的性质。因此无需再为它单开一个配置项。

        Args:
            rel_path: 相对项目根的路径。

        Returns:
            bool。未声明 layers 时恒为 False。
        """
        if not self.layers:
            return False
        return self.layer_of(rel_path) == self.layers[-1]


def find_root(start):
    """从 start 向上寻找带配置文件的目录。[主线]

    Args:
        start: 起始目录。

    Returns:
        Path;找不到时返回 None。到文件系统根为止。
    """
    cur = Path(start).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / CONFIG_NAME).is_file():
            return candidate
    return None


def load(start):
    """定位并载入项目配置。[主线]

    Args:
        start: 起始目录,通常是命令的工作目录。

    Returns:
        Project 实例。

    未找到配置时抛 NotEnabled,配置无法解析时抛 BadConfig ——
    两者的提示语不同,前者要引导用户启用,后者要指出文件位置。
    """
    root = find_root(start)
    if root is None:
        raise NotEnabled(
            f"未找到 {CONFIG_NAME}:该项目尚未启用注释标准。"
            f"在项目根创建 {CONFIG_NAME}(内容 {{}} 即可)后重试。"
        )
    config_file = root / CONFIG_NAME
    try:
        raw = json.loads(config_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BadConfig(f"{config_file} 无法解析:{exc}") from exc
    cfg = _validate(raw, config_file)
    return Project(
        root=root,
        db_path=root / ".codegraph" / "codegraph.db",
        output_roots=cfg["output_roots"],
        layers=cfg["layers"],
        vendored=cfg["vendored"],
        codegraph=cfg["codegraph"],
    )


# =============================================================================
# 配置校验
#
# 配置是所有规则的前提,它错了后面全错,而且往往是静默地错:
# `layer` 打成 `layers` 的 typo 会让分层校验整个失效却毫无提示。
# 所以这里从严 —— 未知字段也算错 —— 并且一次报全所有问题。
# =============================================================================

_KNOWN_KEYS = frozenset({"layers", "output_roots", "vendored", "codegraph"})


def _check_dir_name(value, where, errors):
    """校验一个顶层目录名。[基础设施]

    Args:
        value: 待校验的值。
        where: 字段定位,如 `layers[1]`,用于错误信息。
        errors: 累积错误的列表,原地追加。
    """
    if not isinstance(value, str):
        errors.append(f"{where} 必须是字符串,得到 {type(value).__name__}")
        return
    if not value:
        errors.append(f"{where} 不能为空")
        return
    if "/" in value or "\\" in value:
        errors.append(f"{where} 不能含路径分隔符,应是顶层目录名:{value!r}")
    if value in (".", ".."):
        errors.append(f"{where} 不能是 {value!r}")
    if value in ALWAYS_EXCLUDED:
        errors.append(f"{where} 是通用噪声目录,不能用作层或输出区:{value!r}")


def _check_dir_list(raw, key, errors):
    """校验一个顶层目录名列表字段(layers / vendored)。[基础设施]

    Args:
        raw: 配置字典。
        key: 字段名。
        errors: 累积错误的列表。

    Returns:
        tuple,规范化后的目录名;出错时返回空元组。
    """
    if key not in raw:
        return ()
    items = raw[key]
    if not isinstance(items, list):
        errors.append(f"{key} 必须是列表,得到 {type(items).__name__}")
        return ()
    for i, name in enumerate(items):
        _check_dir_name(name, f"{key}[{i}]", errors)
    names = [x for x in items if isinstance(x, str)]
    dupes = sorted({x for x in names if names.count(x) > 1})
    if dupes:
        errors.append(f"{key} 有重复:{', '.join(dupes)}")
    return tuple(names)


def _check_output_roots(raw, errors):
    """校验 output_roots 字段。[基础设施]

    只接受字符串列表。真实项目常同时有 runs/、outputs/、logs/ 几个输出目录，
    所以是列表；只有一个也写成列表，省掉一套单值分支。

    Args:
        raw: 配置字典。
        errors: 累积错误的列表。

    Returns:
        tuple[str]，输出区目录名；未声明时为 DEFAULT_OUTPUT_ROOTS。
    """
    if "output_roots" not in raw:
        return DEFAULT_OUTPUT_ROOTS
    value = raw["output_roots"]
    if not isinstance(value, list):
        errors.append(
            f"output_roots 必须是字符串列表，得到 {type(value).__name__}"
            + ("。只有一个也要写成列表：[\"runs\"]" if isinstance(value, str) else "")
        )
        return DEFAULT_OUTPUT_ROOTS
    if not value:
        errors.append("output_roots 不能为空列表。不想声明就整个不写这个键，"
                      "默认是 [\"runs\", \"experiments\"]")
        return DEFAULT_OUTPUT_ROOTS
    for i, name in enumerate(value):
        _check_dir_name(name, f"output_roots[{i}]", errors)
    names = [x for x in value if isinstance(x, str)]
    dupes = sorted({x for x in names if names.count(x) > 1})
    if dupes:
        errors.append(f"output_roots 有重复：{'、'.join(dupes)}")
    return tuple(names) or DEFAULT_OUTPUT_ROOTS


# codegraph.json 认得的键。打错 excludes 会静默失效,所以从严。
_CG_KEYS = frozenset({"extensions", "includeIgnored", "exclude", "include", "deprioritize"})


def _check_codegraph(raw, errors):
    """校验 codegraph 段。[基础设施]

    Args:
        raw: 配置字典。
        errors: 累积错误的列表。

    Returns:
        dict 或 None。这一段会原样写进 codegraph.json,所以键名必须是
        codegraph 认得的 —— 写成 `excludes` 不会报错,只会静默不生效。
    """
    if "codegraph" not in raw:
        return None
    cg = raw["codegraph"]
    if not isinstance(cg, dict):
        errors.append(f"codegraph 必须是对象,得到 {type(cg).__name__}")
        return None
    unknown = set(cg) - _CG_KEYS
    if unknown:
        errors.append(f"codegraph 有未知字段:{', '.join(sorted(unknown))}。"
                      f"codegraph.json 只认 {', '.join(sorted(_CG_KEYS))}")
    return cg


def _validate(raw, config_file):
    """校验整份配置,一次报全所有错误。[主线]

    Args:
        raw: json.loads 的结果。
        config_file: 配置文件路径,用于错误信息。

    Returns:
        dict,含规范化后的 layers / output_roots / vendored / codegraph。

    任何一处不合法都抛 BadConfig,消息里逐条列出全部问题 ——
    让人改一次跑一次是浪费。
    """
    errors = []
    if not isinstance(raw, dict):
        raise BadConfig(f"{config_file} 顶层必须是对象,得到 {type(raw).__name__}")

    if "output_root" in raw:
        errors.append("output_root 已更名为 output_roots，值要写成列表：[\"runs\"]")

    unknown = set(raw) - _KNOWN_KEYS - {"output_root"}
    if unknown:
        errors.append(f"未知字段:{', '.join(sorted(unknown))}。"
                      f"只认 {', '.join(sorted(_KNOWN_KEYS))}")

    layers = _check_dir_list(raw, "layers", errors)
    vendored = _check_dir_list(raw, "vendored", errors)
    output_roots = _check_output_roots(raw, errors)
    codegraph = _check_codegraph(raw, errors)

    for root in output_roots:
        if root in layers:
            errors.append(f"output_roots 里的 {root!r} 与 layers 中的层同名 —— "
                          f"输出区不索引,层要索引,一个目录不能同时是两者")
        if root in vendored:
            errors.append(f"output_roots 里的 {root!r} 与 vendored 中的目录同名 —— "
                          f"输出区不索引,第三方代码要索引")
    overlap = sorted(set(layers) & set(vendored))
    if overlap:
        errors.append(f"vendored 与 layers 重叠:{', '.join(overlap)} —— "
                      f"一个目录要么是你的代码要么是第三方的")

    if errors:
        raise BadConfig(f"{config_file} 有 {len(errors)} 处问题:\n  - "
                        + "\n  - ".join(errors))
    return {"layers": layers, "output_roots": output_roots,
            "vendored": vendored, "codegraph": codegraph}
