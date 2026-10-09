# 发布流水线

## 发布脚本骨架（scripts/release.py）

```python
"""发布一个新版本：python3 scripts/release.py 1.4.1
改版本号 → 检查能构建 → 重新生成主页 → 提交「发布 vX」→ 打 tag → 推主分支和 tag。
先决条件不满足就停下，什么都不改。"""
import json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "main"                                  # 项目的主分支：main 或 master

def run(*args, cwd=ROOT):
    r = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if r.returncode != 0:
        sys.exit(f"命令失败：{' '.join(args)}\n{(r.stderr or r.stdout).strip()}")
    return r.stdout.strip()

def replace(path, pattern, repl):
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(pattern, repl, text, count=1, flags=re.M)
    if n != 1:
        sys.exit(f"{path} 里没找到要改的版本号")
    path.write_text(new, encoding="utf-8")

def main():
    version = sys.argv[1]; tag = f"v{version}"
    current = json.loads((ROOT / "package.json").read_text())["version"]   # 以其中一处为准
    if tuple(map(int, version.split("."))) <= tuple(map(int, current.split("."))):
        sys.exit(f"新版本 {version} 不比当前的 {current} 高")
    if run("git", "branch", "--show-current") != BRANCH: sys.exit(f"要在 {BRANCH} 上发布")
    if run("git", "status", "--porcelain"): sys.exit("工作区有没提交的改动")
    run("git", "fetch", "origin", BRANCH, "--tags")
    if run("git", "rev-parse", BRANCH) != run("git", "rev-parse", f"origin/{BRANCH}"): sys.exit(f"本地 {BRANCH} 和 origin/{BRANCH} 不一致")
    if run("git", "tag", "-l", tag): sys.exit(f"标签 {tag} 已存在")

    # 先检查再改文件：失败时工作区还是干净的（这里换成项目自己的构建检查）
    run("pnpm", "build:renderer"); run("cargo", "check", "--release", cwd=ROOT / "src-tauri")

    # 版本号出现在几处改几处
    replace(ROOT / "package.json", r'^(\s*"version": )"[^"]+"', rf'\g<1>"{version}"')
    # … Cargo.toml、Cargo.lock（name = "xxx"\nversion = …）、应用配置、代码常量

    run(sys.executable, str(ROOT / "site/build.py"))
    run("git", "add", "-A"); run("git", "commit", "-m", f"发布 {tag}")
    run("git", "tag", tag); run("git", "push", "origin", BRANCH, tag)
    print(f"已推送 {tag}，Actions 会构建并直接发布；跑完按「发布后的检查」逐项核对。")

if __name__ == "__main__":
    main()
```

先在一个临时克隆里（克隆一份 bare 仓库当假 origin）跑一遍脚本，确认提交、tag、推送都对，再用到真仓库。

## 发布工作流骨架（.github/workflows/release.yml）

```yaml
name: release
on:
  push:
    tags: ["v*"]
  workflow_dispatch:          # 手动触发只构建不发布，用来试工作流
permissions:
  contents: write
jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: windows-latest
            build: …
          - os: macos-latest
            build: …
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      # 装工具链、装依赖、构建（按项目来）
      # 产物改成英文文件名放进 out/，带版本号：Name_<version>_<platform>.<ext>
      - uses: actions/upload-artifact@v4
        with: { name: Name-${{ runner.os }}, path: out/* }
  release:
    needs: build
    if: startsWith(github.ref, 'refs/tags/')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with: { path: out, merge-multiple: true }
      - uses: softprops/action-gh-release@v2
        with:
          draft: false                      # 直接正式发布
          name: 项目名 ${{ github.ref_name }}
          files: out/*
          body: |
            各平台怎么装、首次打开的注意事项（未签名的提示怎么过）
```

- 私钥、令牌一律从 `secrets.*` 读，用 `env:` 传给构建步骤。Secret 不能是空值，没密码就不要建那个 Secret，工作流里引用不存在的 Secret 得到空串。
- 版本号从配置文件读（`node -p "require('./tauri.conf.json').version"`），不从 tag 猜；Release 名用 `github.ref_name`。
- 矩阵里 `fail-fast: false`，一个平台挂了另一个照跑，方便定位。

## 第一次跑之前

1. 用 `workflow_dispatch` 手动跑一次，只构建不发布，看 Artifacts 里的文件对不对。
2. 对照官方文档核对各步骤的大版本：<https://github.com/actions/checkout>、`setup-node`、`upload-artifact`、`download-artifact`、`softprops/action-gh-release`。
3. 推第一个 tag。

## 发布后的检查

推完 tag 按顺序查。`<o>/<r>` 是仓库，`vX.Y.Z` 是这次的 tag。

