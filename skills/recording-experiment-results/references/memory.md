# 最小实验 memory

memory 就是可浏览的实验记录和摘要。沿用 CSV、Markdown、原始输出与 Git，不另存 JSON、
哈希清单或数据库。已有指标 JSON 照常保留。

## 目录与内容

新组按论文用途组织；已有记录根目录及大小写优先，不为模板强制搬迁。

```text
experiments/                         # 入 Git
  README.md                          # 总览：各部分结论、缺口、入口链接
  exploration/                       # 暂未归入论文的探索实验
  main-result/
    README.md                        # 按需：本部分摘要、实验组链接
    baseline-comparison/
      README.md                      # 问题、条件、结论与限制、证据链接
      results.csv                    # 原有五列，一行一次尝试
  ablation/
  analysis/                          # 参数、效率、案例等；只创建需要的分类
outputs/                             # 不入 Git
  baseline-comparison/{task}/         # 实际运行的配置、指标、日志、模型
  analysis/{batch}/                  # 按需：跨运行分析及其输入、计算方法
```

记录按论文用途导航，输出按实际执行归属；两棵目录树不必相同。CSV 的「输出目录」是关联，
新记录中的相对输出路径统一相对于项目根目录，绝对外部路径也可用。旧记录若用其他基准，
先核对真实位置再调整引用，不静默改变语义。不同组可有同名 task；CSV 路径 + task 区分尝试。
实验后来进入另一个论文部分时，更新导航链接即可；多个部分引用同一实验，不复制 CSV 或产物。

组 README 写共用命令、代码/配置/数据与环境依据，以及当前结论、限制和论文图表位置；
每次差异继续写 CSV「简介」。来源尽量链接已有配置、日志和指标，不重新抄写大段内容。
总览保持简短，例如：

| 部分 | 当前结论 | 尚缺什么 | 实验入口 |
|---|---|---|---|
| main-result | 待验证 | 基线比较尚未完成 | [基线比较](main-result/baseline-comparison/README.md) |

上表是模板，实际写入时只列真实存在的实验入口。部分摘要仅在有助导航时创建。

## Agent 读写

- 跑前：recording 作为记录入口；输出未定时查 saving 规则，确定 task、路径和基准，
  然后用 `exp-plan` 登记 CSV 计划，结果暂空。
- 跑后：读取本次必要原始结果，用 `exp-finish` 补齐 CSV，更新本组摘要；
  只有部分结论改变才更新上级摘要。
  保留失败和未完成记录，沿用主 Skill 的版本、恢复与提交规则；摘要与相应记录一同保存。
- 查询：总览 → 相关部分/组摘要。概览可据摘要回答；具体数字或比较必须读相关 CSV 和原始证据。
  查询“全部、最佳、均值”先枚举完整目标范围，再筛选或计算，不把少量命中当全集。
- 更新后检查相关组，交接或调整导航后检查全部记录。脚本只返回计数与有限条异常，
  不把整份 CSV、日志或所有摘要加载进 Agent 上下文。来源缺失时报告缺口，不编造结果。

## Agent 使用的脚本命令

这些是 Agent 执行的脚本子命令，不是宿主的全局 slash 指令；用户只需描述任务。
使用本 Skill 的 `scripts/memory.py`，Python 3.10+ 标准库。先从 `--help` 确认当前命令名。
公开名称集中在脚本的 `COMMANDS`，以后重命名只改映射键并同步本文，不增加通用命令框架。

以下为虚构路径和指标，执行时替换为真实信息：

```sh
python /path/to/recording-experiment-results/scripts/memory.py exp-plan --root /path/to/project --records experiments --csv main-result/baseline-comparison/results.csv --task method-a_round1 --purpose '与基线比较' --output outputs/baseline-comparison/method-a_round1
python /path/to/recording-experiment-results/scripts/memory.py exp-finish --root /path/to/project --records experiments --csv main-result/baseline-comparison/results.csv --task method-a_round1 --metrics 'FID 12.3' --status keep --conclusion '本批开发集改善；补独立验证'
```

`--csv` 相对于记录根目录；输出相对于项目根目录。`exp-plan` 创建必要的记录目录及 CSV，
不创建或改写产物，拒绝重复 task。输出目录已存在时由 saving 核对归属，登记本身不代表允许覆盖；
已有尝试按恢复流程处理。
`exp-finish` 只更新已有且结论为空的尝试，失败指标用 `—`；已有结论的修订和 `summary` 行
仍按原记录规则明确修改并检查，不通过此命令覆盖。写入校验候选 CSV 的格式、task 和状态，
输出可用性留给 `exp-check`：历史产物缺失不阻止新记录；创建输出前就失败也能登记，结论注明原因。
记录成功不表示证据完整。同一 CSV 的脚本写入互斥。异常终止若留下 `.csv.lock`，先确认
无写入进程再人工清理；不同时用编辑器修改同一 CSV。脚本不执行实验、不生成摘要、不操作 Git。

交接或修改摘要后执行只读检查：

```sh
python /path/to/recording-experiment-results/scripts/memory.py exp-check --root /path/to/project --records experiments
python /path/to/recording-experiment-results/scripts/memory.py exp-check --root /path/to/project --records experiments --scope main-result/baseline-comparison
```

`--records` 按实际根目录填写，例如 `experiments`；`--scope` 相对于它，可指定组目录或单个文件。
`exp-check` 递归检查选定范围内的 CSV 和 Markdown，按文件里写的路径核对引用，不假设记录和产物的目录一一对应，也不修改任何文件。

- CSV：标准五列、组内唯一 task、计划和输出路径；完成状态、指标非空及输出目录存在。
  空结论保持未完成，允许尚未创建输出；`summary` 不要求状态前缀或输出叶子同名，可无基线。
- 输出：普通尝试的叶子与 task 一致；不同记录引用同一目录只警告。局部检查只能发现范围内重复。
- Markdown：检查代码块外的内联本地链接，如 `[指标](../../../outputs/a/metrics.json)`；
  相对于 Markdown 文件解析。含空格或括号的路径用 `[标签](<路径>)`。
  不检查远程 URL、锚点、引用式链接或普通文字路径。

成功退出 0，错误退出 1；警告不阻断。默认最多显示 20 条诊断，`--limit` 可调整，
始终完成范围内扫描并报告错误总数。缺失范围会报错，不把“没找到文件”当成功。
本版只检查格式和引用存在性，不检测内容覆盖、摘要过时或科学结论正确性，不自动统计实验数值。
已有其他表格格式继续沿用；接入前单独适配，不能为了检查器重写旧台账。
