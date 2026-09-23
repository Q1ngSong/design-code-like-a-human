# worktree 的合并与删除

主流程见 SKILL.md 的「合并：保留两个父提交」和「每组一个 worktree」。本文只写 git 合并之外的两件事：
worktree 里未入库的数据怎么搬进目标目录，以及什么时候删 worktree。实验分支和非实验分支
（文档、论文、工具）做法相同。

## 为什么要单独处理

git 合并只带走入库文件。worktree 里生成的输出、报告和工具记录大多被 `.gitignore` 忽略，合并时留在原地；
`git worktree remove` 会把它们连同目录一起删掉，退出码 0，不提示。合并在某个路径带进入库文件时，
如果目标目录里同一路径有被忽略的文件，会直接覆盖它。

## 约定

- 新文件先在 worktree 里生成。
- 合并时 git 带走入库文件；其余未入库的数据按相同的相对路径搬进签出目标分支的目录（通常是主目录），
  原位置换成指向那里的绝对路径软链接。数据只留目标目录一份，worktree 照常读写，之后写进这些位置的内容
  直接落到目标目录。
- 缓存、虚拟环境和构建产物留在 worktree 本地，不搬。
- 没入库也没被忽略的文件不搬：记录要用的脚本入库（放 `temp_scripts/`），其余补进 `.gitignore`。
- 目标目录里有内容不同的同名文件时整体停下，一个都不搬。
- worktree 默认保留。

## 谁来做，什么时候做

- 由执行合并的 agent 做，作为合并流程的一步。合进主分支时前提和合并本身一样：人看过交接报告，说了合并。
  交接报告附上演练清单（脚本不加 `--apply` 的输出），冲突由人逐个决定。
- 无人值守时不合进主分支，所以也不搬，只把演练清单写进交接报告。分支之间的合并按 SKILL.md 由 agent 自己做，数据也自己搬。
- 默认由负责这个 worktree 的会话来搬；这个会话已经结束时，由执行合并的会话接手。
- worktree 里还有会话在工作，或者运行还在写输出时，不搬。

## 步骤

`wt_dir` 是 worktree 目录，`target_dir` 是签出目标分支的目录，`target_branch`、`source_sha` 与 SKILL.md 合并一节相同。

1. 合并前，检查分支新入库的文件会不会覆盖目标目录里被忽略的同名文件：

   ```bash
   git -C "$target_dir" diff --no-renames --name-only --diff-filter=A "$target_branch...$source_sha" |
   while IFS= read -r f; do
     if [ -e "$target_dir/$f" ] && git -C "$target_dir" check-ignore -q -- "$f"; then
       echo "would overwrite ignored file: $f"
     fi
   done
   ```

   有输出就先把这些文件移开，或确认可以被覆盖，再合并。把主分支合进实验分支时也做这一步，角色对调：
   `target_dir` 是本组 worktree，`target_branch` 是实验分支，`source_sha` 是主分支。
2. 按 SKILL.md 完成 git 合并，核对两个父提交。
3. 把下面的脚本存成项目外的临时文件，在合并后的目标目录上演练：

   ```bash
   bash worktree-merge-untracked.sh "$wt_dir" "$target_dir"
   ```

   每一项打印去向：`move + link` 搬走并留链接；`same, link` 目标已有相同文件，只换成链接；
   `keep local` 留在本地；`NOT IGNORED` 没入库也没被忽略；`CONFLICT` 目标里有不同的同名文件。
   有 `NOT IGNORED` 或 `CONFLICT` 时退出码为 1，什么都不改。
4. 问题处理完，加 `--apply` 再运行一次，成功后打印 `applied`。
5. 实验分支还要在目标目录跑记录检查（`recording-experiment-results` 的 `exp-check`），确认记录引用的输出都在。
6. worktree 保留。以后再从它合并时重复 1–5；已经换成链接的路径会被跳过，新生成的文件会被带走。

### 脚本

`KEEP_LOCAL` 是扩展正则，匹配相对于 worktree 的路径，默认只匹配 Python 缓存和虚拟环境。
项目有别的构建产物时加进去，并限定到具体目录，免得把实验日志误当构建产物留在本地。例如论文目录的 LaTeX 产物：

```bash
KEEP_LOCAL='(^|/)(__pycache__|\.pytest_cache|\.venv|venv)(/|$)|\.pyc$|^paper/[^/]*\.(aux|bbl|blg|fdb_latexmk|fls|log|out|toc)$|^paper/main\.pdf$' \
  bash worktree-merge-untracked.sh "$wt_dir" "$target_dir"
```

