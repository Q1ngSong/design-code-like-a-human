---
name: evaluating-frozen-methods
description: Use when the methods are final and their weights frozen, and what remains is evaluation - the paper's final numbers or an extra benchmark - with no training and no tuning. Covers where the weights come from, which benchmarks count, running every benchmark in full under one evaluation setup, and recording the results. 触发场景:开始评测、最终评测、在 benchmark 上评测、补测一个 benchmark、跑论文最终数字、测一下最终模型的效果。
---

# 评测已冻结的方法

方法和权重都已定型，剩下的是评测：论文的最终数字，或者补测一个额外的 benchmark。这是代码设计和训练之后的收尾，
不训练、不调参，所以**不问调参**。还要训练或调参的对比，用 `comparing-methods-fairly`。

分不清用哪个时，看这次的结果还要不要用来在方法之间做选择：还要选，就是对比，用 `comparing-methods-fairly`；
已经选定，只是报数字或补测 benchmark，用这里。

## 开一组评测

照常开组（`running-experiments-on-branches`），在组 README 里写对照协议，单独提交 `freeze(<组>): 对照协议`，再登记第一行：

```markdown
## 对照协议
- 对照方: ours, baseline_a, baseline_b
- 训练条件: 不训练；ours 来自 main-result/final @ 9f8e7d6；baseline_a 用官方权重，baseline_b 用复现的权重（见 BASELINES.md）
- 调参: 只评测，不调参
- 正式测试集: data/imagenet-c/
```

| 字段 | 写什么 |
|---|---|
| 对照方 | 要评测的方法。只评测一个方法时写一个 |
| 训练条件 | 写「不训练」，再写每一方的权重从哪来，见下面 |
| 调参 | 固定写 `只评测，不调参` |
| 正式测试集 | 这组要评测的 benchmark，写法同 `comparing-methods-fairly`：写路径，只测一部分时加 `N=数量` |

**每一方的权重从哪来**，写进 `训练条件` 一行：

- 我们的方法：定型那一组 summary 行选定的配置对应的 commit。有多个种子的，每个种子都评，报均值和标准差，
  不挑其中最好的一个。
- 外部 baseline：官方发布的权重（在 `BASELINES.md` 那一节写明下载地址和文件哈希），或者按 `reproducing-baselines`
  复现、判定为「通过」的权重。
  它们按各自论文的方式训练，不要求和我们同一份训练条件，也不用重训；公平体现在评测上，见下文「评测时」。
- 我们自己方法的新旧版本、消融版本放在一起比，看某个改动有没有用：这时各版本必须来自同一份训练条件，
  不是就回到 `comparing-methods-fairly` 重训；也不能拆成几个只评测一个版本的组，再把数字放在一起比。

**benchmark 由用户定，或者沿用论文计划里已经定的**；Agent 不自己挑，也不换成更小的。
组里写了 `正式测试集`，就只按它检查；没写，就沿用上级 README 声明的正式测试集。

## 评测时

- 所有方法用同一套评测：benchmark 这一侧完全一样（同一份数据和版本、同一套划分、同一份指标代码），
  生成类评测用同一组随机种子。模型自己要求的输入处理（分辨率、归一化）按各自的官方实现来。
- 不在评测用的 benchmark 上挑任何东西：checkpoint、阈值、提示词都不挑。要挑就是调参，
  回到 `comparing-methods-fairly`，在验证集上挑。用户要在评测时再调参，这组就不是只评测了：
  这组不动，另开一组按 `comparing-methods-fairly` 在验证集上挑。
- 每个 benchmark 都跑满：`指标` 写成 `mCE 60.1 @data/imagenet-c 全部`，写了 N 的写 `N/N`。
  没跑完记 `timeout`，指标填 `—`；smoke 的数字不进记录。
- CSV 一行记一个方法，`简介` 以方法名开头（`ctx_gate: 最终评测`），`指标` 里组内每个 benchmark 各写一个标注；
  跑完的评测结论写 keep。想分开评不同的 benchmark，就一个 benchmark 开一组。
- 不同方法的评测互不依赖，同时开，见 `running-experiments-on-branches`「互相独立的运行同时开」。

## 收尾

按 `recording-experiment-results` 写组 README 的「结论」块。「回答」写明是哪个 benchmark 上的结论：
补测的 benchmark 上得出的结论，不能说成主测试集上的结论。「对总览的影响」照常写。

## 脚本会检查什么

和对比组一样，由 `recording-experiment-results` 的 `scripts/memory.py` 检查：`简介` 以对照方开头；
keep 或 discard 的指标标明每个 benchmark 都跑满了；crash 或 timeout 的指标填 `—`。
只评测的组有两处不同：组里写了 benchmark 就不再要求上级的正式测试集；对照方可以只有一个。
