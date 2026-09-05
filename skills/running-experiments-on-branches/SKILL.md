---
name: running-experiments-on-branches
description: Use when starting a group of experiments or tuning parameters - open a branch instead of running on main, pin the winning config before merging, and squash back so main's log reads as an experiment index rather than dozens of tuning commits. 触发场景:调参、跑实验、做消融、开分支、并行跑几组实验、主分支 commit 太乱、实验怎么用 git 管。
---

# 实验跑在分支上

**调参和实验不在主分支上跑。** 一组实验会产生十几次「改个数、跑一遍」的提交，
全堆进主分支，`git log` 就成了噪声，回头找不到哪次是真正的功能改动。

要保留的就这一条。下面的做法是模板，项目有自己的习惯就跟着它走。

## 一组实验一个分支

```bash
git checkout -b exp/ablation_study/lora_rank
```

分支名跟着输出目录走，三者是同一组实验的三个视图：

    分支    exp/ablation_study/lora_rank
    输出    runs/ablation_study/lora_rank/{task}/
    记录    experiments/lora_rank.csv

带上章节那一层是为了防撞名——`main_results/baseline` 和 `badcases/baseline`
是两组不同的实验。

**「一组」有多大、要不要新开分支，你自己判断。** 判据是：这些实验会不会
放在一起比较。几次相关的调参是一组，换个方向就该另起一组。

开分支的第一个 commit 写清这组要回答什么：

```
exp: 开一组 —— LoRA rank 扫描

要回答:rank 取多少能补上 main_results 里的 0.3 分差距
计划:从当前 4 开始往上试,过拟合即止
```

## commit 的粒度是一次决策，不是一次运行

**逐次自适应调参** —— 上次结果决定下次试什么。一次一个 commit,
message 里写清为什么试这个值，那句话就是推理链条：

```
exp: rank=8 → FID 12.3 —— 有效,+0.4 分
exp: rank=16 → FID 11.9 —— 有效但收益递减
exp: rank=32 → FID 14.1 —— 过拟合,回退
```

**脚本批量扫** —— 一次 `for rank in [4,8,16,32]` 全跑完。这是**一个决策**,
一个 commit 就够，不要假装成四次：

```
exp: 扫描 rank 4/8/16/32,定在 16
```

每次 commit 前先按 `recording-experiment-results` 往这组的 CSV 里补一行，
`task` 列用输出目录的叶子名（`rank8_lr1e-4_round1` 这种），和 `runs/` 对得上。

**`git 版本` 那列在 commit 之后填。** 提交号要提交完才有：

```bash
git commit -m "exp: rank=8 → FID 12.3 —— 有效，+0.4 分"
git rev-parse --short HEAD          # 把它写进 CSV 这一行的 git 版本列
```

顺序是：跑完 → 写 CSV 前五列 → commit → 回填提交号。
提交号指向的正是产生这一行结果的那份代码，`git checkout <提交号>` 能重跑。

## 调优期：快速迭代模式

上面的粒度是**构建期**的——有人在场，每一步都是和人一起做的决策，
失败留在分支上给人看。

**快速迭代由你开启、由你停止。** 你说"开始迭代"，agent 进入这个模式，
无人交互地跑，直到你叫停。前提是有能跑的基线和一个指标——否则每次尝试
没有东西可比。开启之后什么都能改——学习率、层数、换一种 attention、
重写数据管线——不分参数和架构，一夜能跑几十上百次。每次失败留一个 commit，
分支就成了一百格的废墟，理解负担比失败本身还重。所以：

```
改代码 → git commit -m "exp: lr 0.04" → 跑
  变好了 → 追加 CSV 行（结论 keep，提交号 = 刚才那个），分支前进
  没变好 → h=$(git rev-parse --short HEAD)
           git update-ref refs/tried/$h HEAD        # 钉住
           git reset --hard HEAD~1                  # 清掉
           追加 CSV 行（结论 discard，提交号 = $h）
```

**先 commit 再跑**，跑之前就有提交号，CSV 的 `git 版本` 列有东西可填。

**CSV 追加就行，不 commit。** `experiments/` 和 `runs/` 一样不入库，
`git reset --hard` 不碰 untracked 文件，上一次失败的那行不会被下一次 reset 冲走。
（项目自己把记录文件纳入了版本控制的，每追加一行就单独 commit 一次，
否则会被 reset 抹掉。）

**`update-ref` 那行不能省。** 裸 reset 之后那个 commit 没有任何 ref 指向它，
30 天后 gc 掉，CSV 里的提交号变成悬空指针：你知道「试过 lr 0.04 不行」，
看不到当时改的是哪几行。**CSV 里的提交号能用，全靠这一行钉着它**——
`git show refs/tried/<提交号>` 就是那次的完整代码。不钉就别填提交号，
填了也是假的。

