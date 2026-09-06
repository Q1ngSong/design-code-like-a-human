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
    记录    experiments/ablation_study/lora_rank.csv

带上章节那一层是为了防撞名——`main_results/baseline` 和 `badcases/baseline`
是两组不同的实验。**三处都带**:记录的路径照抄输出目录去掉 `runs/` 和叶子,
和 stash message 是同一条规则。CSV 入库了,两组 `baseline` 写进同一个文件
就是真实的合并冲突。

**「一组」有多大、要不要新开分支，你自己判断。** 判据是：这些实验会不会
放在一起比较。几次相关的调参是一组，换个方向就该另起一组。

开分支的第一个 commit 写清这组要回答什么：

```
exp: 开一组 —— LoRA rank 扫描

要回答:rank 取多少能补上 main_results 里的 0.3 分差距
计划:从当前 4 开始往上试,过拟合即止
```

## commit 的粒度是一次决策，不是一次运行

**逐次自适应调参** —— 上次结果决定下次试什么。一次一个 commit：

```
exp: rank8_lr1e-4_round1 —— keep
exp: rank16_lr1e-4_round1 —— keep
exp: rank32_lr1e-4_round1 —— discard
```

**第一行只要 task 名和一个词的结果。** task 名是三个月后找回这次代码的唯一线索；
那个词让 `git log --oneline` 扫一眼就知道哪次赢了。为什么试、指标多少、输出在哪，
CSV 那行里有，和代码在同一个 commit 里，第一行不再抄。

**正文留给决策。** 放弃一个方向、人工改判、收尾定配置——这些是决策不是数据，
理由写进 commit 正文（`git commit -m "第一行" -m "正文"`），`git log` 读下来
就是决策链。和 CSV `结论` 列是同一段话，两处都有：CSV 是表，git log 是叙事。

**脚本批量扫** —— 一次 `for rank in [4,8,16,32]` 全跑完。这是**一个决策**,
一个 commit 就够，不要假装成四次。message 把四个 task 名都列上，
将来 grep 任何一个都能找到：

```
exp: rank4 rank8 rank16 rank32 —— 定在 16
```

**一次决策一个 commit，代码和 CSV 那行一起：**

```bash
# 跑完，CSV 追加一行，然后：
git add train.py experiments/ablation_study/lora_rank.csv
git commit -m "exp: rank8_lr1e-4_round1 —— keep"
```

找回来：`git log --all --grep=rank8_lr1e-4_round1 --source`，`%S` 列就是它在哪条分支。
顺序是：跑完 → 写 CSV 行（`task` 用输出目录的叶子名，其余列见
`recording-experiment-results`）→ 一个 commit。做完工作区是干净的。

## 调优期：快速迭代模式

上面的粒度是**构建期**的——有人在场，每一步都是和人一起做的决策，
失败留在分支上给人看。

**快速迭代由你开启、由你停止。** 你说"开始迭代"，agent 进入这个模式，
无人交互地跑，直到你叫停。前提是有能跑的基线和一个指标——否则每次尝试
没有东西可比。开启之后什么都能改——学习率、层数、换一种 attention、
重写数据管线——不分参数和架构，一夜能跑几十上百次。每次失败留一个 commit，
分支就成了一百格的废墟，理解负担比失败本身还重。所以：

```
开跑前 → grep "^<task>," experiments/<section>/<setting>.csv   # 本组试过就换 task
       → CSV 追加一行：task、简介 填好，指标、结论 留空        # 没试过才落盘意图
改代码 → 审计（`--base HEAD`，圈出这次的改动）→ 跑
  变好了 → CSV 那行补上 指标，结论 = keep
           git add -A && git commit -m "exp: lr0.04_bs4_round1 —— keep"
  没变好 → CSV 那行补上 指标，结论 = discard
           git add experiments/ablation_study/lora_rank.csv && git commit -m "record: lr0.04_bs4_round1 discard"
           git stash push -u -m "ablation_study/lora_rank/lr0.04_bs4_round1"
           # 失败的改动（含新建文件）进 stash，工作区回到起点；message = 输出目录去掉 runs/
```

**每一步归哪个技能管——按名字调，不靠它自己撞上来。**

| 步骤 | 调谁 | 它管什么 |
|---|---|---|
| CSV 追加 / 补齐 | `recording-experiment-results` | 列的含义、失败和崩溃怎么记 |
| 改代码 | `writing-minimal-code` | 四道闸门；新函数的 docstring 转 `writing-python-comments` |
| 改动会写盘 | `saving-experiment-outputs` | 输出存哪；不写盘的尝试不用调 |
| 审计 | `auditing-code-comments` | 告警怎么处置、R3/D1/C1 哪些要判断 |

