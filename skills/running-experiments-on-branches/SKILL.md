---
name: running-experiments-on-branches
description: Use when starting, resuming, or closing a group of experiments - isolate runs on a branch, record the baseline and results, then preserve experiment history with a no-ff merge into the project's actual target branch. 触发场景:调参、跑实验、做消融、实验结束、实验收尾、合回 master 或 main、实验怎么用 git 管。
---

# 实验跑在分支上

**调参和实验不在主分支上跑。** 界线只有一条：改变主分支的操作要人来做，其余都归 agent。
主分支只进人看过结果、明确说合的东西，用 `git merge --no-ff` 保留整条实验历史，主分支因此保持干净，
每个合并节点对应一个有结论的实验组。从主分支开分支、开几组、试什么、分支之间合并、回退、删分支，
无人值守时自己控制，前提只有一个：每次尝试留下的 CSV 行、带 task 名的 commit、带路径的 stash 和
方向级结论，足以让人事后看清自动化做了什么、为什么，支撑得起最终结论。
主分支通过 `git log --first-parent` 浏览每组实验的合并节点，通过 `git log --graph --oneline --all`
查看具体尝试。默认不 squash、不 rebase、不 cherry-pick 代替合并。

分支名和目录名是模板，项目已有命名习惯时沿用。下文的提交、存档和恢复顺序相互配套，
采用这套流程时需要一起遵守。

## 一组实验一个分支

先读项目约定并检查 `git status --short`、`git branch -avv`、`git worktree list`。
确认实验的起点、第一合并目标及是否还要经过集成分支；`master`、`main`、`develop`
只是常见名称，不能从当前所在分支猜目标，也不要为套模板新建 `develop`。
已有分支时先恢复它，不重复创建。目标仍不明确时，有人在场就问一句；无人值守或用户已离场就不问：
基线取当前 HEAD（`baseline_sha=$(git rev-parse HEAD)`），开组记录里合并目标写「待定」，迭代照常。
合并目标只影响收尾要不要本地合并，收尾时仍不明确就停在本地实验分支，交接报告列出候选目标让用户选。

以下是 **Bash 示例**；在 PowerShell 中使用对应语法，逐步检查退出码。
假设项目约定直接合回 `master`，且起点也是 `master`：

```bash
target_branch=master
experiment_branch=exp/ablation_study/lora_rank
baseline_sha=$(git rev-parse --verify "${target_branch}^{commit}")
git switch -c "$experiment_branch" "$baseline_sha"
```

将实验分支、固定的 `baseline_sha`、实际合并目标链及完整运行配置写入本组记录或其链接的
说明文件并入库。基线是开组时的提交，后续恢复不能改用已经向前移动的主分支。
工作区有无关改动时先处理，方式见 `recording-experiment-results`：有人在场问一句，无人值守提交成 `chore:`；不丢弃、不 stash 用户的工作。

分支、输出目录和记录文件使用相同的实验组路径：

    分支    exp/ablation_study/lora_rank
    输出    runs/ablation_study/lora_rank/{task}/
    记录    experiments/ablation_study/lora_rank.csv

例如，`main_results/baseline` 和 `badcases/baseline` 是不同组，三处都保留章节名以免重名。
CSV 路径去掉输出根目录和最后一级 task 名，再加 `.csv`；stash message 则保留 task 名，
用于区分同组的不同尝试。

**「一组」有多大、要不要新开分支，你自己判断，无人值守时也一样。** 判据是：这些实验会不会
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

**快速迭代由用户授权开启，由用户叫停。** 默认是开放搜索：下一步试什么由你自己规划，网格是临时的，
按下文的趋势判断换方向，跑到用户叫停或约定预算（比如一夜）用完。只有用户明确给了固定清单时，
清单跑完就停，不自行加项。
前提是已有可运行的基线和评价指标，用于比较每次尝试的结果。迭代可以调整参数，也可以
修改架构，例如更换 attention 或重写数据管线。连续尝试较多时，为每次失败提交代码会
增加分支历史的阅读负担，因此失败尝试只提交记录，将代码改动保存在 stash 中：

