---
name: recording-experiment-results
description: Use when planning, resuming, finishing, or summarizing experiments - record each task's plan before running, then its metrics, conclusion, output path, and reproducible version references before moving on. 触发场景:实验计划、实验恢复、实验跑完了、记录结果、汇总结果、这组实验的结论、上次那个实验结果呢。
---

# 记录实验结果

**开跑前记录计划，运行结束后补齐结果，再开始下一次。** 每次尝试使用同一行记录，
避免只在终端或对话中保留实验信息。

## 一组实验一个 CSV

新组按论文用途放在 `Experiments/{部分}/{实验组}/results.csv`，例如
`Experiments/ablation/lora_rank/results.csv`。已有 `experiments/` 大小写及组 CSV 布局继续沿用。
CSV 的「输出目录」引用实际产物，两边不要求目录同构。一行一次实验：

```csv
task,简介,指标,结论,输出目录
rank8_lr1e-4,"rank 4→8，上轮已收敛未过拟合",FID 12.3 / CLIP 0.281,keep：有效，继续比较 rank16,runs/ablation_study/lora_rank/rank8_lr1e-4
rank16_lr1e-4,继续加到 16 看还有没有收益,FID 11.9 / CLIP 0.283,keep：指标改善，继续比较 rank32,runs/ablation_study/lora_rank/rank16_lr1e-4
rank32_lr1e-4,再翻倍确认拐点,FID 14.1 / CLIP 0.271,"discard：过拟合，回退到 rank16",runs/ablation_study/lora_rank/rank32_lr1e-4
```

按标准 CSV 格式读写；字段含英文逗号、换行或双引号时，正确引用和转义。

`experiments/` **入库**。记录不是产物，是结论——它要随仓库走、要在 `--no-ff` 合并时
进主分支、要在 worktree 删掉之后还在。`runs/` 才是产物，那个不入库。

| 列 | 写什么 |
|---|---|
| `task` | **与输出目录最后一级的名称一致**（命名方式见 `saving-experiment-outputs`） |
| `简介` | **为什么试这个**，不是「跑了个实验」 |
| `指标` | 你关注的那几个数，自由格式（`FID 12.3 / CLIP 0.281`） |
| `结论` | 以 keep / discard / crash / timeout 开头，说明原因和下一步。构建期也用这些状态，便于恢复时判断如何收尾 |
| `输出目录` | 本次尝试的实际输出路径；`runs/` 是示例根目录，项目已有其他路径时沿用 |

`task` 是本次实验设置的缩写，完整组路径 + task 用于关联 CSV 记录、输出目录和 commit message。
三处使用同一个名称，不要另起简称，以免回查时需要逐一对应。

## 原始证据与实验记忆

以总览和实验组 README 导航，CSV 保存尝试，原始文件保留在输出区；不另建 memory JSON。
想看这些尝试的谱系——谁基于谁、哪条路死了——用 `visualizing-experiment-lineage`
从 CSV 和 git 渲染一页，它只读记录、不写记录。
记录、查找或汇总时按 [memory 约定](references/memory.md) 逐层读取、局部更新，
由 Agent 执行 `scripts/memory.py` 的 `exp-plan` 登记计划、`exp-finish` 补结果、
`exp-check` 检查引用。输出未定时先查 saving 规则，已有路径不重复分配。具体数字回源核对，
查询全部结果先枚举目标范围。脚本负责安全写入和检查格式与引用，不判断结论是否正确。

## 版本与提交关联

**用 task 名查找对应版本。** 构建期和快速迭代 keep 的代码在实验分支的 commit 中，
快速迭代 discard、crash、timeout 的代码改动在 stash 中。例如：

    git log --all --fixed-strings --grep=rank8_lr1e-4 --oneline

同名 task 可能出现在不同组，需核对提交中的 CSV 路径和记录。stash 按完整组路径与 task 名
定位，取回方式见 `running-experiments-on-branches`。名称用于检索，不代替版本核对；
重跑还需要对应代码、完整配置和运行参数。固定参数不要只依赖目录名推断。
开组时记录基线提交和合并目标（不明确就写「待定」）；完整命令、种子、数据划分、依赖环境写一次进
本组入库的说明文件，每行 `简介` 只记与之不同的项，保持已有 CSV 列结构。
运行版本就是 keep 的 commit 或 discard 的 stash，前提是跑完到提交、stash 之间不再改实验代码。
以下情况需另存源码和配置快照到本次输出目录并在记录中引用：一次决策跑了多个 task、
跑后确实改了代码、恢复时发现有差异却找不到对应的 commit 或 stash、
使用了外部脚本或工具且版本可能变化。stash 仅是本地存档，不随分支推送。

**开始新尝试前，工作区要干净**：上次的代码和记录已按对应模式提交或存档。

    git status --porcelain     有输出表示存在改动，先检查归属

本次改动**运行结束后再提交**，message 包含 task 名。构建期及快速迭代 keep 时，将代码和
CSV 记录一起提交；快速迭代 discard 时，单独提交 CSV 记录，将代码改动存入 stash。
具体顺序和命令见 `running-experiments-on-branches`。

