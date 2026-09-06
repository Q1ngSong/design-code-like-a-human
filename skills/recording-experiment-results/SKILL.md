---
name: recording-experiment-results
description: Use when an experiment run finishes, before starting the next one - append a row to this round's CSV recording what was tried, the metric, and the conclusion, so twenty rounds later the results can still be compared instead of living only in scrollback. 触发场景:实验跑完了、记录结果、实验记录、汇总一下结果、这组实验的结论、上次那个实验结果呢。
---

# 记录实验结果

**开跑前记录计划，运行结束后补齐结果，再开始下一次。** 每次尝试使用同一行记录，
避免只在终端或对话中保留实验信息。

## 一组实验一个 CSV

路径照抄输出目录去掉 `runs/` 和叶子 —— 输出在 `runs/ablation_study/lora_rank/{task}/`，
记录就是 `experiments/ablation_study/lora_rank.csv`，
一行一次实验：

```csv
task,简介,指标,结论,输出目录
rank8_lr1e-4,"rank 4→8，上轮已收敛未过拟合",FID 12.3 / CLIP 0.281,keep：有效，继续比较 rank16,runs/ablation_study/lora_rank/rank8_lr1e-4
rank16_lr1e-4,继续加到 16 看还有没有收益,FID 11.9 / CLIP 0.283,keep：指标改善，继续比较 rank32,runs/ablation_study/lora_rank/rank16_lr1e-4
rank32_lr1e-4,再翻倍确认拐点,FID 14.1 / CLIP 0.271,"discard：过拟合，回退到 rank16",runs/ablation_study/lora_rank/rank32_lr1e-4
```

按标准 CSV 格式读写；字段含英文逗号、换行或双引号时，正确引用和转义。

`experiments/` **入库**。记录不是产物，是结论——它要随仓库走、要在 squash 时
进主分支、要在 worktree 删掉之后还在。`runs/` 才是产物，那个不入库。

| 列 | 写什么 |
|---|---|
| `task` | **与输出目录最后一级的名称一致**（命名方式见 `saving-experiment-outputs`） |
| `简介` | **为什么试这个**，不是「跑了个实验」 |
| `指标` | 你关注的那几个数，自由格式（`FID 12.3 / CLIP 0.281`） |
| `结论` | 以 keep / discard / crash / timeout 开头，说明原因和下一步。构建期也用这些状态，便于恢复时判断如何收尾 |
| `输出目录` | 本次尝试的实际输出路径；`runs/` 是示例根目录，项目已有其他路径时沿用 |

`task` 是本次实验设置的缩写，用于关联 CSV 记录、输出目录和 commit message。
三处使用同一个名称，不要另起简称，以免回查时需要逐一对应。

**用 task 名查找对应版本。** 构建期和快速迭代 keep 的代码在实验分支的 commit 中，
快速迭代 discard、crash、timeout 的代码改动在 stash 中。例如：

    git log --all --fixed-strings --grep=rank8_lr1e-4 --oneline

同名 task 可能出现在不同组，需核对提交中的 CSV 路径和记录。stash 按完整组路径与 task 名
定位，取回方式见 `running-experiments-on-branches`。名称用于检索，不代替版本核对；
重跑还需要对应代码、完整配置和运行参数。固定参数不要只依赖目录名推断。

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
**不要 amend 进上一个 commit**——那个 commit 的 message 是上一次实验的记录，
塞进无关改动就说不清那次跑的是什么了。单独提交，message 写清里面是什么、
说明它不是实验，例如 `chore: 任务开始前整理 README`。
用户在场时先确认是否提交，避免提交用户尚未完成的工作。无人值守时，确认与实验无关后
单独提交为 `chore:`，并在 message 中列清内容。模式判定见 `auditing-code-comments`。

**运行结束到提交之间不要再修改实验代码**，以免提交内容与实际运行的代码不一致。
如果确实修改了，在 `结论` 末尾注明「跑后又改了代码，此行不可复现」。

**每组实验使用一个 CSV 文件。** 需要总表时，汇总 `experiments/**/*.csv`。

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

这组收尾时（合并前）在 CSV 末尾追加一行总结，随最后一次的 commit 一起提交；
最后一次已经提交了就再提交一次，不 amend（见 `running-experiments-on-branches`
的合并前一节）。这一行五列这样填：
`task` 写 `summary`，`简介` 写胜出的配置，`指标` 写它的指标，
`结论` 写为什么胜出、下一轮打算做什么，`输出目录` 指向胜出那次的目录。
全部失败时，简介写「无胜出尝试，回到基线」，结论说明放弃原因和下一步；指标与输出目录
可引用已有的基线记录，缺少时填 `—`，不要编造胜出结果。快速迭代中的总结单独提交。

## 关于格式

上面的列和文件名是模板。项目已经在用别的记录方式（自己的表格）就跟着它走，
别为了统一格式改动既有记录。但仍需记录运行前的计划、运行后的结果，并能区分未完成、
保留、放弃、崩溃和超时等状态，以便按对应流程恢复。
