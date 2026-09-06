---
name: saving-experiment-outputs
description: Use before writing or editing any script that saves files (checkpoints, metrics, figures, logs) - settle where the output goes before writing code, by proposing a concrete directory and getting it confirmed, so experiment results stay tidy instead of accumulating as output/ results2/ test_final/. 触发场景:代码目录设计、目录结构怎么定、结果存哪里、输出放哪、保存 checkpoint、存模型、存日志、写会产生文件的脚本、中间文件太乱、文件散落。
---

# 保存路径：先说好存哪儿

**要写盘的脚本，先把输出目录说定再动代码。** 就这一件事。
路径不先定，代码写着写着就长出 `output/`、`results2/`、`test_final/`,
几周后没人说得清哪个是哪个。

这是个习惯，不是流程。下面的目录形状是模板，抄不抄都行；
**问一句「存哪儿」才是要保留的那部分。**

## 有人在场

**项目已有输出目录的**——看一眼，照现有习惯拼一个具体路径，问一句：

> 这次输出存 `runs/ablation_study/lora_rank/rank8_lr1e-4/`?

确认或改一个字就完事。**不要把它拆成几个问题让用户回答再由你拼装** ——
习惯已经在那儿了，让他答题是替你填表。

**项目还没有任何输出目录的**——没东西可照，这时才问：这次要回答什么、
服务论文哪一节、这组变的是什么。三个答案拼成路径，从此就是这个项目的习惯。

**项目已有的习惯优先于任何模板。** 已经在用 `exp/`、`logs/`、
`checkpoints/2026-09-05/` 的，跟着它走，别去「纠正」成我们的形状。

## 无人值守

无人值守 = `audit.json` 的 `unattended` 为 true，或会话开头 hook 说了「无人值守中」
（哨兵怎么设见 `running-experiments-on-branches`）。长程自动任务里没人可问。按 实验计划 → 自己决定 的顺序定，
决定什么在变本来就是你的活。

但**自己定的要留痕**，连同依据。留在哪儿、什么格式，见
`recording-experiment-results`——那边的 CSV 就是这件事的落点，
其中「简介」一列写的正是**为什么试这个**：

    rank8_lr1e-4,"rank 4→8，上轮已收敛未过拟合",...

这一句最要紧。目录名说得了做了什么，说不了为什么做——有人在场时用户自己记得，
长程任务里没人记得。

## 一个可以照抄的模板

项目没有既成习惯时，这个形状省事：

```
runs/{服务论文哪一节}/{这组在试什么}/{本次变的是什么}/
     motivation           lora_rank        rank8_lr1e-4
     main_results
     ablation_study
     badcases
```

按论文章节分第一层，是因为实验最终要回答的是「图 3 哪来的」
「消融表这行对应哪次跑」。**这只是模板** —— 层数、命名、要不要分章节，项目自己定。

**叶子用 `{参数}{值}` 拼，只写这一组里变化的那几个**，同一配置跑多次就带上轮次：

    rank8_lr1e-4_round1        rank 8、学习率 1e-4、第 1 轮
    r8l4r1                     嫌长就缩，只要自己认得、能定位

不变的参数属于上一层（`lora_rank` 这个名字本身就说明在调 rank），塞进叶子
只会让每个名字都又长又像。叶子名开始变长是个信号：一组里有五六个参数在动，
多半不是一组实验，该拆。

叶子名同时是实验记录 CSV 里的 `task` 列——两边必须一字不差，
那是 CSV 和 `runs/` 之间的连接键（见 `recording-experiment-results`）。

## 写脚本时

开头算出**一个**目录，之后所有写盘从它派生：

```python
from pathlib import Path

task = f"rank{rank}_lr{lr}_round{i}"   # 这个字符串同时是 CSV 里的 task 列
out = Path("runs") / "ablation_study" / "lora_rank" / task
out.mkdir(parents=True, exist_ok=True)

torch.save(model.state_dict(), out / "ckpt.pt")
json.dump(metrics, open(out / "metrics.json", "w"))
plt.savefig(out / "loss.png")
```

