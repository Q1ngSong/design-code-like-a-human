---
name: running-experiments-on-branches
description: Use when starting a group of experiments or tuning parameters - open a branch instead of running on main, pin the winning config before merging, and squash back so main's log reads as an experiment index rather than dozens of tuning commits. 触发场景:调参、跑实验、做消融、开分支、并行跑几组实验、主分支 commit 太乱、实验怎么用 git 管。
---

# 实验跑在分支上

**调参和实验不在主分支上跑。** 一组实验会产生十几次「改个数、跑一遍」的提交，
全堆进主分支，`git log` 就成了噪声，回头找不到哪次是真正的功能改动。

分支名和目录名是模板，项目已有命名习惯时沿用。下文的提交、存档和恢复顺序相互配套，
采用这套流程时需要一起遵守。

## 一组实验一个分支

```bash
git checkout -b exp/ablation_study/lora_rank
```

分支、输出目录和记录文件使用相同的实验组路径：

    分支    exp/ablation_study/lora_rank
    输出    runs/ablation_study/lora_rank/{task}/
    记录    experiments/ablation_study/lora_rank.csv

例如，`main_results/baseline` 和 `badcases/baseline` 是不同组，三处都保留章节名以免重名。
CSV 路径去掉输出根目录和最后一级 task 名，再加 `.csv`；stash message 则保留 task 名，
用于区分同组的不同尝试。

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

**提交标题包含 task 名和结果状态。** task 名用于查找对应尝试，状态便于浏览
`git log --oneline`。实验目的、指标和输出路径保存在 CSV 中，无需重复写入标题。

**在正文中说明决策理由。** 放弃一个方向、人工改判或收尾选定配置时，把理由同时写入
commit 正文和 CSV 的 `结论` 列。提交命令可写成 `git commit -m "第一行" -m "正文"`。

**脚本批量扫** —— 一次 `for rank in [4,8,16,32]` 全跑完。这是**一个决策**,
一个 commit 就够，不要假装成四次。message 把四个 task 名都列上，
将来 grep 任何一个都能找到：

```
exp: rank4 rank8 rank16 rank32 —— 定在 16
```

**一次决策一个 commit，代码和 CSV 那行一起：**

```bash
# 跑完后补齐开跑前写入的 CSV 记录，然后：
git add train.py experiments/ablation_study/lora_rank.csv
git commit -m "exp: rank8_lr1e-4_round1 —— keep"
```

顺序：确认工作区干净 → CSV 填写 `task`、`简介` → 改代码 → 运行 → 补齐 `指标`、`结论`
→ 提交代码和 CSV。完成后，工作区应恢复干净。

## 调优期：快速迭代模式

上面的提交方式用于**构建期**：用户参与每次决策，失败尝试的代码也提交到分支中，供用户审阅。

**快速迭代由用户开启和停止。** 用户要求「开始迭代」后，进入无人值守模式，直到用户叫停。
前提是已有可运行的基线和评价指标，用于比较每次尝试的结果。迭代可以调整参数，也可以
修改架构，例如更换 attention 或重写数据管线。连续尝试较多时，为每次失败提交代码会
增加分支历史的阅读负担，因此失败尝试只提交记录，将代码改动保存在 stash 中：

```
开跑前 → 在本组 CSV 中按 task 字段精确查找，先处理未完成的尝试
       → 新尝试追加一行：填写 task、简介、输出目录，指标、结论留空
改代码 → 审计（`--base HEAD`，圈出这次的改动）→ 跑
  变好了 → CSV 那行补上 指标，结论 = keep
           git add -A && git commit -m "exp: lr0.04_bs4_round1 —— keep"
  没变好 → CSV 那行补上 指标，结论 = discard
           git add experiments/ablation_study/lora_rank.csv
           git commit --only -m "record: lr0.04_bs4_round1 discard" -- experiments/ablation_study/lora_rank.csv
           git stash push -u -m "ablation_study/lora_rank/lr0.04_bs4_round1"
           # 失败的改动（含新建文件）进 stash，工作区回到起点；message = 输出目录去掉 runs/
```

**每轮按下表调用相应技能，具体要求见各技能。**

