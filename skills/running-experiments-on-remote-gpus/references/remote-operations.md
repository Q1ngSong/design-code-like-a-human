# 远程服务器操作命令

本地为 Windows + Git Bash，远端为 Linux + bash。每个 bash 代码块假定已执行第 1 节的变量定义
（每次新开 shell 都要重新执行）。尖括号内是必须替换的值，替换后不保留尖括号。

## 1. 变量与连接

```bash
set -o pipefail
KEY="$HOME/.ssh/<密钥文件名>"
PORT=<端口>
REMOTE=<用户>@<主机>
DISK=<远端数据盘根目录>            # 环境、输入、代码、日志都在它下面
REPO=$DISK/<仓库目录名>            # 远端代码检出
PY=$DISK/envs/<环境名>/bin/python  # 远端解释器
SSH_OPTS=(-i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new
          -o "UserKnownHostsFile=$HOME/.ssh/known_hosts_<主机别名>" -o ConnectTimeout=25 -o LogLevel=ERROR)
r() { ssh "${SSH_OPTS[@]}" -p "$PORT" "$REMOTE" "$@"; }          # r '远端命令'
cp_to_remote() { scp "${SSH_OPTS[@]}" -P "$PORT" "$1" "$REMOTE:$2"; }
```

- 生成专用密钥（文件已存在时跳过）：`mkdir -p ~/.ssh && ssh-keygen -t ed25519 -f "$KEY" -N ""`，
  把 `$KEY.pub` 的内容交给用户添加到远端 `~/.ssh/authorized_keys`。
- `BatchMode=yes` 使需要输入密码时立即失败而不是挂起。
- 首次连接记录主机密钥。之后若报主机密钥变化：停止，请用户确认机器是否重建过；确认后只删除
  `known_hosts_<主机别名>` 这一个文件再连接。
- 远端命令用单引号包住，其中的变量在远端展开。要传入本地变量时改用双引号，
  并把需要在远端展开的 `$` 写成 `\$`。
- 命令需要两层以上引号时，写成脚本文件，提交后随代码部署，再在远端执行该文件。

## 2. 测量

```bash
r 'nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader
   df -h / '"$DISK"' | tail -2; nproc; free -g | sed -n 2p
   cat /sys/fs/cgroup/memory.max 2>/dev/null'     # 容器内存上限;输出 max 或无输出表示未在此处限制
r 'for t in git screen tar pgrep timeout nvidia-smi python3; do command -v $t >/dev/null && echo "have $t" || echo "MISSING $t"; done'
```

吞吐 = 成功传输的字节数 ÷ 总耗时（并行测试的总耗时含启动间隔）：

```bash
# 上行,64 MiB
time (head -c 67108864 /dev/urandom | r 'cat > /dev/null')
# 下行,单连接,16 MiB
time (r 'head -c 16777216 /dev/urandom' | wc -c)
# 下行,32 连接,各 8 MiB
T=$(mktemp -d)
time (for i in $(seq 32); do (r 'head -c 8388608 /dev/urandom' | wc -c > "$T/$i") & sleep 0.25; done; wait)
grep -lx 8388608 "$T"/* | wc -l        # 成功的连接数;小于 32 时减少连接数重测
```

多连接合计吞吐高于单连接时，回传并发数取全部成功的最大连接数。

## 3. 上传输入文件

本地或远端缺 `rsync` 时用 tar 流。任一端失败时函数返回非零：

```bash
put() {  # put <本地基准目录> <远端目标目录> <相对路径...>
  local base=$1 dest=$2; shift 2
  tar -C "$base" -cf - "$@" | r "mkdir -p '$dest' && tar -xf - -C '$dest'"
}
verify() {  # verify <本地基准目录> <远端目标目录> <相对路径...>   对同一组路径两端比对 SHA-256
  local base=$1 dest=$2; shift 2
  diff <(cd "$base" && find "$@" -type f -print0 | sort -z | xargs -0 sha256sum | sed 's/ [ *]/  /') \
       <(r "cd '$dest' && find $* -type f -print0 | sort -z | xargs -0 sha256sum") && echo UPLOAD_VERIFIED
}
put    <本地输入根> "$DISK/<远端输入目录>" <相对路径> <相对路径>
verify <本地输入根> "$DISK/<远端输入目录>" <相对路径> <相对路径>
```