```
开跑前 → 在本组 CSV 中按 task 字段精确查找，先处理未完成的尝试
       → 新尝试追加一行：填写 task、简介、输出目录，指标、结论留空
改代码 → 审计（`--base HEAD`，圈出这次的改动）→ 跑
  变好了 → CSV 那行补上 指标，结论 = keep
           git add -- train.py experiments/ablation_study/lora_rank.csv
           git diff --cached
           git commit -m "exp: lr0.04_bs4_round1 —— keep"
  没变好 → CSV 那行补上 指标，结论 = discard
           git add experiments/ablation_study/lora_rank.csv
           git commit --only -m "record: lr0.04_bs4_round1 discard" -- experiments/ablation_study/lora_rank.csv
           git stash push -u -m "ablation_study/lora_rank/lr0.04_bs4_round1"
           # 先确认剩余改动全属本次尝试；失败代码（含新文件）进 stash，记录留在分支
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
stash 成功后检查工作区及新条目；失败时不假定代码已恢复：先重试一次，仍失败就改走构建期的路，
把失败代码按 `exp: <task> —— discard` 提交到分支（多一个失败 commit，不丢东西），结论里注明
「stash 失败，代码在 commit」，工作区确认干净后循环继续。连 commit 也失败才停下说明阻碍。
**stash 只是本地存档，合并或推送实验分支不会带上它。** 需要在其他机器复现失败尝试时，
使用构建期的代码提交方式，或按已约定的备份方式保存 stash；不能把本地 stash 说成远端已有备份。

stash message 使用输出目录去掉 `runs/` 后的路径，可根据 CSV 的 `输出目录` 列找到对应条目。
路径包含实验组名，因此不同组的同名 task 可以区分；同名 stash 条目也不会相互覆盖。

查找时用 `git stash list --format='%H %gs'`，核对包含完整组路径和 task 名的消息，取得
对应的对象 ID。用 `git stash show -p -u <对象ID>` 查看改动，`-u` 会显示存档中的新建文件。
不同 worktree 共用 stash 列表，其他尝试也会使下标变化，因此后续操作使用对象 ID，
不要保存 `stash@{n}` 下标。循环中用 `push` 保存、`apply` 取回；`pop`、`drop`、`clear` 会移除条目，
要清理时先确认对应 CSV 行的结论已写全、失败代码不再需要。

**审计放在跑之前，用 `--base HEAD`。** 那时这次的改动还没 commit，`--base HEAD`
把落在改动上的告警（改了的函数、新文件、改动文件里的模块级语句）标成
`changed=true`，只看这些；D3（写死的输出路径）在烧
GPU 之前就能抓到。C1 会报这次改了的函数——函数体动了就报，改个常量也报——
那是预期，快速迭代里不为它补 `变更:` 行；合并前相对实际目标分支那一遍才认真看 C1。

**跑崩了、跑超了、跑过了——三条照 autoresearch 的做法。**

- **崩溃**（OOM、NaN、栈回溯）：先看日志尾部。是 typo、漏 import 这种笨错，
  修了直接再跑一次——还没 commit，工作区改就是；修两次还崩就当想法不行——走 discard
  那条路（CSV、commit、stash），CSV `结论` 写 `crash：崩在哪一步、什么原因`。
  不要为一个想法修第三次。
- **超时**：第一轮跑的是基线，记下它用了多久。之后单次运行超过**基线两倍**
  就终止本次运行及其子进程，确认它们已退出后再试；只处理本任务的进程。
  当 discard 处理，`结论` 写 `timeout`。
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

      git commit --only -m "record: lr0.16_bs4_round1 discard" -m "lr↑ 放弃（0.04/0.08/0.16……）—— 学习率已在稳定边界，再推只会发散" -- experiments/ablation_study/lora_rank.csv

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
有多个输出根目录时，先逐一确认均被忽略，且 `git ls-files -- <输出目录>` 没有已入库产物，再创建标记：

    if git check-ignore -q runs/; then
        mkdir -p .codegraph &&
        { [ -f .codegraph/.gitignore ] || printf '%s\n' '*' > .codegraph/.gitignore; } &&
        git branch --show-current > .codegraph/unattended
    else
        echo "runs/ 尚未被忽略，先补充 .gitignore" >&2
        false
    fi

开启前必须确认输出区已被 Git 忽略，否则宽范围暂存可能提交 checkpoint，
discard 时的 `stash push -u` 会将未跟踪的输出存入 stash，并从工作区移除。D2 虽然能报告
这个问题，但它属于文件级告警，不会标为 `changed=true`，仅查看本次改动时会漏掉它。
因此要在进入无人值守模式前补齐 `.gitignore`。

落哨兵前还要确认宿主处于免审批模式：Claude Code 开自动模式（或 `--dangerously-skip-permissions`）；
Codex 的 workspace-write 沙箱把 `.git` 整个设为只读，commit 和 stash 都会撞沙箱，必须由用户以
`--sandbox danger-full-access` 启动（细节见入口技能 `using-design-code-in-codex` 的 `/permissions`）。
否则第一条需要审批的命令就会把你挂到天亮。

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

**不要因改动类型而切换模式。** 调整参数和修改架构都可在快速迭代中进行。用户叫停或重新参与决策、
约定预算耗尽、或用户给的固定清单跑完时，按停止步骤清除标记，回到构建期。
单纯没有收到回复不代表获得了无人值守授权。

**无人值守任务尚未完成且可以继续时，继续执行，不要提前给出最终总结并结束当前轮次。**
将实验决策写入 commit message 或 CSV，便于之后回查。无人值守时按既定规则处理，
不要提出需要用户回答的问题，再把沉默当成同意。缺少必需信息或授权、无法安全恢复时，
保留现场并说明阻碍，不把持续重试当作进展。

**上下文压缩后，从本地记录恢复。** 检查无人值守标记的存在与修改时间，再查看当前分支、
最近提交、本组 CSV、stash 列表和对应输出目录。恢复期间先核对已有进程或任务状态；
上下文压缩不代表实验进程已停止。CSV 的 `summary` 是组总结，不作为待恢复的实验行。

- **结论为空**：记录尚未完成。尚未启动的计划里，用户明确暂停或取消过的不自动重跑，其余照常自己安排。
  进程仍在运行就继续跟踪；确认正常结束后补齐指标和结论。
  若确认中断且无法恢复，记录 `crash` 及原因，按 discard 顺序提交 CSV，再用包含完整
  实验路径的 message 保存代码改动。不能仅凭指标文件存在就认定运行完成。
- **结论已填，但提交或存档未完成**：核对本组记录对应的 commit；discard、crash、timeout
  还要核对对应 stash。只补做未完成的步骤，不重复提交已有记录。没有代码差异时无需 stash，
  以 CSV 中的说明为准；有差异却找不到 stash 时，先核对工作区，不能假定已存档。
- **本次尝试已完整收尾，工作区仍有其他改动**：查清来源后，按 `recording-experiment-results`
  的无关改动处理方式提交成 `chore:`，不能只因记录齐全就认定剩余改动无关。

未完成尝试的代码不能提交成 `chore:`，否则会混入后续尝试使用的基线。

## 实验结束：先收尾，再合并

**改主分支的事要人来做，分支上的事自己定。** 无人值守到点（预算用完、清单跑完、被叫停）
只是停止新增尝试，收尾到合并前一步为止：补齐 CSV、写总结行、收尾 commit、相对目标分支跑一遍审计和验证、
清除标记、留交接报告。哪怕用户离场前说了「跑完合回去」，也停在这里让人看一眼结果再合；
是否该合、合到哪，由人看过交接报告后决定，没说就一直留在实验分支上。
这是唯一要等人的一步。开分支、分支之间合并、回退、删分支、清 stash，无人值守时都自己控制，
前提只有一个：CSV 和带 task 名的 commit 还在，结论追得回来。

**运行完成、记录完成、本地合并完成、推送完成是不同状态。** 用户在场、看过结果后要求收尾合并，
且项目约定已明确合并目标时，完成下面的记录、验证和本地合并，不只给指标就结束。
用户仅要求暂停、保留分支或不合并时，按该范围处理；合并目标不明确时收尾到本地实验分支为止，
交接报告列出候选目标。推送沿用已有授权，不从无人值守标记推断。

完整收尾时确认进程退出、已启动的 task 有终态、指标和输出对应、失败尝试已存档，并清除标记。
用户暂停或提前结束时，安全停止相关运行并记录中断原因；未启动项保留空结果，在简介注明暂停或取消原因。
汇总本组 CSV 和实际完成范围，必要时附入库的分析说明；不要把未执行的计划写成已完成或崩溃。

**合并不会自动选择最好的配置。** 收尾前核对最终实现和配置是否对应选定的结果。
构建期最后一次可能是失败代码；快速迭代通常停在最后一次 keep，仍需核对人工改判等情况。
有明确选择就恢复选定设置；比较性扫描不必选出唯一赢家，可保留基线并说明指标与不确定性。

全部失败且不保留实现时，从开组记录的 `baseline_sha` 恢复本组改动的实现和配置，
包括处理基线中不存在的新增文件。逐一核对路径，保留实验记录和输出，不从当前主分支批量覆盖。
例如 `git restore --source="$baseline_sha" -- train.py config.yaml` 只适用于已核对的对应路径；
新增、删除、重命名文件另行核对，不把这个示例当成完整恢复清单。

将最终调整与 CSV 的 `summary` 提交：最后一次尝试已提交就新建收尾 commit，不 amend，
那会改掉上一条实验记录的 message。先前尝试的 commit 留不留由你定，CSV 里的行不能少。
只暂存本组路径，审阅 `git diff --cached` 后提交；说明保留内容和理由。
若跑后调整影响数值路径，重新验证并记录，不能拿旧指标证明新代码有效。

相对**即将接收这条分支的实际目标**检查完整差异，例如：

    python3 <插件根>/scripts/refresh.py . --base "$target_branch" --json

检查本次 findings、C1 及因删除调用点新产生的存量 R1，结合入口和调用关系判断，不能按零调用者直接删除。
检查索引状态和漏索引文件；退出码 0 不保证检查完整，1 是 finding，2 是审计未成功。
完成项目要求的验证，提交修正，确认工作区干净，再进入合并。

## 合并：保留两个父提交

有人在场、看过交接报告并说了合并之后才执行；无人值守不走这一节。下列步骤对每一级目标分别执行。示例变量来自开组记录；恢复会话时重新读记录，不能依赖旧 shell 变量。
**逐步检查命令是否成功；冲突、验证失败或状态不符时，不执行后续提交或推送。**

1. 检查源、目标工作区均干净且没有未完成的 merge/rebase/cherry-pick。
   `git worktree list` 显示目标已在其他 worktree 检出时，在那个目录操作，不强行抢占分支。
   需要同步远端时，先按项目约定 fetch 并核对分歧；不要用盲目的 pull 改写本地合并计划。
2. 记录源和目标的完整提交 ID，确认源分支包含本组记录与收尾代码：

   ```bash
   source_sha=$(git rev-parse --verify "${experiment_branch}^{commit}")
   target_before=$(git rev-parse --verify "${target_branch}^{commit}")
   git merge-base --is-ancestor "$source_sha" "$target_before"
   ```

   最后一条退出码 0 表示源已在目标历史中，核对现有结果后跳过重复合并；1 才继续；其他值是错误。
   文件树相同不代表已合并，旧 squash 也不建立源分支的祖先关系。不要自动重写旧历史来修复它。
3. 切到目标并核对 HEAD 仍是 `target_before`；目标或源已变化就重新审阅，不沿用过期结论：

   ```bash
   git switch "$target_branch"
   git rev-parse HEAD
   git merge --no-ff --no-commit "$source_sha"
   ```

   `--no-ff` 即使可快进也保留合并节点，`--no-commit` 让最终合并内容先接受审阅。
   查看 `git status`、`git diff --cached`，在合并后的代码上完成所需验证。
   冲突时逐项解决并暂存，不能整批选择 ours/theirs；处理影响实验行为时重新验证。
   无法继续则记录原因；需要撤销本次未提交合并时用 `git merge --abort`，不丢弃其他工作。
4. 确认无冲突、暂存内容正确且验证满足要求，再创建合并提交：

   ```bash
   git commit -m "exp(ablation_study): lora_rank —— rank16 最优, FID 11.9"
   git rev-list --parents -n 1 HEAD
   git merge-base --is-ancestor "$source_sha" HEAD
   git status --short
   ```

   标题中的结论和数字换成实际结果。`rev-list` 应输出合并提交及**恰好两个父提交**：
   第一个为 `target_before`，第二个为 `source_sha`；祖先检查应为 0，工作区应干净。
   核对分支仍指向计划中的提交。仅凭 commit 命令成功或文件内容相同不足以宣布合并完成。

通过 `git log --first-parent --oneline "$target_branch"` 浏览每组实验的合并节点，
通过 `git log --graph --oneline --all` 查看完整历史。**合并后实验分支留不留由你定**，默认保留；
已提交的失败记录和尝试已是目标分支的祖先，删分支不丢历史。没合并的分支删掉就是丢历史，
先确认结论已在 CSV 里。stash 中的失败代码仍然只在本地。

### 项目有 develop 时

只有项目约定这条链时才走：`实验分支 → develop → main`（最终分支也可能是 `master`）。
先按上述流程把实验分支合入 `develop`，再以刚完成的 `develop` 为源、`main` 为目标重复流程。
第二次合并须审阅 `develop` 相对 `main` 的全部待合入内容，包含其他任务时核对授权范围，
不能因本组完成就顺带发布无关修改。某一级失败时停在该级，不把整条链说成已完成。
主分支看到的是 `develop` 的合并节点，实验节点可沿第二父提交追溯；它不一定与实验组一一对应。

### 推送与交接

本地合并和远端同步分别处理。推主分支、集成分支这类目标分支是改变主分支的行为，要人来做：
用户已经授权向指定远端推送指定分支时，完成验证后直接执行；否则先完成本地可审阅结果，需要发布时
再询问。实验分支要不要推，按项目习惯自己定。示例 `git push origin main develop` 仅适用于
这两个分支与远端都已确认的项目，不默认推送所有分支、tag 或 stash，也不强制推送。
推送可能部分成功，逐个核对远端分支的提交 ID；拒绝时保留本地结果，记录未完成项，不覆盖远端历史。

交接报告写清实验结论、保留配置、CSV 和实际输出路径、验证结果、每一级源/目标及合并提交，
分别标明本地合并和远端推送状态。合并提交 ID 在创建后汇报，不要求把自身 ID 写进该提交。
上下文恢复时先查 Git 的进行中状态、祖先关系和远端状态，只补未完成步骤，不重复合并或重跑实验。

## 并行跑多组：用 worktree

从已确认的基线创建另一组，而不是隐式继承当前实验的 HEAD：

```bash
git worktree add -b exp/badcases/guidance_scale ../proj-guidance "$baseline_sha"
```

每组一个目录、一个分支、一个 CSV 和独立输出目录，各自维护基线和结论；需要总表时汇总
`experiments/**/*.csv`。worktree 共享 Git 对象和 stash，不能同时检出同一分支。
不同组仍可能修改相同代码，合并时照常审阅冲突和行为。

**移除 worktree 前先检查产物。** 停止相关进程，把忽略的输出复制到持久目录，验证完整性，
更新 CSV 中的实际路径并提交，确认代码和记录已保存且本组已按约定合并。
`git worktree remove` 会删除目录；Git 入库只保护已提交的记录，不保护其中的图片和 checkpoint。
只移除已核对的 worktree，不使用 `--force` 掩盖未保存状态；实验分支记录后可以选择性删除。

## 跑砸了的分支也保留结论

负面结论照样按同一流程 `--no-ff` 合并，message 写清无效的方向和证据。
合并前把不保留的实现和配置恢复到固定基线，检查相对基线剩余的差异只有记录或明确保留的修改。
这不会删除历史里的失败尝试，也不应覆盖目标分支后来新增的改进。合并后的代码仍需验证。
只合成功记录会掩盖已排除的方向，让后续实验重复走同一条路。
