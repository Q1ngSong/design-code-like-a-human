---
name: releasing-github-projects
description: Use when a software project needs a GitHub project page or GitHub Pages, a new version published with installers on a Release, in-app auto-update for a Tauri desktop app, or a check of whether a release succeeded and what failed. 触发场景：做项目主页、GitHub Pages、发布新版本、打 tag、Release 里放安装包、自动更新、发布脚本、检查发布结果、release 失败排查、项目宣传页。功能代码本身不归它管。
---

# GitHub 项目主页与发布

**主页和发布是两条线，各自一个入口。** 主页是「README 渲染进一个带首屏的模板，推主分支就更新」；
发布是「一条脚本改版本号、打 tag、推上去，Actions 构建并直接发成正式 Release」。两条线都不手工点网页，
网页上只做一次性的设置（开 Pages、加 Secret）。功能代码怎么写不归这个技能管。

**什么时候动手：** 发布要推主分支和 tag，推上去就是公开的。只在用户明确说要发、版本号由用户定的时候做；
无人值守时不发布，等人回来。这和 `running-experiments-on-branches` 里「改主分支的事等人回来」是同一条。
下文的「主分支」指项目实际用的那条（main 或 master）。

先看项目里有没有现成的东西：`site/`、`index.html`、`.github/workflows/`、`scripts/release.*`、
版本号出现在哪几个文件。有就沿用，缺什么补什么，不另起一套。

## 主页：README 是唯一内容源

README 是给人看的（安装、使用、方法），页面只从它生成；给 Agent 的项目说明在 `PROJECT.md`，不进页面。

页面从上到下固定四段：**首屏（banner）→ 下载或安装 → 带插图的使用场景 → README 全文**。
首屏和下载卡片写在模板里，后两段来自 README：使用场景就是 README 里「一张图配一段话」的那些小节，
README 从第一个二级标题起整段渲染进去，所以 README 写好，页面就有了。不要在页面里另写一份介绍，
两处文案会慢慢对不上。

做法、模板骨架和生成脚本见 [references/project-page.md](references/project-page.md)。要点：

- 生成脚本把 README 渲染成 HTML 填进模板，写出根目录的 `index.html`；相对链接改成指向 GitHub 上的文件，
  插图直接用仓库里的 `assets/`。生成物一起提交，只改源文件页面不会变。
- 下载卡片不写具体版本号，链接指向 Releases 页，这样发新版不用改页面。
- 根目录放 `.nojekyll`，Pages 原样发布，不过 Jekyll。
- Pages 的来源有两种，**只能二选一**，选错就一直 404：「Deploy from a branch」选主分支根目录，无需工作流；
  「GitHub Actions」要仓库里有部署工作流（模板在参考文档里）。仓库 `has_pages` 为真但没有任何
  `pages build and deployment` 运行记录，就是来源没选对。

## 发布：一条脚本，一个 tag，直接出正式 Release

**流程固定成脚本**（`scripts/release.py <版本>`），人只决定版本号：

1. 门槛检查：在主分支、工作区干净、和远端一致、tag 不存在、新版本号比旧的高。有一条不满足就停，什么都不改。
2. 先跑构建检查（页面能构建、代码能编过），再改文件——失败时工作区还是干净的。
3. 版本号出现在几处就改几处（`package.json`、`Cargo.toml`、`Cargo.lock`、应用配置、代码里的常量……），
   用正则定位，没找到就报错，别静默跳过。
4. 重新生成主页，提交「发布 vX.Y.Z」，打 tag，把主分支和 tag 一起推上去（`git push origin <主分支> vX.Y.Z`）。

工作流（`.github/workflows/release.yml`）由 `v*` 的 tag 触发：按平台矩阵构建 → 产物改成英文文件名
（中文文件名会被 GitHub 改掉）→ `softprops/action-gh-release` 直接发正式 Release（`draft: false`）。
**不出草稿。** 草稿只有登录的仓库主人看得见，公开接口回 404，用户、主页的下载按钮、应用里的更新检查
全都看不到它，很容易以为「发了但没生效」。发错了按下面「交付检查」的两条原则处理。
`workflow_dispatch` 留着只构建不发布，用来试工作流。

