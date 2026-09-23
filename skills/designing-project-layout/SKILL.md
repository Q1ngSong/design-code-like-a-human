---
name: designing-project-layout
description: Use when a research project has no usable directory structure yet - a new or empty repo, new code with nowhere to land, a flat pile of files - or the first time .comment-standard.json is enabled and layers must be filled. Proposes a directory tree that maps directly onto the auditing skill's layers (core, middle, outermost) plus the layers/vendored/output_roots values. Not for re-organising a project that already has a structure - there it only describes the existing tree as layers. 触发场景：新项目怎么建目录、目录结构怎么定、代码目录设计、新文件放哪、layers 怎么填、文件太平了分不清核心和脚本。
---

# 目录结构缺失时，先拟一份

多数项目已经有结构，改动落在现有文件里，`writing-minimal-code` 规划时说一句
「改 `ovam/attention.py`，探针放 `temp_scripts/`，输出存 `runs/...`」就够。只有四种时刻用这份技能：
新项目或空仓库；要加的东西在现有目录里没有落脚处；平铺的文件已经多到分不清哪些是核心
哪些是脚本；首次启用规范要填 `layers`——这时只是把现有目录描述成层，不挪文件。
已有结构的项目跟着现有习惯，不为了分层去挪文件、建目录。

## 先看现状

    ls <项目根>
    codegraph query <某个核心符号>      有索引的话看看谁依赖谁

判据只有一条：**谁离不开谁**。几个包同为核心、说不出谁上谁下的，放同一层。

- **最内层**是拿掉它别的就跑不了的那个——通常是同名于项目的包（`ovam/`），或者放模型、
  算法主体的目录。`src/<项目名>/` 这种布局只能整体写成 `"src"`，里面不能再分层
- **最外层**是拿掉它主体照常跑的——临时脚本、探针、`temp_scripts/`、`sandbox/`
- **中间层**是调用核心、又被外层调用的——评测、训练、`scripts/`、`tools/`

判不准就问一句：「拿掉 `scripts/`，`ovam/` 还能用吗？反过来呢？」答案通常一秒就出来。

## 拟出来的树

每个目录写它在项目里的角色，每个文件写它的功能：

```
cores/                                     最内层（layers 首项）：核心方法实现
  pipeline.py                              主采样循环、检测触发、latent 替换
  rewind.py                                局部加噪、短程修复、背景锚定
  detectors/                               可替换的检测与定位模块；子目录随顶层同属核心层
    base.py                                统一接口、检测上下文与返回结构
    ovam.py                                当前步 OVAM 定位
scripts/                                   中间层：正式运行入口，调核心、被 temp_scripts 调
  generate.py                              模型、时间步、条件、检测器、seed 的命令行入口
temp_scripts/                              最外层：按实验需要创建的运行脚本和探针
  smoke_test.py                            小规模闭环验证（[一次性]）
  sweep_timesteps.py                       调 scripts/generate.py 扫描 t1/t2
  compare_detectors.py                     比较几种定位方法
tests/                                     自动化正确性检查；不进 layers
  test_rewind.py                           加噪公式、返回时间、背景一致性
  test_pipeline.py                         基线一致性、触发、状态替换
docs/                                      研究与实现文档，不是代码
reference_proj/<baseline_name>/            上游参考源码与复现的中间文件，只读、不入库、不上 sys.path，核心不 import 它，跑实验的时候的脚本可能引用它
BASELINES.md                               每个 baseline 的来源、commit、角色与复现判定，入库；见 reproducing-baselines
experiments/ablation_study/timesteps/      实验记录，入库；组路径照 outputs/ 去掉根和叶子
  results.csv                              一行一次尝试
  README.md                                本组的问题、结论与限制
outputs/ablation_study/timesteps/{task}/   实验产物，不入库：config.json、metrics.json、images/ …
.gitignore                                 含 outputs*/、reference_proj/ 等，模板见 auditing-code-comments 的 references/setup.md
PROJECT.md                                 给 Agent 的项目说明：研究什么、主体在哪、规矩与边界
README.md                                  安装、使用和方法说明，给人看
```

对应的声明：

    "layers": ["cores", "scripts", "temp_scripts"],
    "output_roots": ["outputs"]


树要能直接写成 `.comment-standard.json` 的声明，审计规则查的就是这几条：