- `verify` 的相对路径不能含空格。`sed` 去掉 Git Bash 的 `sha256sum` 在文件名前加的 `*`，使两端输出格式一致。
- 只传任务实际加载的文件；同一权重的其他格式或精度副本不传。
- 多条流并行：每条流是一个顺序执行若干 `put` 的脚本，各自在本地后台运行。
- 传输中断的目录不可用：重新 `put`，`verify` 输出 `UPLOAD_VERIFIED` 后才启动依赖它的任务。

## 4. 部署代码

```bash
BRANCH=<实验分支>
SHA=$(git rev-parse "$BRANCH")
git bundle create /tmp/repo.bundle "$BRANCH"
r "mkdir -p '$DISK/deploy'" && cp_to_remote /tmp/repo.bundle "$DISK/deploy/repo.bundle"

# 首次:克隆到一个不存在的目录。被 git 忽略的输入和输出在这之后再上传进去
r "git clone -q -b '$BRANCH' '$DISK/deploy/repo.bundle' '$REPO' && cd '$REPO' && git config core.fileMode false"

# 更新(仅当没有写入者引用 $REPO;否则克隆到新目录)
r "cd '$REPO' && git pull -q --ff-only '$DISK/deploy/repo.bundle' '$BRANCH'"

# 每次部署后核对:SHA 一致且工作区无改动
r "cd '$REPO' && test \"\$(git rev-parse HEAD)\" = '$SHA' && test -z \"\$(git status --porcelain)\" && echo DEPLOY_OK"
```

- 仓库使用 Git LFS 或子模块时，bundle 不含这些内容，按第 3 节另传。
- shell 脚本须以 LF 换行提交：仓库 `.gitattributes` 加 `*.sh text eol=lf`，
  执行 `git add --renormalize .` 后提交。不在远端改换行。
- 环境记录（SKILL.md 第 3 节）：

  ```bash
  r "mkdir -p '$DISK/logs' && '$PY' -m pip freeze > '$DISK/logs/env_pip_freeze.txt' && { '$PY' -V; nvidia-smi --query-gpu=name,driver_version --format=csv,noheader; '$PY' -c 'import torch; print(torch.__version__, torch.version.cuda); print(torch.ones(4, device=\"cuda\").sum().item())'; cd '$REPO' && git rev-parse HEAD; } > '$DISK/logs/env_machine.txt'"
  ```

## 5. 启动、排队、停止

把 `scripts/run_until_done.sh` 和 `scripts/wait_then_start.sh` 复制进项目仓库并提交，随代码部署。
每个任务一个 `screen` 会话和一个日志文件，会话名即任务名。

`run_until_done.sh <gpu> <最大尝试次数> <完成检查命令> -- <任务命令>`：设置 `CUDA_VISIBLE_DEVICES`；
完成检查未通过就运行一次任务命令，最多尝试指定次数。任务命令必须自己跳过已完成的任务项。
退出码：0 完成检查通过；1 用完次数仍未通过；2 参数错误。它不限制单次运行的时长。

每个任务在仓库里有一个启动脚本，内容是一条 `run_until_done.sh` 调用，例如 `scripts/start_job_a.sh`：

```bash
#!/bin/bash
# 用法: start_job_a.sh <远端解释器>
cd "$(dirname "$0")/.." || exit 1
exec scripts/run_until_done.sh 0 5 "test \"\$($1 scripts/<完成计数脚本> outputs/<组>/<运行>)\" -ge <任务项总数>" \
  -- "$1" scripts/<任务脚本> --out outputs/<组>/<运行>
```

启动，30 秒后核对：

```bash
r "mkdir -p '$DISK/logs' && screen -dmS job_a bash -c 'bash $REPO/scripts/start_job_a.sh $PY > $DISK/logs/job_a.log 2>&1'"
r 'sleep 30; screen -ls; nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader -i 0; tail -5 '"$DISK"'/logs/job_a.log'
```

核对标准：`screen -ls` 列出 `job_a`；0 号卡的计算进程列表非空；日志末尾没有 `Traceback` 或 `Error`。
会话已不存在时看日志：末尾是 `=== DONE` 表示任务项本来就已全部完成。
权重已全部在远端时，在启动脚本里 `export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`，防止访问不可达的源而挂起。