通用工作流模板、脚本模板、发布后的检查命令和排查表见 [references/release-pipeline.md](references/release-pipeline.md)。

**GitHub 的具体要求以官方文档为准，动手前查一遍**：Actions 的各步骤版本（`actions/checkout`、
`setup-node`、`upload-artifact`、`deploy-pages` 的当前大版本和 Node 版本要求）、Pages 的来源设置、
Secret 的限制（不能是空值）。查 <https://docs.github.com/actions> 和 <https://docs.github.com/pages>，
把当时查到的版本写进工作流，不凭记忆。黄色的 Node 版本弃用警告不是错误，不用为它改东西。

## 桌面应用（Tauri）：安装包之外还要有更新包

用户装了一次之后应该不用再去网页。做法是 Tauri 的 updater 插件：应用读 Release 里的 `latest.json`，
比版本号，下载对应平台的更新包，校验签名后装上并重启。这意味着发布时除了 dmg/exe，还要有
`.app.tar.gz`（macOS）、安装包的 `.sig`、以及列出各平台地址和签名的 `latest.json`。

签名密钥只生成一次，私钥放仓库外并备份——**私钥丢了，所有已装出去的版本都再也收不到更新**。
公钥写进应用配置，私钥放仓库 Secret 给 Actions 用。

接入步骤、`latest.json` 的格式、本机如何用假服务器完整验证一次「下载→装上→重启」、以及踩过的坑
（Windows 特性门、工具链版本、草稿不触发更新），见 [references/tauri-desktop.md](references/tauri-desktop.md)。

## 交付检查：推完 tag 不算发完

推完 tag 后逐项核对，再向用户汇报。每一项的命令和失败对照表见
[references/release-pipeline.md](references/release-pipeline.md)「发布后的检查」。

**成没成功**
- tag 触发的 Actions 跑完，各平台的构建和 release 作业都是绿的。用 `gh run watch <运行 ID> --exit-status`
  阻塞等它跑完，不写循环去轮询。
- tag 在远端，指向「发布 vX.Y.Z」那个提交。
- 不登录也看得到：匿名接口 `releases/latest` 返回的就是这个版本（草稿查不到，预发布不算 latest）。
- 用了主页的话，Pages 的部署记录也是绿的。

**内容对不对**
- 照工作流的平台矩阵列出应有的文件，逐个核对：在不在、大小不为 0、文件名带这次的版本号。
- Tauri：`latest.json` 的版本号对，每个平台的地址能下载，签名不为空。
- Release 正文写了各平台怎么装。

**失败了怎么办，先分清公没公开：**
- **还没公开**（release 作业被跳过、没出 Release、只有草稿）：没人拿到过，修好后把 tag 挪到新提交，
  用同一个版本号重发。
- **已经公开**：不挪 tag、不删 Release，修好后发下一个补丁版本。坏版本一时修不好，先标成预发布
  （`gh release edit vX.Y.Z --prerelease`）：`latest` 退回上一个正式版，自动更新也不再推它。
- 删 Release、删或挪 tag、强推，都是对外的、撤不回来的动作，先问用户。

**汇报**：版本号；Actions 链接和每个作业的结果；Release 链接；文件清单（应有几个、实有几个、各多大）；
自动更新和主页的结果。没过的项写清卡在哪一步、建议怎么办、哪些动作要用户点头。

常见现象先看哪里：
- Release 里没东西：Actions 有没有跑、跑到哪步红了；release 作业在 build 后面，任一平台失败它就跳过。
- 主页 404：Pages 来源；有没有部署记录；`.nojekyll` 在不在；根目录有没有 `index.html`。
- 应用说「已是最新」但明明发了：发的是不是草稿；`latest.json` 在不在 Release 里；应用里的公钥和签名用的私钥是否一对。
- 读失败日志：`gh run view <运行 ID> --log-failed`。没装 gh 又没登录时看不到 Actions 日志，让用户贴那一步的最后几十行。