| 步骤 | 调谁 | 它管什么 |
|---|---|---|
| CSV 追加 / 补齐 | `recording-experiment-results` | 列的含义、失败和崩溃怎么记 |
| 改代码 | `writing-minimal-code` | 四道闸门；新函数的 docstring 转 `writing-python-comments` |
| 改动会写盘 | `saving-experiment-outputs` | 输出存哪；不写盘的尝试不用调 |
| 审计 | `auditing-code-comments` | 告警怎么处置、R3/D1/C1 哪些要判断 |

**跑前先写记录，跑完补齐结果。** `task`、`简介` 和输出目录在开跑前确定，先写入 CSV；
`指标` 和 `结论` 等结果出来后填写。这样恢复时能找到正在进行的尝试及其输出。

**运行结束后再提交。** 先在工作区运行本次改动，keep 时提交代码和记录，discard 时只提交
记录并保存代码改动到 stash。这套顺序不需要提前提交实验代码，也不需要使用 `HEAD~1`
或 `reset --hard` 回退。

**discard 时 CSV 先 commit，代码后 stash，顺序不能反。** 反了 CSV 行会跟着代码一起
进 stash，分支上就没有这次的记录了。keep 时一起 commit 没有这个问题。
示例用 `commit --only` 限定提交 CSV，避免把已暂存的失败代码一起提交。
提交记录前先确认是否有代码差异；若没有，在结论中注明「无代码差异，无需 stash」，
只提交记录。无改动时，stash 命令不会产生条目。

**`stash push -u` 先保存改动，再将工作区恢复到 HEAD。** `-u` 会同时保存未跟踪的新文件。
保存成功后才恢复工作区，最新条目由 `refs/stash` 引用。

stash message 使用输出目录去掉 `runs/` 后的路径，可根据 CSV 的 `输出目录` 列找到对应条目。
路径包含实验组名，因此不同组的同名 task 可以区分；同名 stash 条目也不会相互覆盖。

查找时用 `git stash list --format='%H %gs'`，核对包含完整组路径和 task 名的消息，取得
对应的对象 ID。用 `git stash show -p -u <对象ID>` 查看改动，`-u` 会显示存档中的新建文件。
不同 worktree 共用 stash 列表，其他尝试也会使下标变化，因此后续操作使用对象 ID，
不要保存 `stash@{n}` 下标。循环中用 `push` 保存；取回时用 `apply`，不用会移除条目的
`pop`、`drop`、`clear`。

**审计放在跑之前，用 `--base HEAD`。** 那时这次的改动还没 commit，`--base HEAD`
把落在改动上的告警（改了的函数、新文件、改动文件里的模块级语句）标成
`changed=true`，只看这些；D3（写死的输出路径）在烧
GPU 之前就能抓到。C1 会报这次改了的函数——函数体动了就报，改个常量也报——
那是预期，快速迭代里不为它补 `变更:` 行；C1 只在合并前 `--base main` 那一遍才该认真看。

**跑崩了、跑超了、跑过了——三条照 autoresearch 的做法。**

- **崩溃**（OOM、NaN、栈回溯）：先看日志尾部。是 typo、漏 import 这种笨错，
  修了直接再跑一次——还没 commit，工作区改就是；修两次还崩就当想法不行——走 discard
  那条路（CSV、commit、stash），CSV `结论` 写 `crash：崩在哪一步、什么原因`。
  不要为一个想法修第三次。
- **超时**：第一轮跑的是基线，记下它用了多久。之后单次运行超过**基线两倍**
  就 kill 掉，当 discard 处理，`结论` 写 `timeout`。
- **去重**：追加记录前，用 CSV 读取器在本组文件中精确匹配 `task` 字段，避免将名称中的
  `.` 等字符当成正则表达式。已有结果的尝试不重复运行；结论为空时，先检查进程和输出，
  按下文恢复流程处理。计划内的重复实验使用新的轮次名，并在简介中说明重复的目的，
  不要仅换个名字重跑已经否定的尝试。

驱动层（`program.md` 之类）自己定了超时或重试策略的，以它为准；
这三条是没人定时的默认。

