---
name: recording-experiment-results
description: Use when an experiment run finishes, before starting the next one - append a row to this round's CSV recording what was tried, the metric, and the conclusion, so twenty rounds later the results can still be compared instead of living only in scrollback. 触发场景:实验跑完了、记录结果、实验记录、汇总一下结果、这组实验的结论、上次那个实验结果呢。
---

# 记录实验结果

**一次实验跑完，先记一行，再跑下一次。** 不记就跑下一次，二十轮之后
只剩一堆目录名和翻不动的终端输出。

## 一组实验一个 CSV

路径照抄输出目录去掉 `runs/` 和叶子 —— 输出在 `runs/ablation_study/lora_rank/{task}/`，
记录就是 `experiments/ablation_study/lora_rank.csv`，
一行一次实验：

```csv
task,简介,指标,结论,输出目录
rank8_lr1e-4,"rank 4→8，上轮已收敛未过拟合",FID 12.3 / CLIP 0.281,有效 +0.4 分,runs/ablation_study/lora_rank/rank8_lr1e-4
rank16_lr1e-4,继续加到 16 看还有没有收益,FID 11.9 / CLIP 0.283,收益递减 +0.1 分,runs/ablation_study/lora_rank/rank16_lr1e-4
rank32_lr1e-4,再翻倍确认拐点,FID 14.1 / CLIP 0.271,"过拟合，回退",runs/ablation_study/lora_rank/rank32_lr1e-4
```

字段里有逗号就加双引号，标准 CSV 写法。

`experiments/` **入库**。记录不是产物，是结论——它要随仓库走、要在 squash 时
进主分支、要在 worktree 删掉之后还在。`runs/` 才是产物，那个不入库。

| 列 | 写什么 |
|---|---|
| `task` | **就用输出目录的叶子名**，`{参数}{值}{参数}{值}{参数}{值}......` 拼接 |
| `简介` | **为什么试这个**，不是「跑了个实验」 |
| `指标` | 你关注的那几个数，自由格式（`FID 12.3 / CLIP 0.281`） |
| `结论` | keep / discard / crash / timeout，加一句为什么、下一步做什么。构建期也用这套词——崩溃恢复靠它分支 |
| `输出目录` | `runs/` 下的路径，把这一行和实际产物钉在一起 |

`task` 一列三用：这次实验设置的缩写、CSV 和 `runs/` 之间的连接键、
**commit message 的开头**。所以直接用叶子目录名，别另起一个短名字——
三套命名对不上，回头就得靠人脑映射。

    rank8_lr1e-4_round1     ← 一眼看出 rank 8、学习率 1e-4、第1轮(也可以r8l4r1等更短的缩写，来快速定位)
    runs/ablation_study/lora_rank/rank8_lr1e-4_round1/

只写**这一组里变化的**参数。不变的那些属于上一层（`lora_rank` 这个 setting
本身就说明了在调 rank），塞进叶子只会让每个名字都又长又一样。
如果一组里有五六个参数在动，那多半不是一组实验，该拆。

**回到当时的代码靠 task 名，不靠提交号。** commit message 含 task 名
（见 `running-experiments-on-branches`），所以：

    git log --all --grep=rank8_lr1e-4_round1 --source    找到 commit，%S 列是它在哪条分支
    git stash list | grep ablation_study/lora_rank/rank8_lr1e-4_round1    快速迭代里 discard 掉的那次
    git stash show -p stash@{n}                                            ↑ message = 输出目录去掉 runs/

参数在叶子目录名和简介里，代码在 message 带这个名字的 commit 里，两样凑齐才能复现。
没有它，三个月后你只知道「rank8 得了 12.3」，不知道那时的 loss 函数长什么样。

也正因为每次实验的代码都能这样找回来，改既有函数才不那么可怕——
改坏了能定位到是哪一次、能回到那个 commit 重跑（见 `writing-minimal-code`）。

**开始这次实验之前，工作区要干净**——上一次的改动全部已提交，别混进来：

    git status --porcelain     有输出就说明上一次还没提交完

本次的改动**跑完再提交**，message 含 task 名。构建期和快速迭代 keep 时，
CSV 那行和代码在同一个 commit 里；快速迭代 discard 时 CSV 行单独 commit、代码进
stash——两种情况「跑过的代码」都能按 task 名找回。
顺序是：确认干净 → 写 CSV 半行（task、简介）→ 改代码 → 跑 → 补齐 CSV 行 → 一个 commit
（见 `running-experiments-on-branches`）。做完工作区是干净的。

