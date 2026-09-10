---
name: visualizing-experiment-lineage
description: Use when someone wants to see how a set of experiments evolved - which attempt built on which, where a direction died, what won - as a top-down lineage page generated from the group CSVs and git history, so nobody has to read git log. 触发场景:画实验谱系、实验进化图、看看探索到哪了、这些尝试谁基于谁、方法探索的路线、把实验结果可视化、哪条路死了。
---

# 实验谱系：一页看清谁基于谁

**只读记录，不写记录。** 页面是派生物：节点来自 CSV，边来自 git，叙述来自 README。
想让页面多说一句，就把那句写进组 README 或总览 README 再渲染一次；页面本身不手改、不入库。

## 什么时候用

用户想看方法探索走到哪了、哪条路死了、胜出的是从哪一支长出来的。
默认只画 `exploration`（暂未归入论文的方法探索），要看别的部分或单个组就把范围传进去。
`main-result` 这种一表就能看清的部分不需要它。

## 怎么做

1. 确认记录根目录（`Experiments/`，或项目沿用的名字）和输出根目录（`outputs/`、`runs/`……），
   沿用 `recording-experiment-results` 与 `saving-experiment-outputs` 已经定下的。
2. 先跑 recording 的 `exp-check`。列结构不对的 CSV 页面会整组跳过并列在页脚：先修记录，别改脚本迁就。
3. 渲染：

       python /path/to/visualizing-experiment-lineage/scripts/lineage.py --root /path/to/project --records Experiments --scope exploration --out outputs/lineage/exploration.html

   `--scope` 相对记录根目录，可以是部分或组，`.` 表示全部；`--out` 相对项目根，放输出根下，不入库。
   加 `--json` 只打印数据不写页面，用来核对边算得对不对。Python 3.10+ 标准库，不装东西。
4. 告诉用户页面路径，转述脚本列出的「跑完了却找不到 commit」的行。那是记录纪律的缺口
   （标题没带 task 名、跑完没提交），修的是记录和提交，不是页面。

## 边是怎么来的

一个节点 = 一次决策 = 一个 commit：标题含 task 名、且改了本组 CSV。批量扫描一个 commit 多行，就是一个节点多行。
父 = 沿 first-parent 往上遇到的第一个「带 task 行且改了代码」的 commit：

- 快速迭代的 discard 只提交记录、代码进 stash，下一次 keep 的父跳过它落到上一个 keep。
- 构建期失败代码进了分支，下一次确实基于它，就照实画。
- 遇到 `--no-ff` 合并节点钻进被合并的分支，找到那组最后一次带代码的决策。这就是跨组边：
  组 B 从组 A 的胜出代码出发。
- 没有 git、或某行对不上 commit：父 = 同一 CSV 里上一个 keep 行，虚线标「推断」。

范围外的组也读进来参与解析，但不画；父在范围外画成存根「来自 ablation/xxx」。
同名 task 可能出现在不同组，所以配对还要求那个 commit 改过本组的 CSV。

## 页面上有什么

单文件 HTML，样式和脚本全内联，零外链。顶部：总览 README 里该部分的「当前结论」、图例、
折叠 discard 叶的开关、按组变暗的筛选。主体：每个部分一片自顶向下的森林，节点卡片是 task、状态色、指标；
组的入口节点标组名。点节点：右侧显示那行 CSV 的五列原文、`CSV 路径:行号`、commit 与标题、
本机 stash 名（discard 的代码在哪）、输出目录、它基于哪次。页脚披露来源、推断边的数量和跳过的行。

## 不做

- 页面里不写 Agent 的叙述。要写就写进 README。
- 不加「基于」列、不建第二份谱系文件。git 已经记着，再记一份会漂。
- 不入库。