```bash
#!/usr/bin/env bash
# Move the files git does not track from a worktree into the target checkout and leave absolute symlinks
# behind, so the worktree keeps working and the data lives in the target. Dry run unless --apply is given.
# usage: [KEEP_LOCAL=<regex>] bash worktree-merge-untracked.sh <worktree dir> <target dir> [--apply]
set -u
wt=$(cd "$1" && pwd -P) || exit 2
target=$(cd "$2" && pwd -P) || exit 2
apply=${3:-}
keep_local=${KEEP_LOCAL:-'(^|/)(__pycache__|\.pytest_cache|\.venv|venv)(/|$)|\.pyc$'}
problems=0

plan() {  # plan <path relative to the worktree> <dry|apply>
  local rel=$1 mode=$2 src="$wt/$1" dst="$target/$1" child
  if printf '%s\n' "$rel" | grep -q -E "$keep_local"; then echo "keep local : $rel"; return 0; fi
  if [ -L "$src" ]; then
    case "$(readlink "$src")" in "$target"/*) return 0 ;; esac   # linked into the target by an earlier run
  fi
  if [ ! -e "$dst" ] && [ ! -L "$dst" ]; then
    echo "move + link: $rel"
    if [ "$mode" = apply ]; then
      { mkdir -p "$(dirname "$dst")" && mv "$src" "$dst" && ln -s "$dst" "$src"; } || { echo "FAILED: $rel" >&2; exit 3; }
    fi
  elif [ -d "$src" ] && [ ! -L "$src" ] && [ -d "$dst" ] && [ ! -L "$dst" ]; then
    for child in "$src"/* "$src"/.[!.]* "$src"/..?*; do
      [ -e "$child" ] || [ -L "$child" ] || continue
      plan "$rel/${child##*/}" "$mode"
    done
  elif [ -f "$src" ] && [ ! -L "$src" ] && [ -f "$dst" ] && cmp -s "$src" "$dst"; then
    echo "same, link : $rel"
    if [ "$mode" = apply ]; then
      { rm "$src" && ln -s "$dst" "$src"; } || { echo "FAILED: $rel" >&2; exit 3; }
    fi
  else
    echo "CONFLICT   : $rel"; problems=$((problems + 1))
  fi
  return 0
}

run() {  # run <dry|apply>
  local rel
  while IFS= read -r rel; do
    rel=${rel%/}; [ -n "$rel" ] || continue
    printf '%s\n' "$rel" | grep -q -E "$keep_local" && continue
    echo "NOT IGNORED: $rel (commit it or add it to .gitignore first)"; problems=$((problems + 1))
  done <<< "$(git -C "$wt" ls-files --others --exclude-standard --directory)"
  while IFS= read -r rel; do
    rel=${rel%/}; [ -n "$rel" ] && plan "$rel" "$1"
  done <<< "$(git -C "$wt" ls-files --others --ignored --exclude-standard --directory)"
  return 0
}

run dry
if [ "$problems" -gt 0 ]; then echo "stopped: $problems problem(s); nothing changed"; exit 1; fi
if [ "$apply" = --apply ]; then run apply > /dev/null && echo "applied"; fi
```

## 冲突和例外

- **CONFLICT**：常见于两组写了同一路径，或者编译产物。能重新生成的加进 `KEEP_LOCAL`；真正的数据由人决定留哪份，
  处理完重新演练。
- **NOT IGNORED**：记录要用的脚本入库；其余补进 `.gitignore`。
- **相对路径的软链接**：脚本只认指向目标目录的绝对路径链接，相对链接会报冲突，改成绝对路径再跑。
- **目标分支没在任何目录签出**：合并时在当前目录切到目标分支完成，数据本来就在这个目录，不用搬。

## 删除 worktree

只在不再需要时删：

- 代码更新后决定从新的基线重新注册同一组（另分出一个 worktree），旧的不再用；
- 用户要求合并并删除；
- 用户明确要删某个 worktree。

删除前：

1. 确认没有会话或运行在用这个目录。
2. 按上面的步骤把未入库的数据搬完，直到演练只剩 `keep local`。
3. 删除 worktree，再删掉因此变空的目录（所属部分的目录和容器）：

   ```bash
   git worktree remove "$wt_dir"
   rmdir "$(dirname "$wt_dir")" "$main_dir.worktrees"    # 还有别的组时报 Directory not empty，保留即可
   ```

删除 worktree 时，软链接只删掉链接本身，目标目录里的数据不受影响。`git worktree remove` 会删掉没搬走的图片和 checkpoint，
不要用 `--force` 掩盖未搬走的文件。worktree 目录被手动删掉时，用 `git worktree prune` 清掉残留的记账。

以上行为 2026-09-11 在 git 2.50.1 与 macOS 自带 bash 3.2 下实测：冲突和 `NOT IGNORED` 时不改任何文件；
搬走后经链接读写正常，重复运行不改动，新文件下次被带走；删除 worktree 后目标目录数据完整。