**开始前工作区不干净怎么办。** 先看是什么，别闭着眼 `git add -A`：

    git status --porcelain
    git diff --stat

多半是人改了 README、改了配置、或上一次跑到一半崩了留下的东西。先看本组 CSV
的尾行和它的收尾（`running-experiments-on-branches` 的恢复一节）：`结论` 为空，
或非空但对应的 keep commit / discard stash 还没出现，工作区的改动就是那次尝试的，
先把那次的 keep 或 discard 做完，而不是提交成 `chore:`，否则半成品成了基线。
两处都齐了，才是下面说的无关改动。
**不要 amend 进上一个 commit**——那个 commit 的 message 是上一次实验的记录，
塞进无关改动就说不清那次跑的是什么了。单独提交，message 写清里面是什么、
说明它不是实验：`chore: 任务开始前清理 —— README 改动、上次崩溃的半成品`。
有人在场时先问一句要不要提交，那可能是他改到一半的东西。无人值守（`audit.json` 的 `unattended` 为 true）时不问，直接按上面那条提交成 `chore:`，message 里列清是什么——人回来看 log 就知道开跑前工作区里有过什么。

**跑完到提交之间不要再改任何东西。** 改了，commit 里的代码就不是跑过的那份——
这时在 `结论` 列末尾注一句「跑后又改了代码，此行不可复现」。

**一组一个文件，不是一个全局表。** 一组一个分支、一个 worktree 一个分支，
两边永远写的是不同的文件，合并零冲突；要总表就把 `experiments/**/*.csv` 全读进来。

「一组」有多大由你判断 —— 几次相关的调参是一组，换个方向就该另起一组。
没有硬标准，判据是：这些实验会不会放在一起比较。

## 失败的也要记

跑砸了、结论是「这条路不通」——**照样记一行**，结论写清为什么不通。

只记成功的实验，记录就是假的：三个月后看到一片「有效」，不知道中间试错过什么，
于是重新试一遍已经排除过的方向。在长程自动任务里这个损失最大，
因为没人凭记忆兜底。

## 没跑完的也一样

上一节说的是「跑完了但结论是负面」。**中途挂掉是另一回事**——OOM、数据缺失、
loss 变 NaN、机器被抢占——处理方式一样,三件事都要做:

**记一行。** 结论写清挂在哪一步、什么原因:

    rank64,"显存上限试探",—,"OOM,step 3200 挂,batch 8 时显存不够",runs/.../rank64

指标列填 `—`,别留空:留空看着像忘了记,`—` 说明确实没有。

**半成品目录留着,并照常填进输出目录列。** 崩之前的部分往往就是证据 ——
loss 曲线到崩溃点为止已经能看出是发散还是显存问题。删掉就只剩一句
「OOM」,下次还得再撞一次才知道在哪一步。

**照常 commit。** 失败也是一次决策的结果,跳过 commit 就没有带这个 task 名的
commit 可找 —— 三个月后 CSV 里有这一行,git 里却对不上它跑的是什么代码。

**快速迭代里例外。** 上面三条是构建期的：崩溃的代码留在分支上，作为一次决策的记录。
快速迭代里崩溃走 discard 那条路——CSV、commit、stash——崩溃的代码不留在分支上，
只留在 stash 和 CSV 那一行里。见 `running-experiments-on-branches`。

## 什么时候写

**跑前写 `task` 和 `简介`，跑完写 `指标` 和 `结论`。** 前两列跑之前就知道，
先落盘，任何时刻都能看到「正在试什么、为什么」；后两列要等结果。

**后两列跑完立刻写，在决定下一步之前。** 顺序反了就会变成「先想下一步、
顺手补记录」，而补的记录一定是事后合理化，不是当时的判断。

这组收尾时（合并前）在 CSV 末尾追加一行总结，随最后一次的 commit 一起提交；
最后一次已经提交了就再提交一次，不 amend（见 `running-experiments-on-branches`
的合并前一节）。这一行五列这样填：
`task` 写 `summary`，`简介` 写胜出的配置，`指标` 写它的指标，
`结论` 写为什么胜出、下一轮打算做什么，`输出目录` 指向胜出那次的目录。

## 关于格式

上面的列和文件名是模板。项目已经在用别的记录方式（自己的表格）就跟着它走，
别为了统一去改人家的习惯。**要保留的是「跑完先记再跑下一次」这个习惯，
不是这几个列名。**