这些技能的 description 也会按情境自动触发，那是兜底；循环里以这张表为准，
每轮都调——它们的内容不在本技能里复制一遍，要用就调。

**跑前先写半行 CSV。** `task` 和 `简介` 跑之前就知道，先落盘；`指标` 和 `结论`
跑完再填。这样任何时刻工作区里都有「正在试什么、为什么」，不靠对话记忆。

**跑完再 commit，不是跑前。** 尝试在工作区里跑，成了才成为 commit。所以不需要
先 commit、不需要 `HEAD~1`、不需要 `reset --hard`——没有任何一步会退历史或抹工作区。

**discard 时 CSV 先 commit，代码后 stash，顺序不能反。** 反了 CSV 行会跟着代码一起
进 stash，分支上就没有这次的记录了。keep 时一起 commit 没有这个问题。

**`stash push -u` 是先存档再清空，一条命令。** 它把工作区的改动（`-u` 连新建的
文件一起）存成一个 commit 挂在 `refs/stash` 上，再把工作区清回 HEAD。存不成就
不会清。message 照抄输出目录去掉 `runs/`，CSV 的 `输出目录` 列就是钥匙——
stash 是栈，同名不覆盖，两组实验各有一个 `lr0.04` 也不撞。

找回：`git stash list | grep <路径>` 定位，`git stash show -p stash@{n}` 看 diff。
**永远按名字 grep，不写死下标**——每 push 一次，所有旧条目的下标加一。
循环里只用 `push`；`pop`、`drop`、`clear` 是破坏性的，不用。
默认 `git gc` 不清 stash（实测 120 天的照样在），显式 `reflog expire` 才会。

存储不是问题：stash 和 commit 一样是压缩快照，实测 28KB 的 `train.py` 存 100 次，
gc 之后 `.git` 只涨 124KB，一个 50M 参数的 fp16 checkpoint 抵八百夜。

**审计放在跑之前，用 `--base HEAD`。** 那时这次的改动还没 commit，`--base HEAD`
把落在改动上的告警（改了的函数、新文件、改动文件里的模块级语句）标成
`changed=true`，只看这些；D3（写死的输出路径）在烧
GPU 之前就能抓到。C1 会报这次改了的函数——函数体动了就报，改个常量也报——
那是预期，快速迭代里不为它补 `变更:` 行；C1 只在合并前 `--base main` 那一遍才该认真看。

这个模式下分支上没有失败的代码：赢家是 `exp:`（代码和 CSV 行在一起），
输家只剩一行 `record:`。失败的经验在两处：CSV 一行（试了什么、得了多少、
为什么弃）和 stash 一条（当时的完整改动）。
合回主分支时 CSV 跟着 squash 进去，主分支照样知道排除过什么。

**跑崩了、跑超了、跑过了——三条照 autoresearch 的做法。**

- **崩溃**（OOM、NaN、栈回溯）：先看日志尾部。是 typo、漏 import 这种笨错，
  修了直接再跑一次——还没 commit，工作区改就是；修两次还崩就当想法不行——走 discard
  那条路（CSV、commit、stash），CSV `结论` 写 `crash：崩在哪一步、什么原因`。
  不要为一个想法修第三次。
- **超时**：第一轮跑的是基线，记下它用了多久。之后单次运行超过**基线两倍**
  就 kill 掉，当 discard 处理，`结论` 写 `timeout`。autoresearch 的规矩是
  5 分钟预算、10 分钟 kill，比例就是这个；我们不知道你的项目该跑多久，
  但第一轮之后 agent 知道。
- **去重**：在追加半行**之前**查，`grep "^<task>," experiments/<section>/<setting>.csv`。
  顺序反了会查到自己刚写的半行，永远「试过」。只查本组这一个文件——
  `-r experiments/` 会把别的组同名 task 也算上，同名不同组是两次实验不是重复。
  命中但 `结论` 列为空，是上次没跑完留下的半行，不是试过。
  试过的不再试——压缩之后最容易犯的就是这条，CSV 尾部就是记忆。

驱动层（`program.md` 之类）自己定了超时或重试策略的，以它为准；
这三条是没人定时的默认。

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
CSV `结论` 列和 `record:` commit 的正文，写的是整个方向为什么不行，不是最后一次本身：

      lr↑ 放弃（0.04/0.08/0.16，最好 1.003 仍劣于基线 0.998）——
      学习率已在稳定边界，再推只会发散

      git commit -m "record: lr0.16_bs4_round1 discard" -m "lr↑ 放弃（0.04/0.08/0.16……）—— 学习率已在稳定边界，再推只会发散"

