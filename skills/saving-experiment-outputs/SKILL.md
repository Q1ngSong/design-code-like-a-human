---
name: saving-experiment-outputs
description: Use before writing or editing any script that saves files (checkpoints, metrics, figures, logs) - settle where the output goes before writing code, by proposing a concrete directory and getting it confirmed, so experiment results stay tidy instead of accumulating as output/ results2/ test_final/. 触发场景:结果存哪里、输出放哪、保存 checkpoint、存模型、存日志、写会产生文件的脚本、中间文件太乱、文件散落。
---

# 保存路径：先说好存哪儿

**要写盘的脚本，先把输出目录说定再动代码。** 就这一件事。
本 Skill 管输出位置和写盘规则；实验记录由 `recording-experiment-results` 统一组织。
确定 task、输出路径和路径基准后，由 recording 登记跑前计划；仅修改写盘脚本不自动创建实验。

路径不先定，代码写着写着就长出 `output/`、`results2/`、`test_final/`,
几周后没人说得清哪个是哪个。

下面的目录结构是模板。需要保留的要求是：写代码前确定输出位置；有人参与时确认具体
路径，无人值守时按实验计划决定并记录依据。

## 有人在场

**项目已有输出目录的**——看一眼，照现有习惯拼一个具体路径，问一句：

> 这次输出存 `runs/ablation_study/lora_rank/rank8_lr1e-4/`?

确认或改一个字就完事。**不要把它拆成几个问题让用户回答再由你拼装** ——
习惯已经在那儿了，让他答题是替你填表。

**项目还没有任何输出目录的**——没东西可照，这时才问：这次要回答什么、
服务论文哪一节、这组变的是什么。这些答案拼成路径，从此就是这个项目的习惯。

**项目已有的习惯优先于任何模板。** 已经在用 `exp/`、`logs/`、
`checkpoints/2026-09-05/` 的，跟着它走，别去「纠正」成我们的形状。

## 无人值守

无人值守的判定见 `auditing-code-comments` 的「无人值守」一节；`audit.json` 和 hook
提示可能过时，需要时检查标记文件。处于无人值守模式时，优先按实验计划确定输出路径，
计划未说明的部分自行决定。

**自行决定实验设置时，把设置及其依据写入 CSV 的「简介」列**（见 `recording-experiment-results`）。
目录名只说明本次做了什么，选择这组设置的原因需要另行记录。

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

组名说明比较的主题，例如 `lora_rank` 表示比较不同 rank，但不能替代具体参数值。
固定参数保存在本组配置或实验说明中，无需重复写入每个目录名。若多个参数同时变化，
按这些尝试是否需要放在一起比较来判断是否拆组，不要仅凭名称长度或参数个数决定。

运行目录的叶子名同时是实验记录 CSV 里的 `task` 列——两边必须一字不差，
以 CSV 组路径 + task 识别尝试，通过输出目录列关联产物；记录与输出目录不要求同构（见 `recording-experiment-results`）。

## 已有原始数据、重复评估或跨运行汇总

沿用现有输出区：运行独有产物归本次 task；再次评估分配独立批次；跨运行图表归分析批次，
记录输入集合和计算方式。改变输入或数值方法时新建批次，不覆盖旧报告引用的文件。
共享输入只引用来源，不因研究问题变化而复制或搬移数据。评估/分析批次不替换原运行 task。
需要追溯和机器校验时，使用
[memory 读写约定](../recording-experiment-results/references/memory.md)。

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

**开跑前，若 `out` 已存在，先确认它属于哪次实验。** `exist_ok=True` 不会阻止复用目录，
后续写入可能覆盖已有 checkpoint。独立重跑增加 `round`，生成新的 task 名并同步更新 `out`；
只有按实验恢复流程核对进程、代码、配置、输入和恢复点，确认接续同一次执行时才复用目录，
并记录恢复过程。相同叶子名位于不同组可保留；完整输出路径撞到另一尝试时重新分配。

直接在脚本入口组合路径，不要为此另写辅助模块。多个实验复用脚本时，将上层目录作为命令行参数。

## 两条硬规矩

其余都是建议，这两条不是：

- **写盘点不自己决定路径。** 在脚本开头算出一个 `out`，之后每次写盘都从它派生。
  `torch.save(m, "ckpt.pt")` 是错的，`"./outputs/x.pt"`、`f"runs/{name}.png"`
  同样是错的 —— 错在这个写盘点自己拍了板。一次性脚本、探针也一样。

  `out = Path("runs") / ...` 仍相对于启动脚本时的当前工作目录（cwd）。从 `scripts/` 目录
  启动，输出就位于 `scripts/runs/`。入口必须明确并记录路径基准：若沿用相对路径，运行命令
  固定启动目录；若支持任意目录启动，则按明确的项目/存储根解析输出位置。不要静默改变旧脚本的路径语义。

  审计规则 D3 查这条。
- **输出目录必须被 `.gitignore` 忽略。** 否则 checkpoint 会进版本库。
  使用 `runs`、`runs-v2` 等输出目录的项目，可用 `runs*/` 统一忽略。完整的 `.gitignore`
  模板及已跟踪文件的检查方法，见 `auditing-code-comments` 的 `references/setup.md`。