**每次 discard 后，先判断是否继续这个方向。** 例如，lr 从 0.04 增到 0.08 后结果仍变差，
就应重新判断是否值得继续增加到 0.16。由你根据结果趋势判断何时停止，不能只看尝试次数：

- 指标持续变差，还是围绕基线波动？前者提示方向可能不合适；后者可能是噪声，可以再试一次
- 继续调整带来的收益是否递减？新增收益接近零时，考虑结束这个方向
- 是否有支持停止的机制解释，例如学习率已到稳定边界？有就停止这个方向；暂时解释不了
  原因时，换个角度再试一次，不要继续增加同一个参数
- 别的方向还有多少没试？一个方向吃掉一夜三分之一的预算，就该问值不值

连续三次没有改善时，重新检查上述依据；不要仅凭次数决定停止。

**放弃一个方向时，必须写方向级的结论。** 这条不是判断，是规矩。那次 discard 的
CSV `结论` 列和 `record:` commit 的正文，写的是整个方向为什么不行，不是最后一次本身：

      lr↑ 放弃（0.04/0.08/0.16，最好 1.003 仍劣于基线 0.998）——
      学习率已在稳定边界，再推只会发散

      git commit -m "record: lr0.16_bs4_round1 discard" -m "lr↑ 放弃（0.04/0.08/0.16……）—— 学习率已在稳定边界，再推只会发散"

三行 discard 各写各的，回头只知道三次都不行，不知道这个方向已经判死，
下一夜的 agent 会把同一条死路再走一遍。

为了让同方向的行能对上，`简介` 以方向开头：`lr↑: 0.08，上次 0.04 无效再推一档`。
同前缀的行连着看，趋势就在眼前。

**用户可以重新选择此前 discard 的尝试。** 例如，主要指标稍差，但曲线更稳、代码更简单，
或另一项指标更好。先按完整实验路径找到 stash 的对象 ID，为这次取回分配新的 task，
填写 CSV 的计划和输出目录；简介注明「人工改判取回 <原task>」及用户的取舍理由，再执行：

    git stash apply <对象ID>

`apply` 将旧改动应用到当前代码，并不恢复当时的完整实验状态。解决冲突后，即使没有
文本冲突，也要**作为新尝试重新运行**，按运行结果和用户的选择补齐 keep 或 discard。
保留原记录，它描述的是当时的结果。

**开启时创建标记，停止时删除。** 标记用于在上下文压缩后恢复模式。下面以 `runs/` 为例；
有多个输出根目录时，先逐一确认均被忽略，再创建标记：

    if git check-ignore -q runs/; then
        mkdir -p .codegraph &&
        { [ -f .codegraph/.gitignore ] || printf '%s\n' '*' > .codegraph/.gitignore; } &&
        git branch --show-current > .codegraph/unattended
    else
        echo "runs/ 尚未被忽略，先补充 .gitignore" >&2
        false
    fi

开启前必须确认输出区已被 Git 忽略，否则 keep 时的 `git add -A` 会提交 checkpoint，
discard 时的 `stash push -u` 会将未跟踪的输出存入 stash，并从工作区移除。D2 虽然能报告
这个问题，但它属于文件级告警，不会标为 `changed=true`，仅查看本次改动时会漏掉它。
因此要在进入无人值守模式前补齐 `.gitignore`。

创建 `.codegraph/.gitignore` 是为了忽略该目录中的文件，防止 stash 将无人值守标记收走，
导致后续运行误判模式。codegraph 会创建这个忽略文件，因此这里只在文件缺失时写入。

**只在用户明确说要离开、让你自己跑时才落这个文件**——「开始迭代」「我去睡了」
「跑一夜」算；「继续」「好」「行」不算，那是对上一步的回应，不是授权离场。
拿不准就问一句「要我无人值守跑吗」，这一问值得。停止时 `rm .codegraph/unattended`，
再跑一次 `refresh.py`——`audit.json` 的 `unattended` 是审计那一刻的快照，不会自己翻回 false。
**文件存在且距修改时间不足 24 小时，标记才有效**；
`refresh.py` 把它写进 `audit.json` 的 `unattended` 字段，hook 在每次会话开始
（含压缩之后）输出提示。这两处是读取时的快照；可能过时时，检查标记是否存在及修改时间。
24 小时有效期用于避免遗留标记长期生效，文件中的分支名仅供人查看。

