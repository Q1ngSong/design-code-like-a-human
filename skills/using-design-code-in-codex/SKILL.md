---
name: using-design-code-in-codex
description: "Codex entry point for design-code-like-a-human. Use in Codex for research-code changes, comment audits, experiment planning, unattended iteration, or experiment-session recovery. Select the shared skills and relevant native capabilities, including explicitly requested goals. Not for Claude Code. 触发场景：在 Codex 中使用本插件、科研开发、注释审计、跑实验、无人值守、恢复实验任务。"
---

# Codex 入口

本技能集中处理 Codex 的宿主能力，并按任务调用六个通用技能。实验步骤、审计规则和
记录格式仍由通用技能维护，项目约定和用户已给出的授权继续适用。

## 选择入口与技能

根据当前会话的宿主信息选择入口；仓库含 `.codex-plugin/` 或机器安装了 `codex`
不能单独证明当前宿主。Claude Code 或其他宿主直接按任务使用通用技能。
读取本入口或询问插件用法，不代表开始实验、创建 goal 或新建对话。

只读取当前任务需要的技能；下列路径以本技能目录为基准。实验循环由实验技能安排，
本入口不另起一套循环，也不要求每次任务都使用下文全部指令。

| 当前工作 | 读取并应用 |
|---|---|
| 写或修改科研代码 | [writing-minimal-code](../writing-minimal-code/SKILL.md) |
| 写 Python 注释和行为变更记录 | [writing-python-comments](../writing-python-comments/SKILL.md) |
| 确定实验输出目录 | [saving-experiment-outputs](../saving-experiment-outputs/SKILL.md) |
| 开实验组、迭代、恢复或收尾 | [running-experiments-on-branches](../running-experiments-on-branches/SKILL.md) |
| 写计划、指标、失败或组总结 | [recording-experiment-results](../recording-experiment-results/SKILL.md) |
| 刷新索引、审计或判断 finding | [auditing-code-comments](../auditing-code-comments/SKILL.md) |

## 十项常用指令及配套操作

slash 指令是用户在 Codex 输入框中的入口，不是 shell 命令。CLI 与桌面端支持情况
可能不同，以当前菜单和实际工具契约为准。有对应工具且已有所需授权时直接使用；
仅有界面入口时告知用户如何操作，不声称已执行，不另开 Codex 进程模拟当前任务的控制。

### 1. `/goal`：持续完成明确目标

需要创建或恢复目标时，先用可用的 `get_goal` 核对状态。同一任务复用已有目标，
不因下一次实验或上下文压缩重复创建，也不覆盖其他未完成目标。
用户明确要求创建 goal，或已有适用于本次工作的明确 goal 授权时，才调用 `create_goal`。
「无人值守」「开始迭代」及 `.codegraph/unattended` 标记本身不构成该授权。

从请求和已确认的计划确定目标、允许修改范围、验证方式和可检查的停止条件。
仅在用户明确给出 token 预算时传入 `token_budget`。工具不可用时说明限制，
继续仍可执行的已授权工作，不自动修改宿主配置或承诺跨轮次续跑。

goal 管跨轮次推进；无人值守标记仍按实验技能创建、检查和清除，两者不能互相代替。
恢复时同时核对分支、CSV、现存进程、输出和未完成的提交/存档，先处理已有尝试。
目标达成、验证通过且必要记录和收尾完整后，才用 `update_goal` 标记 `complete`。
单次失败、预算将尽或用户叫停不等于完成；`blocked` 按当前工具的连续阻塞判据处理。
暂停、恢复或清除目标使用宿主实际支持的控制，如 `/goal pause`、`/goal resume`、
`/goal clear`；工具不能执行时如实说明，不用完成/阻塞冒充暂停，不自行恢复已暂停目标。
用户叫停后停止安排新工作，核对已有进程并按用户要求处理，保留恢复记录。

### 2. `/plan`：设计实验再实施

用户要求先规划时，核对基线、指标、种子与数据划分、每组改变的变量及验收方式。
执行前按通用技能确定分支、输出和跑前 CSV 记录。已有明确方案和实施授权时直接推进；
写出计划不等于切换了宿主 Plan 模式，模式切换以实际宿主控制为准。

### 3. `/review`：审查行为变化

确认审阅范围，再按项目 README 的入口刷新和审计。本轮用 `--base HEAD`，合并前
比较实际目标分支，不硬编码 `main`。结合调用方判断 finding，核对索引是否完整；
原生 review 不能替代插件审计，零调用者告警不能单独作为删除入口或依赖代码的依据。

### 4. `/diff`：核对实际修改

结合 `git diff`、`git diff --cached` 和 `git status --short` 查看未暂存、已暂存及
未跟踪文件，避免漏掉新文件。检查实验产物是否按项目规则忽略；无关改动先核对来源。
桌面端有 `open_in_codex` 时可展示 review 面板，展示差异不代表已验证或已提交。

### 5. `/ps`：跟踪训练和评估进程

使用已返回的终端/进程会话 ID 读取日志和退出状态，复用已启动的运行。
恢复上下文不等于进程已经停止，指标文件出现不等于运行成功。
超时、崩溃和重试按实验技能或用户给定策略处理，只操作已确认属于当前尝试的进程。

### 6. `/status`：核对环境与状态

只报告当前会话可读取的模型、目录、权限和上下文信息。目标状态用 `get_goal`，
账户额度在 `get_usage_limits` 可用时查询，实验状态以运行结果为准，三者不相互替代。
读不到剩余上下文时不估造百分比；查询用量不代表授权使用额度重置或改变预算。

### 7. `/compact`：整理上下文与恢复证据

先按记录技能保存当前 task、完整命令及配置/代码版本关联、输出路径和未完成步骤。
运行中的尝试保留实际状态，不为压缩虚填完成结论。压缩由宿主自动执行或用户触发；
没有对应工具时可整理交接摘要，但不能声称普通摘要已完成原生上下文压缩。

### 8. `/resume`：接续已有实验任务

用户要求继续旧任务时，按项目、实验组和标题定位并核对内容，不能默认最近一项就是目标。
桌面端可按实际工具契约使用 `list_threads`、`read_thread`、`send_message_to_thread`；
CLI 可选择已保存会话。续接后先检查进程、CSV 和 goal 状态，再处理未完成尝试。

### 9. `/fork`：分开方案探索

仅在用户要求分叉或新任务时使用 `fork_thread` 或宿主入口。对话分叉与 Git 分支/worktree
是两件事；只要求开实验分支时不新建对话。分叉后核对目录、基线和记录位置，
不能假定运行中的半轮内容、进程或 goal 状态已复制。

### 10. `/permissions`：处理执行权限

已有权限和授权足够时直接执行。遇到实际限制，说明具体路径或操作并走宿主审批流程；
权限菜单由用户控制，无人值守不等于授权关闭沙箱、扩大权限或把拒绝当作成功。

无人值守的沙箱问题要在开始前由用户解决：workspace-write 沙箱把 `.git` 整个设为只读，循环里每次
commit 和 stash 都会撞沙箱，approval 是 `on-request` 就弹窗等到天亮，是 `never` 就直接失败。
落哨兵前提醒用户以 `--sandbox danger-full-access`（或配置 `sandbox_mode = "danger-full-access"`）
重新启动，并确认第一次 commit 能过。

指令语义核对日期：2026-09-07；宿主更新后以当前工具契约和菜单为准。
参考：[OpenAI 指令文档](https://learn.chatgpt.com/docs/developer-commands?surface=cli)、
[goal 工作流](https://learn.chatgpt.com/use-cases/follow-goals)。