`wait_then_start.sh <gpu> <超时秒数> <会话名[,会话名...]> -- <命令>`：等列出的会话全部结束、
该卡没有计算进程后，以 `CUDA_VISIBLE_DEVICES=<gpu>` 启动命令。超时只限制等待阶段。
退出码：3 等待超时；4 `nvidia-smi` 查询失败；2 参数错误；其余为命令自身的退出码。

```bash
r "screen -dmS queue_b bash -c 'bash $REPO/scripts/wait_then_start.sh 0 43200 job_a -- bash $REPO/scripts/start_job_b.sh $PY > $DISK/logs/queue_b.log 2>&1'"
```

会话结束不代表任务成功：`job_b` 依赖 `job_a` 的结果时，在 `start_job_b.sh` 开头检查 `job_a` 的完成条件。

停止（先排队脚本，再任务），然后核对没有写入者残留：

```bash
r 'for s in queue_b job_a; do screen -S $s -X quit; done; sleep 10; screen -ls
   ps -eo pid,etimes,args | grep -E "<任务脚本名>|run_until_done|wait_then_start" | grep -v grep
   nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader'
```

第二、三条命令仍有输出时，按列出的 PID 逐个 `kill <PID>`，再核对一次。
不使用 `pkill -f`：它可能匹配到执行这条命令的远端 shell，把当前 SSH 会话一起结束。

## 6. 查看进度

一次调用取回全部状态。`<完成计数脚本>` 是按任务完成条件统计已完成任务项数的仓库脚本：

```bash
r 'date "+%F %T %Z"
   for d in '"$REPO"'/outputs/<组>/*/; do echo "$(basename "$d") $('"$PY $REPO"'/scripts/<完成计数脚本> "$d")"; done
   screen -ls
   nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader
   grep -c "Traceback\|OutOfMemory" '"$DISK"'/logs/*.log
   df -h '"$DISK"' | tail -1'
```

取两次完成数，间隔不短于一个任务项的耗时，按 SKILL.md 第 4 节的公式算剩余时间。
两次之间没有新增完成项时不外推，先查该任务的日志。

## 7. 本地的等待与后台进程

- 等远端某个状态出现：在本地后台运行一个带截止时间的轮询，成功、失败、超时用不同的退出码。
  远端任务结束时写 `<名>.done` 或 `<名>.failed` 文件作为状态。

  ```bash
  end=$((SECONDS + 3600))
  until r "test -f '$DISK/logs/build.done'"; do
    r "test -f '$DISK/logs/build.failed'" && exit 2
    [ $SECONDS -gt $end ] && exit 3
    sleep 60
  done
  ```
- 停止本地任务后核对进程和显存；仍有输出时按 PID 结束，直到两条命令都无输出：

  ```powershell
  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '<脚本名>' } | Select-Object ProcessId, ParentProcessId, CommandLine
  nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader
  ```

## 8. 回传工具

`scripts/sync_remote_outputs.py` 只依赖本地 Python 3.8 以上的标准库和 `ssh`。项目相关的内容全部写在一个
JSON 配置里。模板 `scripts/sync_config.example.json` 中的每个值都是示例，必须逐项替换：

| 键 | 含义 |
|---|---|
| `host` `port` `key` `known_hosts` | 连接参数，同第 1 节。路径可用 `~` |
| `remote_python` | 远端任意 Python 3.8 以上解释器的绝对路径，用来生成清单 |
| `remote_root` | 远端输出根的绝对路径 |
| `local_root` | 接收 worktree 的输出目录，Windows 绝对路径，用 `/` 分隔（如 `D:/repo-wt/outputs`） |
| `remote_logs` | 可选。远端日志目录的绝对路径，递归取回到 `<state_dir>/logs/` |
| `state_dir` | `local_root` 下存放回传状态的单层目录名，默认 `_remote_sync`。远端输出根的顶层不能有同名条目 |
| `units` | 任务项规则列表，见下 |
| `exclude_dirs` | 输出根内任何层级上同名的目录都不取回 |
| `writer_pattern` | `pgrep -f` 正则，须匹配远端全部写入者的命令行（任务脚本、评测脚本、`run_until_done`、`wait_then_start`），且不匹配 `bash`、`sshd` 这类常驻进程 |
| `workers` | 并行连接数，取第 2 节实测值 |