把叶子名单独取出来存进变量，跑完记录时直接用它写 CSV，两边不会写岔。

**开跑前 `out` 已经存在，先看一眼是不是自己的。** `exist_ok=True` 不会拦，
静默覆盖掉上一次的 ckpt 才是最糟的。是自己上次崩了的半成品就升 round；
不是自己的——另一组实验碰巧起了同样的 task 名——就换个 task 名，
`out` 跟着 `task` 变，目录名自然一起换。

不 import 任何工具，怎么跑都行。脚本被多个实验复用时把上层做成命令行参数。

**不要为此引入辅助模块。** 做过一个带维度校验的 `save_root.py` 模板，
385 行防一个打字错误，还逼着全项目改用 `python -m` 跑，已删除。两行就够。

## 两条硬规矩

其余都是建议，这两条不是：

- **写盘点不自己决定路径。** 在脚本开头算出一个 `out`，之后每次写盘都从它派生。
  `torch.save(m, "ckpt.pt")` 是错的，`"./outputs/x.pt"`、`f"runs/{name}.png"`
  同样是错的 —— 错在这个写盘点自己拍了板。一次性脚本、探针也一样。

  注意上面推荐的 `out = Path("runs") / ...` **仍然相对 cwd**，在 `scripts/`
  里跑就落到 `scripts/runs/`。这条规矩不消灭 cwd 依赖，它做的是把十几个
  分散的路径决策收敛成一个 —— 将来要改成命令行参数或锚到项目根，只改那一行。

  审计规则 D3 查这条。
- **输出目录必须被 `.gitignore` 忽略。** 否则 checkpoint 会进版本库。
  换过根的项目写 `runs*/` 一条覆盖所有版本。

## 顺带把 .gitignore 补齐

科研仓库最常见的一类乱是**把不该推的东西推上去了**。启用项目时对着看一遍：

```gitignore
# 实验输出（实验的中间产物，包括权重、生成内容、评估记录、评估报告等。） —— 换根后仍覆盖
runs*/
# experiments/ 不在这里：实验记录入库，它是结论不是产物

# 索引与派生的审计报告,删掉重跑就回来
.codegraph/

# codegraph 的项目配置。它必须放在项目根(codegraph 只在那儿找它),
# 但内容由 .comment-standard.json 的 codegraph 段生成,同样是派生物
codegraph.json

# 密钥与本地配置 —— 一旦提交就永远留在历史里
.env
.env.*
*.pem
*.key

# Python 产物与虚拟环境
__pycache__/
*.pyc
.venv/
venv/
.pytest_cache/

# 编辑器与系统
.vscode/
.idea/
.DS_Store
```

密钥那组值得单独说：**成本一行，防的是不可逆的泄漏**。别的东西提交了还能删，
密钥进了历史就得改密钥。这个不对称性足以让它先写上，哪怕当前用不到。

### 已经推上去了怎么办

`.gitignore` 只对未跟踪的文件生效，后加的规则管不了已经提交的东西。
一个跑了半年才想起加 `runs/` 的项目，之前提交的 checkpoint 还在库里，
加了规则也不会消失。

查是安全的，加 `-C <项目根>`（命令不会改变你的当前目录，不加就可能查错仓库）：

    git -C <项目根> ls-files -i -c --exclude-standard

列出的是「已入库但按现在的规则本不该入库」的文件——多半是 checkpoint、
虚拟环境、索引目录。

**到此为止，把清单交给用户。** 移出索引的命令是：

    git rm -r --cached <路径>

**这条你不要执行。** 它改动 git 索引，误删的代价由用户承担；
而且哪些该留哪些该走，只有用户知道——一个看起来像中间产物的目录，
可能正是某篇论文的图表来源。列出文件、给出命令、说明后果，然后停下。
无人值守时同样不执行：清单和命令写进这一轮的记录（`结论` 列或 commit message），
循环照常，人回来再定。

还要一并说清：`git rm --cached` 只让文件不再出现在**新提交**里，
**历史里那份还在，仓库体积不会变小**。真要清干净得重写历史
（`git filter-repo` 之类），那会影响所有协作者，更得用户自己决定。
