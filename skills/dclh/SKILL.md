---
name: dclh
description: "DCLH / dclh：design-code-like-a-human 插件的跨宿主统一入口。用户说「dclh + 任务」「用 dclh …」或要求使用本插件时触发，涵盖科研代码编写、注释、审计、实验输出、分支和结果记录。Use when the user requests dclh or DCLH workflows in Codex, Claude Code, or another Agent Skills host."
---

# DCLH

将 `dclh <任务>`、`用 dclh <任务>` 中的任务作为本插件的请求，简称不区分大小写。
这是整个插件的入口，按具体任务读取并应用现有技能。以下路径相对于本文件所在目录。

根据当前会话的宿主信息路由，不能仅凭仓库中的 `.codex-plugin/`、`.claude-plugin/`
或安装的命令判断宿主。宿主未知时使用通用技能；只在任务确实需要宿主专有能力时核对。

- 当前宿主是 Codex：读取并应用 [Codex 入口](../using-design-code-in-codex/SKILL.md)。
- Claude Code 或其他宿主：按任务读取下表中适用的通用技能。

| 当前工作 | 读取并应用 |
|---|---|
| 写或修改科研代码 | [writing-minimal-code](../writing-minimal-code/SKILL.md) |
| 写 Python 注释和行为变更记录 | [writing-python-comments](../writing-python-comments/SKILL.md) |
| 确定实验输出目录 | [saving-experiment-outputs](../saving-experiment-outputs/SKILL.md) |
| 开实验组（注册 worktree）、迭代、恢复或收尾；文档、论文、工具分支的 worktree 与合并 | [running-experiments-on-branches](../running-experiments-on-branches/SKILL.md) |
| 写计划、指标、失败或组总结 | [recording-experiment-results](../recording-experiment-results/SKILL.md) |
| 看实验谱系：谁基于谁、哪条路死了 | [visualizing-experiment-lineage](../visualizing-experiment-lineage/SKILL.md) |
| 刷新索引、审计或判断 finding | [auditing-code-comments](../auditing-code-comments/SKILL.md) |
| 新项目建目录、填 `layers` | [designing-project-layout](../designing-project-layout/SKILL.md) |
| 跑别人的代码、复现 baseline | [reproducing-baselines](../reproducing-baselines/SKILL.md) |

只有 `dclh` 而没有任务时，沿用当前已明确的任务；没有明确任务则询问要处理什么。
调用简称本身不代表开始实验、创建 goal 或新建对话。