三行 discard 各写各的，回头只知道三次都不行，不知道这个方向已经判死，
下一夜的 agent 会把同一条死路再走一遍。

为了让同方向的行能对上，`简介` 以方向开头：`lr↑: 0.08，上次 0.04 无效再推一档`。
同前缀的行连着看，趋势就在眼前。

**人工改判：指标说 discard，你觉得它才是对的。** 指标差一点但曲线更稳、
代码更简单、在另一个指标上更好——这种权衡机器做不了，你做。想要哪次就取回来：

    git stash list | grep <路径>       找到它现在的下标
    git stash apply stash@{n}          把那次的改动叠到现在的工作区

**apply 出来的是「那次的改动 + 后来所有赢家」的组合，不是那次实验本身。**
尖端一直在动，碰同一处会冲突，手动解；不冲突也不等于当时的结果还成立。
所以取回之后**当一次新尝试跑**：CSV 追加一行，`简介` 写「人工改判取回 <task>」，
跑完按结果 keep 或 discard。原来那行不改——它记的是当时的结果，是对的。

stash 里没有的话这一步做不了：`fatal: bad revision`。

**架构改动也走这个循环。** 失败的 diff 在 stash 里，清掉不丢东西。
"架构失败的经验更值钱"是真的，但值钱的是那份 diff 和那行方向级结论，
不是分支上多一个 commit。快速迭代里不区分参数和结构。

**开启时落一个标记，停止时删掉。** 模式不能只活在对话里——context 一压缩
就没了，凌晨三点 agent 会重新去问人。开启时：

    git check-ignore -q runs/ || echo "runs/ 没被 git 忽略，先补 .gitignore"   # output_roots 里每个都查
    mkdir -p .codegraph
    [ -f .codegraph/.gitignore ] || echo '*' > .codegraph/.gitignore
    git branch --show-current > .codegraph/unattended

第一行不能省：输出区没被 git 忽略，keep 的 `git add -A` 会把 checkpoint 提交进库，
discard 的 `stash push -u` 会把整个 `runs/` 从磁盘收走。D2 在跑前审计里报得出来，
但它是文件级的，永远不是 `changed=true`，无人值守时没人看它；这一刻你还在场，
补 `.gitignore` 是构建期的事。第三行是给没装 codegraph 的项目的:`.codegraph/` 下的东西不被忽略,第一次 discard 的
`stash push -u` 就会把哨兵当未跟踪文件收走,模式静默翻回有人在场。装了 codegraph
的话它自己会写这个文件,判断一下不覆盖。

**只在用户明确说要离开、让你自己跑时才落这个文件**——「开始迭代」「我去睡了」
「跑一夜」算；「继续」「好」「行」不算，那是对上一步的回应，不是授权离场。
拿不准就问一句「要我无人值守跑吗」，这一问值得。停止时 `rm .codegraph/unattended`，
再跑一次 `refresh.py`——`audit.json` 的 `unattended` 是审计那一刻的快照，不会自己翻回 false。
**文件存在且不超过 24 小时就是无人值守**；
`refresh.py` 把它写进 `audit.json` 的 `unattended` 字段，hook 在每次会话开始
（含压缩之后）打一行。其他技能看这两处，不自己推断。24 小时照 ARIS 的规矩：
忘了删的哨兵不该在一周后还生效。文件里那行分支名是给人看的。

**迭代期间不切回构建期。** 模式由谁在场决定，不由改动类型决定：
无人交互就是快速迭代——其他技能里说的「无人值守」指的就是这个阶段——
一直到你叫停；你回来了、开始一起做决策了，
就自动回到构建期，每个决策一个 commit。中途不切换——切换的判断本身
就是一次交互，而迭代期间没有人可交互。

**无人值守期间不交出 turn。** harness 没有「循环模式」：agent 一直调工具，
turn 就一直不结束；哪一刻输出了一段没有后续动作的总结，turn 结束，CLI 等人，
等到天亮。所以每一步都以工具调用收尾，要说的写进 commit message 或 CSV。
不许「问一句，没人答就继续」——要么阻塞地问（有人时），要么不问。

**压缩之后从盘上恢复。** 状态全在 git 里，不需要别的状态文件：
`git branch --show-current` 是在哪，`git log -3 --oneline` 是走到哪，
`experiments/<路径>.csv` 尾部是试过什么，`git stash list` 是失败档案。
第一步 `cat .codegraph/unattended`——在、且没过 24 小时，就还在无人值守
（Claude Code 的 hook 也会说这一句；Codex 没有 hook，自己看）。然后读上面四处续上。