**不要因改动类型而切换模式。** 调整参数和修改架构都可在快速迭代中进行。用户叫停或
重新参与决策时，按停止步骤清除标记，回到构建期。单纯没有收到回复不代表获得了无人值守授权。

**无人值守任务尚未完成时，继续执行，不要提前给出最终总结并结束当前轮次。**
将实验决策写入 commit message 或 CSV，便于之后回查。无人值守时按既定规则处理，
不要提出需要用户回答的问题，再把沉默当成同意。

**上下文压缩后，从本地记录恢复。** 检查无人值守标记的存在与修改时间，再查看当前分支、
最近提交、本组 CSV、stash 列表和对应输出目录。恢复期间先核对已有进程或任务状态；
上下文压缩不代表实验进程已停止。CSV 的 `summary` 是组总结，不作为待恢复的实验行。

- **结论为空**：记录尚未完成。进程仍在运行就继续跟踪；确认正常结束后补齐指标和结论。
  若确认中断且无法恢复，记录 `crash` 及原因，按 discard 顺序提交 CSV，再用包含完整
  实验路径的 message 保存代码改动。不能仅凭指标文件存在就认定运行完成。
- **结论已填，但提交或存档未完成**：核对本组记录对应的 commit；discard、crash、timeout
  还要核对对应 stash。只补做未完成的步骤，不重复提交已有记录。没有代码差异时无需 stash，
  以 CSV 中的说明为准；有差异却找不到 stash 时，先核对工作区，不能假定已存档。
- **本次尝试已完整收尾，工作区仍有其他改动**：查清来源后，按 `recording-experiment-results`
  的无关改动处理方式决定是否提交，不能只因记录齐全就认定剩余改动无关。

未完成尝试的代码不能提交成 `chore:`，否则会混入后续尝试使用的基线。

## 合并前：把配置定在胜出的那次

**squash 合并的是分支最终状态，不会自动选择结果最好的那次。** 构建期每次尝试都提交
代码，因此最后一次若失败，分支仍保留那次的代码和配置。例如，最后试了 rank=32，
即使结果显示过拟合，配置也不会自动恢复。

收尾时，将配置恢复到选定的实验设置；全部失败则恢复到基线。将这次调整与 CSV 末尾的
总结行一起提交：最后一次实验尚未提交时可一并提交，已经提交则另建一个 commit，不 amend。
理由写入 commit 正文：

```bash
# 有赢家:把 config 改回 rank=16;CSV 末尾写结论
git commit -m "exp: 收尾 —— 定在 rank=16" -m "16 之后收益递减,32 过拟合"

# 全失败:git checkout main -- <配置文件>,回到基线;CSV 末尾写结论
git commit -m "exp: 收尾 —— 全部无效,配置回基线" -m "rank 8/16 都劣于 4,方向放弃"
```

快速迭代中，失败改动已经存入 stash，当前代码应对应最后一次 keep；全部失败时应仍是基线，
通常无需再次恢复配置。先核对当前代码是否与 CSV 中选定的结果一致，尤其要检查人工改判
取回的尝试。然后在 CSV 末尾追加本组总结，说明选定的配置、理由和下一步安排。
循环中每次尝试已经提交，因此总结单独提交，理由同时写入 commit 正文，不 amend。

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
`experiments/badcases/guidance_scale.csv`，分别对应各组输出目录）。
每组使用独立分支，每个 worktree 检出不同分支。各组写不同的 CSV，可避免同时修改同一份
实验记录；需要总表时，汇总 `experiments/**/*.csv`。若两组还修改了相同的代码或配置文件，
合并时仍需检查差异，不能保证没有冲突。

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

合并前确认最终代码和配置。只恢复配置不会自动撤销模型或数据管线的改动；如果本组只保留
实验结论，就需要把实现和配置都恢复到本组基线，核对剩余差异只有实验记录。若用户决定
保留部分实现，在总结和提交正文中说明保留内容及理由。

squash 将 CSV 等最终文件改动合入主分支，原来的 `record:` 提交仍留在实验分支上。
主分支通过 CSV 和总结提交保留失败结论。
