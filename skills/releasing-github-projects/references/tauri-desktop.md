# Tauri 桌面应用：安装包、签名与自我更新

## 接入自我更新（一次性）

1. 生成签名密钥，放仓库外并备份：`pnpm tauri signer generate -w ~/.tauri/<app>.key --ci`（`--ci` 不设密码）。
   生成 `<app>.key`（私钥）和 `<app>.key.pub`（公钥）。**私钥丢了，装出去的版本永远收不到更新。**
2. 依赖：Rust `tauri-plugin-updater`、`tauri-plugin-process`；页面 `@tauri-apps/plugin-updater`、`@tauri-apps/plugin-process`。
   注意 npm 的 `@tauri-apps/api`、`@tauri-apps/cli` 和 Rust 的 `tauri` 要同一个大小版本，否则 CLI 直接拒绝构建；
   新版 tauri 可能要求更高的 rustc（2.12 要 1.90），`rust-toolchain.toml`、`Cargo.toml` 的 `rust-version`、工作流里的 toolchain 三处一起改。
3. `main.rs` 登记：`.plugin(tauri_plugin_updater::Builder::new().build()).plugin(tauri_plugin_process::init())`。
4. `capabilities/default.json` 的 permissions 加 `updater:default`、`process:default`。
5. `tauri.conf.json`：
   ```json
   "bundle": { "createUpdaterArtifacts": true },
   "plugins": { "updater": { "pubkey": "<公钥文件内容>",
                             "endpoints": ["https://github.com/<o>/<r>/releases/latest/download/latest.json"] } }
   ```
6. 页面：`check()` → 有更新则 `downloadAndInstall(进度回调)` → `relaunch()`。浏览器版（没有 `__TAURI_INTERNALS__`）装不了自己，退回「问 GitHub `releases/latest` 接口，有新版本就打开发布页」。
   插件的英文报错换成人话：`release JSON` 相关 → 「GitHub 上还没有发布的版本，或者连不上」；`signature` → 「更新包签名对不上，没有安装」。
7. GitHub 仓库 Secret：`TAURI_SIGNING_PRIVATE_KEY` = 私钥文件全文。没密码就不要建 `…_PASSWORD`（空值建不了）。
   本机打包：`export TAURI_SIGNING_PRIVATE_KEY=$(cat ~/.tauri/<app>.key)`（`_PATH` 变量不一定被认）。

## 发布产物

| 平台 | 构建 | 安装包 | 更新包 |
|---|---|---|---|
| macOS 通用 | `--target universal-apple-darwin --bundles app,dmg` | `bundle/dmg/*.dmg` | `bundle/macos/*.app.tar.gz` + `.sig` |
| Windows | `--bundles nsis` | `bundle/nsis/*-setup.exe` | 同一个 exe + `.sig` |

全部改成英文名放进 `out/`，release 作业再生成 `latest.json`（通用版 .app 同时给两种 Mac）：

```python
import json, pathlib, datetime
tag = "${{ github.ref_name }}"; version = tag.lstrip("v")
base = f"https://github.com/${{ github.repository }}/releases/download/{tag}/"
out = pathlib.Path("out")
entry = lambda name: {"url": base + name, "signature": (out / (name + ".sig")).read_text().strip()}
mac = entry(f"App_{version}_universal.app.tar.gz"); win = entry(f"App_{version}_x64-setup.exe")
(out / "latest.json").write_text(json.dumps({"version": version,
    "pub_date": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "platforms": {"darwin-aarch64": mac, "darwin-x86_64": mac, "windows-x86_64": win}}, indent=2))
```

应用读的是 `releases/latest/download/latest.json`，**只有正式发布的 Release 才有这个地址**，草稿和预发布都不算。

## 本机完整验证一次

不用等真发布，用假服务器把「检查 → 下载 → 校验 → 安装 → 重启」走一遍（macOS）：

1. 构建 A：当前版本，更新地址指向本机
   `pnpm tauri build --bundles app --config '{"plugins":{"updater":{"endpoints":["http://127.0.0.1:8777/latest.json"],"dangerousInsecureTransportProtocol":true}}}'`，把 `.app` 复制到别处。
2. 构建 B：`--config '{"version":"<更高版本>"}'`，拿 `.app.tar.gz` 和 `.sig`，按上面的格式写 `latest.json`，`python3 -m http.server 8777`。
3. 打开 A，设置页点检查更新 → 安装。服务器日志里应先后出现 `latest.json` 和 `.app.tar.gz` 的请求；装完 A 的 `Info.plist` 版本变成 B 的。
   `--config` 只改打包配置，代码里的版本常量不变，所以 B 显示的「当前版本」还是旧的，这是测试方法的局限，不是 bug。

## 踩过的坑

- **Windows 构建 `unresolved import ShellExecuteW`**：`windows-sys` 的函数按特性门控，以前靠别的依赖顺带打开，升级 tauri 后不再帮开。
  自己用到的特性全部显式写进 `Cargo.toml`（`ShellExecuteW` 还要 `Win32_UI_WindowsAndMessaging`）。本机跨编译检查会卡在 `ring` 的 C 代码，这类错只能靠 CI 或读 CI 日志。
- **应用一直说「已是最新」**：Release 是草稿；或 `latest.json` 没上传；或公钥和签名私钥不是一对。
- **签名步骤报「A public key has been found, but no private key」**：构建环境没有 `TAURI_SIGNING_PRIVATE_KEY`。
- 未签名、未公证的 macOS 应用首次打开要右键「打开」或 `xattr -dr com.apple.quarantine`；updater 装上的更新包不经浏览器下载，没有隔离属性，重启后能直接打开。
- 相邻两个版本都没有 updater 时，用户必须手动装一次带 updater 的版本，从那之后才自动。