工作区里的改动归谁，看 CSV 尾行和它的收尾做没做完：

- `结论` 为空：崩在一次尝试中间，改动属于它。输出目录里指标齐了就照常补齐、
  keep 或 discard；没跑完就按 discard 走——`结论` 写 `crash：崩在哪一步`，
  提交 CSV，`git stash push -u`。
- `结论` 非空但收尾没做完——keep 的 `git log --oneline --grep "<task>"` 找不到
  commit，discard/crash 的 `git stash list | grep "<task>"` 找不到条目：崩在填结论和
  收尾之间，改动仍属于那次，把剩下的半段做完（keep：`git add -A && git commit`；
  discard：提交 CSV、stash）。
- 两处都齐了，工作区还有改动，才是无关改动，按 `recording-experiment-results`
  说的提交成 `chore:`。

**前两种不要当成无关改动提交成 `chore:`**：那会把半成品推成基线，之后每次
discard 的 stash 都回不到最后一次 keep。

## 合并前：把配置定在胜出的那次

**这一步最容易漏。** squash 合的是分支**最终状态**，不是最好的那次。
你跑完 rank=32，配置就停在 32;直接合过去，主分支带着一个已知过拟合的值。
**全部失败时也一样**——尖端是最后那次失败的代码，直接合就把无效实现带进主分支。

所以收尾时把配置改到该合的状态：胜出那次，或全失败时回到基线。CSV 末尾的
总结行和它一起提交：最后一次还没提交就一个 commit 装下；已经提交了就再提交
一次，不 amend。理由进正文：

```bash
# 有赢家:把 config 改回 rank=16;CSV 末尾写结论
git commit -m "exp: 收尾 —— 定在 rank=16" -m "16 之后收益递减,32 过拟合"

# 全失败:git checkout main -- <配置文件>,回到基线;CSV 末尾写结论
git commit -m "exp: 收尾 —— 全部无效,配置回基线" -m "rank 8/16 都劣于 4,方向放弃"
```

快速迭代模式下配置不用改——失败的都 stash 了，尖端要么是指标最优那次，
要么是你人工改判取回的那次，要么（全部失败时）就是基线。但两件事要做：
对着 CSV 核一遍尖端确实是你要的那次，有人工改判的尤其要核；然后 CSV 末尾
写这组的总结论——胜出配置、为什么、下一步——再提交一次，理由进正文。循环里
每次都是当场提交的，胜者也往往不是最后一次（尾端多半是一条 discard 记录），
没有可以搭的 commit；不 amend。

收尾前跑一次差异审阅，看整条分支相对主分支引入了什么：

    python3 <插件根>/scripts/refresh.py . --base main --json

「本次改动」段里的东西是这组实验带进来的，合并前该清的清。「存量」里只过一眼
R1：这条分支删掉的调用点会让别处没动的函数新报 R1，那也是这次带进来的，只是
打标抓不到它；其余存量不归这次管。

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

各组写各自的 CSV（`experiments/ablation_study/lora_rank.csv` /
`experiments/badcases/guidance_scale.csv`——路径照抄输出目录,所以不同组不可能同名）。
一组一个分支、一个 worktree 一个分支——git 不允许两个 worktree 检出同一分支——
所以两边永远写的是不同的文件，合并零冲突。要总表就把 `experiments/**/*.csv`
全读进来。同一个配置文件两边都改也没事，只要改的不是同一行。

**删 worktree 之前先把 `runs/` 挪走。** `git worktree remove` 连目录一起删，
`runs/` 不入库没有副本，输出会随目录一起消失。`experiments/` 入库了、在分支上，
不受影响。

## 跑砸了的分支照样合

结论是「这条路不通」的，**也要 squash 合回主分支**,message 写清为什么不通：

```
exp(ablation_study): attention_dropout —— 无效,不再尝试

试了 0.1/0.2/0.3,FID 全部劣于不加。注意力图本就稀疏,再 dropout 是伤害。
```

只合成功的实验，主分支的历史就是假的：三个月后看到一片「有效」,
不知道排除过什么，于是重新试一遍死路。长程自动任务里这个损失最大，
没人凭记忆兜底。

合之前先走「合并前」那步把配置回到基线——否则 squash 带进主分支的是最后那次
失败的代码。合进去的 diff 只有 CSV 那几行，那正是该留下的东西。

快速迭代模式下失败不在分支的代码历史里，但 `record:` commit 和 CSV 随 squash
进主分支——排除过什么，主分支照样知道。