**开始前工作区不干净怎么办。** 先看是什么，别闭着眼 `git add -A`：

    git status --porcelain
    git diff --stat

先核对本组 CSV、已有进程和工作区差异。结论为空或提交、存档尚未完成时，按
`running-experiments-on-branches` 的恢复流程处理；不要直接把实验中的代码提交成 `chore:`。
尝试已完成后，仍需查清剩余改动的来源，才能按无关改动处理。
**不要 amend 进上一个 commit**——那个 commit 的 message 是上一次实验的记录，塞进无关改动就
说不清那次跑的是什么了。无关改动单独提交，message 写清里面是什么、说明它不是实验：
`chore: 任务开始前清理 —— README 改动、上次崩溃的半成品`。有人在场时先问一句要不要提交，
那可能是他改到一半的东西；无人值守时不问，直接提交成 `chore:`，message 里列清路径，人回来看 log
就知道开跑前工作区里有过什么。进了 git 就不会被后面的 `stash push -u` 收走，也随时能撤回；
不还原、不 stash 用户的改动。

**保存实际运行版本，再做后续修改。** 若跑后修改影响数值路径，分配新 task 重新验证；
纯文档或运行清理等维护变更可另行提交并做对应检查，注明它们晚于该次运行。
原记录继续关联原源码快照，不能将旧指标挂到未经运行的新实现上。
若原源码已无法恢复，明确标记该行不可复现，不编造对应版本。

**每组实验使用一个 CSV 文件。** 需要总表时，枚举实际记录根目录下的 CSV；
沿用项目的 `experiments/` 大小写，不只读取总览列出的少量结果。

## 失败的也要记

跑砸了、结论是「这条路不通」——**照样记一行**，结论写清为什么不通。

只记录成功结果会遗漏已经排除的方向，后续实验可能重复同样的尝试。

## 没跑完的也一样

上一节说的是「跑完了但结论是负面」。**中途挂掉是另一回事**——OOM、数据缺失、
loss 变 NaN、机器被抢占——处理方式一样,三件事都要做:

**补齐本次记录。** 结论以 `crash` 或 `timeout` 开头，写清中断位置和原因：

    rank64,"显存上限试探",—,"crash：OOM,step 3200 中断,batch 8 时显存不够",runs/.../rank64

指标列填 `—`,别留空:留空看着像忘了记,`—` 说明确实没有。

**保留未完成的输出目录，并填入「输出目录」列。** 崩溃前的曲线和日志可用于排查失败原因；
仅记录一句「OOM」会丢失这些依据。判断是发散还是显存问题，需要结合曲线与错误日志。

**照常 commit。** 失败也是一次决策的结果,跳过 commit 就没有带这个 task 名的
commit 可找 —— 三个月后 CSV 里有这一行,git 里却对不上它跑的是什么代码。

**快速迭代的提交方式不同。** CSV 和未完成的输出目录仍需保留，但失败代码存入 stash，
分支只提交记录。崩溃和超时都按 discard 的提交、存档顺序处理，结论分别保留 `crash`
和 `timeout` 状态，见 `running-experiments-on-branches`。

## 什么时候写

**跑前写 `task`、`简介` 和输出目录，跑完补齐 `指标` 和 `结论`。** 使用完整的五列记录，
暂时不知道的结果字段留空，不要只写半行 CSV 文本。

**结果出来后先记录，再决定下一步。** 及时保存当时的判断，避免事后补记时混入后续结果。
暂停或取消的未启动计划保留空结果，在 `简介` 注明原因；恢复时先核对是否仍需执行，
不把从未启动的任务记成 crash，也不把空结果自动视为需要重跑。

这组收尾时（合并前）在 CSV 末尾追加一行总结，随最后一次的 commit 一起提交；
最后一次已经提交了就再提交一次，不 amend（见 `running-experiments-on-branches`
的合并前一节）。这一行五列这样填：
`task` 写 `summary`，`简介` 写胜出的配置，`指标` 写它的指标，
`结论` 写为什么胜出、下一轮打算做什么，`输出目录` 指向胜出那次的目录。
全部失败时，简介写「无胜出尝试，回到基线」，结论说明放弃原因和下一步；指标与输出目录
可引用已有的基线记录，缺少时填 `—`，不要编造胜出结果。快速迭代中的总结单独提交。
比较性扫描没有唯一赢家时，简介写比较范围和最终保留的设置，指标列汇总关键结果，
结论说明取舍及不确定性，输出目录指向本组实际汇总目录；不因某项均值略高就宣称全面最优。
本地合并、远端推送及最终合并提交 ID 在交接时分别汇报，流程见 `running-experiments-on-branches`。

## 关于格式

上面的列和文件名是模板。项目已经在用别的记录方式（自己的表格）就跟着它走，
别为了统一格式改动既有记录。但仍需记录运行前的计划、运行后的结果，并能区分未完成、
保留、放弃、崩溃和超时等状态，以便按对应流程恢复。