1. 找到这次的运行，阻塞等它跑完（不要写循环轮询），再看每个作业：
   ```bash
   gh run list -w release.yml -b vX.Y.Z -L 1 --json databaseId,status,conclusion,url
   gh run watch <databaseId> --exit-status
   gh run view <databaseId> --json jobs --jq '.jobs[] | "\(.name) \(.conclusion)"'
   ```
   每个平台的构建和 release 作业都是 `success`。
2. tag 在远端，指向发布提交：
   ```bash
   git ls-remote origin refs/tags/vX.Y.Z     # 有一行
   git rev-parse "vX.Y.Z^{commit}"           # 等于「发布 vX.Y.Z」那个提交
   ```
3. Release 是正式的，文件齐：
   ```bash
   gh release view vX.Y.Z --json isDraft,isPrerelease,isImmutable,url,assets \
     --jq '.isDraft, .isPrerelease, .isImmutable, .url, (.assets[] | "\(.name) \(.size)")'
   ```
   `isDraft`、`isPrerelease` 都是 false。照工作流矩阵列出应有的文件（每个平台的安装包；Tauri 再加更新包、
   `.sig` 和 `latest.json`），逐个对上：在、大小不为 0、文件名带 `X.Y.Z`。
4. 不登录也看得到：
   ```bash
   curl -s https://api.github.com/repos/<o>/<r>/releases/latest | python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'])"
   ```
   输出 `vX.Y.Z`。草稿查不到，预发布不算 latest。
5. 自动更新（Tauri）：
   ```bash
   curl -sL https://github.com/<o>/<r>/releases/latest/download/latest.json
   curl -sL -o /dev/null -w '%{http_code}\n' <latest.json 里某个平台的 url>    # 200
   ```
   `version` 是 `X.Y.Z`，每个平台的 `signature` 不为空。
6. 主页（用了的话）：
   ```bash
   gh run list -w "pages build and deployment" -L 1 --json conclusion,url   # 用 Actions 部署时换成 -w pages.yml
   curl -s -o /dev/null -w '%{http_code}\n' https://<o>.github.io/<r>/     # 200
   ```

### 哪一步没过，怎么办

先分清公没公开：没出 Release、或只是草稿，算没公开；正式 Release 一出来，就当已经有人下载过。

| 没过的地方 | 公开了吗 | 怎么办 |
|---|---|---|
| 推了 tag 但没有运行 | 没有 | `git ls-remote` 看 tag 在不在远端；工作流的 `on.push.tags` 是否匹配 `v*`。修好后删远端 tag 再推：`git push origin :refs/tags/vX.Y.Z`，再 `git push origin vX.Y.Z` |
| 某个平台构建红了，release 作业被跳过 | 没有 | `gh run view <运行 ID> --log-failed` 读错误。环境偶发的 `gh run rerun <运行 ID> --failed`；代码问题修好提交后，把 tag 挪到新提交重推：`git tag -f vX.Y.Z && git push -f origin vX.Y.Z` |
| 出的是草稿 | 没有 | 工作流改回 `draft: false`；这一次 `gh release edit vX.Y.Z --draft=false` |
| 缺文件或文件大小为 0 | 看情况 | 读 release 作业日志找哪步没产出。没公开：修工作流，`gh release delete vX.Y.Z --cleanup-tag` 后重推 tag；已公开：补传缺的文件（`gh release upload vX.Y.Z <文件>`），补不了就发补丁版本 |
| `latest.json` 缺了或版本号不对 | 看情况 | 同上。补齐之前，已装的应用一直显示「已是最新」 |
| 匿名接口看不到，或 latest 不是它 | — | 是草稿、预发布，或者有版本号更高的 Release；需要时 `gh release edit vX.Y.Z --latest` 显式标成 latest |
| 主页没更新 | — | 看 [project-page.md](project-page.md) 的 Pages 两种来源；部署记录、`.nojekyll`、根目录 `index.html` |
| 已公开的版本本身有问题（装不上、崩溃） | 是 | 不挪 tag、不删 Release，修好发补丁版本；一时修不好先 `gh release edit vX.Y.Z --prerelease`，latest 退回上一个正式版，自动更新不再推它 |

仓库开了不可变 Release（`isImmutable` 为 true）时，已发布的 Release 连文件都改不了，只能发新版本。
删 Release、删或挪 tag、强推之前先问用户。

## 排查

| 现象 | 看什么 |
|---|---|
| 看不到失败日志 | `gh run view <运行 ID> --log-failed`；没装 gh 又没登录时看不到 Actions 日志，让用户贴那一步的最后几十行，或用登录的浏览器读 |
| 黄色 "Node.js 20 is deprecated" | 警告不是错误；等官方步骤出新大版本再升 |
| 跑了 3 分钟就红 | 多半是编译错误而不是构建环境；Rust 项目先在本机 `cargo check --target <目标>` 复现 |