- `layers`、`vendored`、`output_roots` 只认顶层目录名，不能含 `/`；要分层的目录直接放在项目根下
- 由核心到外围排列，依赖只能由外向内（D1 查）；同层可以互调，一层可以是几个平级目录，写成列表
- `[一次性]` 只放最外层（R2 查）；最外层的函数同样要有角色标记（R0 查），其余三种标记不限层
- 只声明一层时没有最外层，`[一次性]` 不能进那一层，R2 会报「单层就是核心，一次性代码该移出去」：
  要么放层外（根上的脚本不分层、不校验），要么再声明一个外层来放它，不为它硬凑第二层
- 复制进来的第三方代码单独一个目录，对应 `vendored`，不放进任何层。审计把它当最内层：
  我们的代码依赖它永远合法，它反过来 import 我们的代码才报 D1。上游参考源码（各自带 `.git`
  的克隆）不入库、不上 `sys.path`，核心不 import 它——新 clone 跑不起来，索引也看不见它；
  要用就 pip 装上游，或把用到的那部分抄进核心并在 docstring 写明来源，整包要用才复制成
  入库的 `vendor/<名>/` 并声明 `vendored`
- 输出放 `output_roots`（默认 `runs/`）下，`.gitignore` 加 `runs*/`：D2 查这条，但目录还不存在时
  它不报，所以拟树时就写进去。`runs/` 下的路径按 `saving-experiment-outputs` 定，新项目先问
  那三个问题，树里只填答案；写盘点从一个 `out` 派生（D3 查）。记录放 `experiments/{部分}/{组}/results.csv`，入库
  （`recording-experiment-results`）
- 层不必覆盖所有目录，没进任何层的路径跳过层级校验；宁可少写一层，也不要为了凑齐硬塞

## 常见形态

| 项目长这样 | 建议 |
|---|---|
| `ovam/` + `scripts/` + `temp_scripts/` | `["ovam", "scripts", "temp_scripts"]` |
| 核心两个包平级（`ovam/` 和 `erase/`），脚本按模型分成两个目录 | `[["ovam","erase"], ["scripts_sd15","scripts_sdxl"], "temp_scripts"]` —— 列表就是一层，任何一层都可以；同层互通，内层不能依赖外层 |
| 只有一个包 + 根上几个脚本 | `["<包名>"]` —— 根上的脚本不分层，自动跳过校验。**单层就是核心，不享受最外层豁免**，R1/R4/R5/R6 照跑；探针放层外（根上），或再加一个外层目录 |
| 全平铺，没有目录结构 | **别写 `layers`**。分层是描述现状，不是强加结构；文件多到分不清时才按上面的树拆，拆是调整结构，要有人在场 |
| 分不清中间层 | 先写两层 `["核心", "外围"]`，跑一轮看 D1 报什么再细分 |

**顺序错了比不写更糟。** 写反了会把正常的依赖全报成违规，用户第一次跑就看到满屏 D1，
多半直接把配置删了。拿不准顺序就先只写最内层那一个——这样没有最外层，核心层按最严的
标准查，不会漏。

## 顺带补一份项目入口

根上的 `PROJECT.md` 是给 Agent 看的项目说明，README 是给人看的：前者写主体代码在哪、
怎么跑一次、这个项目有哪些规矩和边界，后者写怎么装怎么用。模板、该写什么不该写什么、
谁写什么时候改，见 [项目入口](references/project-entry.md)。

已有结构、不需要拟树的项目也可以只补这一份，不必先整理目录。

## 产出

三样一起给：拟定的树、`PROJECT.md` 的骨架，和可以直接写进 `.comment-standard.json`
的建议值——总是给 `layers`；输出目录不叫 `runs` 时再给 `output_roots`；有第三方代码时再给 `vendored`：

    "layers": ["drift", "scripts", "temp_scripts"],
    "vendored": ["vendor"],
    "output_roots": ["outputs"]

**你不改 `.comment-standard.json`**，建议值由用户写进去；首次启用要不要开也先问用户，
不自作主张创建（`auditing-code-comments` 的规矩）。用户写进去之后跑一次审计，`empty_layer_dirs` 为空
才算生效，不为空说明有目录名对不上，R2/D1 对它静默跳过。`PROJECT.md` 是新文件，可以直接写，
但「在研究什么」和「边界」两节只有用户知道：有人在场问一句再填，无人值守留空并在记录里
说明留空的原因，不替用户编研究目标。补 `.gitignore`、索引范围、误入库文件，
见 `auditing-code-comments` 的 `references/setup.md`。

有人在场时确认或改一个字再动手。无人值守时只按实验计划给新文件、新目录定位置，依据写进
CSV 简介列或 commit message；拆平铺、挪已有文件是调整结构，留到有人在场；要不要启用规范、
`layers` 怎么写也留给用户，建议值一并写进记录，不建、不改 `.comment-standard.json`。