`units` 的每条规则：
- `glob`：任务项目录相对 `remote_root` 的模式。按 `/` 分段，段数必须与目录深度相等，每段可用 `*` `?` `[]`；
  不支持 `**`。
- `done_file`：完成标记的文件名。
- `json_len`（可选）：完成标记必须是 JSON 数组且长度不小于此值。

匹配从外层目录向内进行，一个目录用第一条匹配的规则；任务项目录内部不再匹配。
不属于任何任务项目录的文件每轮都取回。

```bash
python scripts/sync_remote_outputs.py <配置.json> --dry-run   # 预演
python scripts/sync_remote_outputs.py <配置.json>             # 一轮增量
python scripts/sync_remote_outputs.py <配置.json> --final     # 最终回传
```

`--dry-run` 不取回、不移动任何结果文件，但会写本地状态目录和远端的哈希缓存、日志快照。
它输出清单文件数、已完成和被暂缓的任务项数，并把将被移走的本地文件逐行写入
`<state_dir>/dry_run_displace.txt`。

| 退出码 | 含义 |
|---|---|
| 0 | 清单中的文件全部已同步；或预演结束 |
| 1 | 有文件未同步或无法同步；或 `--final` 期间远端发生变化 |
| 2 | 命令行参数错误 |
| 3 | 本地磁盘空间不足 |
| 4 | 另一轮正在运行（`--final` 会等它最多 1 小时） |
| 5 | 异常，原因在输出和 `sync_state.json` 中 |
| 6 | `--final` 被拒绝：远端仍有写入者，或配置缺 `writer_pattern` |

输出的最后一行以 `SYNC` 开头：`SYNC UP-TO-DATE`、`SYNC VERIFIED FINAL`、`SYNC INCOMPLETE`、`SYNC DRY-RUN`、
`SYNC REFUSED`、`SYNC SKIPPED`、`SYNC CRASHED`。

`<local_root>/<state_dir>/` 的内容：

| 路径 | 内容 |
|---|---|
| `manifest.jsonl` | 最近一轮清单：每个文件的相对路径、大小、SHA-256、是否已同步 |
| `sync_state.json` / `sync_history.jsonl` | 最近一轮 / 每轮的结果：未同步文件、无法同步的条目、被移走的文件、失败原因 |
| `displaced/<时间>-<进程号>/` | 被移走的本地文件，相对路径不变 |
| `unfinished/` | `--final` 取回的未完成任务项 |
| `logs/` | 远端日志目录的副本 |
| `local_hash_cache.json` `sync.lock` `.staging/` `dry_run_displace.txt` | 工具自用，可在没有回传运行时删除 |

远端：`remote_root` 下有 `.sync_hash_cache.json`，`remote_logs` 下有 `.sync_snapshot/`，均为工具自用。

限制：不属于任何任务项目录的文件在远端被删除后，本地副本保留。

周期回传。路径含空格时须像下面这样在单引号内再加双引号；创建停止文件后，循环在当前一轮结束后
10 秒内退出并在日志写 `LOOP STOPPED`；本机休眠期间不运行，关机后需重新启动：

```powershell
Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass',
  '-File','"<路径>\sync_loop.ps1"','-Python','"<python.exe>"','-Config','"<配置.json>"','-StopFile','"<停止文件>"' `
  -RedirectStandardOutput '<日志>' -RedirectStandardError '<错误日志>'
```

启动后查看 `<日志>`，确认出现第一轮的 `SYNC` 行。

## 9. 现象与检查项

| 现象 | 先检查 |
|---|---|
| 远端进程退出码 137 | `dmesg` 或平台监控里的内存事件；第 2 节的内存上限 |
| `screen` 会话全部消失 | `uptime` 显示的开机时间是否晚于任务启动时间 |
| 远端 `.sh` 报 `\r` 或 `bad interpreter` | 脚本换行是否为 LF（第 4 节） |
| Git Bash 的 `tar` 报 `Cannot connect to C:` | 路径写成 `/c/...`，或加 `--force-local` |
| 回传某轮退出码 1 且列出 `batch incomplete` | 下一轮是否收敛；连续两轮不收敛则减小 `workers` |
| 同卡两个任务都变慢 | 重新测吞吐，判断是否只是分时（SKILL.md 第 4 节） |
| 本地输出目录在任务停止后仍在增长 | 本地进程列表（第 7 节） |