存储不是问题：实测 28KB 的 `train.py` 钉 100 次，`git gc` 之后 `.git` 只涨 124KB，
一个 50M 参数的 fp16 checkpoint 抵八百夜。gc 之前每次约 24KB（git 存的是
整个文件的压缩快照，不是 diff），git 会自己在几千个松散对象时打包，不用管。`refs/tried/*` 让它永久可达，又不出现在 `git branch`
和 `git log` 里，零噪音。差一点的那次要拿回来和别的组合，
`git cherry-pick refs/tried/<提交号>` 就行——没有这个 ref 做不到。

**`--hard` 不能省。** 裸 `git reset HEAD~1` 只挪指针，失败的改动留在工作区，
下一轮就叠在它上面改，失败的代码混进下一次实验。

这个模式下分支上只有赢家，一条直线。失败的经验在两处：CSV 一行（试了什么、
得了多少、为什么弃）和 `refs/tried/` 一个 commit（当时的完整代码）。
两处都不在 git 历史里——CSV 不入库，`refs/tried` 不进 log——所以合回主分支时
主分支**看不到**排除过什么，要看得去 `experiments/` 翻 CSV。这是不入库的代价。

**每次 discard 之后，先问这个方向还要不要继续。** 快速迭代最容易犯的错是死磕：
lr 0.04 差了推到 0.08，还差推到 0.16，一路推下去。什么时候停，你自己判断，
依据是趋势不是次数：

- 指标在往坏走，还是在基线附近抖？往坏走是方向错；抖是噪声，噪声还可以再看一次
- 每次的差距在缩还是在扩？收益递减到接近零，方向已经榨干
- 说得出为什么不行吗？有机制上的解释（学习率到了稳定边界）就该停；
  说不出来是还没理解，值得换个角度再试一次，而不是再推一档
- 别的方向还有多少没试？一个方向吃掉一夜三分之一的预算，就该问值不值

连续三次还没改善，是该认真问上面这几条的时刻，不是自动停的信号。

**放弃一个方向时，必须写方向级的结论。** 这条不是判断，是规矩。那次 discard 的
CSV `结论` 列写的是整个方向为什么不行，不是最后一次本身：

      lr↑ 放弃（0.04/0.08/0.16，最好 1.003 仍劣于基线 0.998）——
      学习率已在稳定边界，再推只会发散

三行 discard 各写各的，回头只知道三次都不行，不知道这个方向已经判死，
下一夜的 agent 会把同一条死路再走一遍。

为了让同方向的行能对上，`简介` 以方向开头：`lr↑: 0.08，上次 0.04 无效再推一档`。
同前缀的行连着看，趋势就在眼前。

**架构改动也走这个循环。** 失败的 diff 被 `refs/tried` 钉着，reset 掉不丢东西。
"架构失败的经验更值钱"是真的，但值钱的是那份 diff 和那行方向级结论，
不是分支上多一个 commit。快速迭代里不区分参数和结构。

**迭代期间不切回构建期。** 模式由谁在场决定，不由改动类型决定：
无人交互就是快速迭代，一直到你叫停；你回来了、开始一起做决策了，
就自动回到构建期，每个决策一个 commit。中途不切换——切换的判断本身
就是一次交互，而迭代期间没有人可交互。

## 合并前：把配置定在胜出的那次

**这一步最容易漏。** squash 合的是分支**最终状态**，不是最好的那次。
你跑完 rank=32，配置就停在 32;直接合过去，主分支带着一个已知过拟合的值。

所以收尾要有一个 commit:

```bash
# 把 config 改回 rank=16,CSV 末尾写结论
git commit -m "exp: 收尾 —— 定在 rank=16,写结论"
```

## 合回主分支：压成一个 commit

```bash
git checkout main
git merge --squash exp/ablation_study/lora_rank
git commit
```

主分支上一组实验一行：

```
exp(ablation_study): lora_rank —— rank16 最优,FID 11.9
exp(badcases): guidance_scale —— CFG 5.0 把崩坏率从 34% 降到 18%
```

message 里带上结论和数字，`git log` 读下来就是实验目录。
细节历史留在分支上，**分支不删** —— 想知道「为什么最后定 16」就切过去看。


## 并行跑多组：用 worktree

```bash
git worktree add -b exp/badcases/guidance_scale ../proj-guidance
```

两组实验各占一个目录、各自的分支，互不干扰 —— 不用来回 `checkout`,
两边的实验可以同时跑。

各组写各自的 CSV(`experiments/lora_rank.csv` / `guidance_scale.csv`),
所以合并时不冲突。同一个配置文件两边都改也没事，只要改的不是同一行。

## 跑砸了的分支照样合

结论是「这条路不通」的，**也要 squash 合回主分支**,message 写清为什么不通：

```
exp(ablation_study): attention_dropout —— 无效,不再尝试

试了 0.1/0.2/0.3,FID 全部劣于不加。注意力图本就稀疏,再 dropout 是伤害。
```

只合成功的实验，主分支的历史就是假的：三个月后看到一片「有效」,
不知道排除过什么，于是重新试一遍死路。长程自动任务里这个损失最大，
没人凭记忆兜底。

快速迭代模式下失败既不在分支历史里，也不随 squash 进主分支（CSV 不入库）。
排除过什么只在 `experiments/` 的 CSV 里，主分支的 log 只有赢家。
