# 项目主页

## 文件

| 文件 | 内容 |
|---|---|
| `site/index.html` | 模板：首屏、下载卡片写死在这里，`__README__` 占位 |
| `site/style.css` | 样式，配色和 `assets/` 里的插图一致，跟系统深浅色 |
| `site/build.py` | 把 README 渲染进模板，写出根目录 `index.html` |
| `assets/*.svg` | README 和页面共用的插图（首屏主图、每个使用场景一张） |
| 根目录 `index.html`、`.nojekyll` | 生成物和 Pages 开关，都要提交 |

## 四段结构

1. **首屏**：一句话标题（项目解决什么）、一两行说明、两个按钮（下载 → `#download`，GitHub → 仓库）、一张主图、一行标签（平台 / 体积 / 依赖）。
2. **下载或安装**：每个平台一张卡片，写文件名的模式（`PluginHub_<版本>_universal.dmg`）不写具体版本，链接到 `…/releases`。安装注意事项（未签名怎么打开、需要哪些依赖）写在卡片下面一句。
3. **使用场景**：README 里「一张图配一段话」的小节，页面上不单独做，随 README 渲染。写 README 时就按这个格式：`![场景说明](assets/xxx.svg)` 后面紧跟一段话。
4. **README 全文**：从第一个二级标题开始（标题、介绍、主图已在首屏），二级标题加 id 供页内跳转。

## 生成脚本骨架

```python
"""生成项目主页：把根目录的 README.md 渲染成 HTML，填进 site/index.html 模板，写到根目录的 index.html。"""
import re
from pathlib import Path
from urllib.parse import urljoin
from markdown_it import MarkdownIt          # pip install markdown-it-py

ROOT = Path(__file__).resolve().parents[1]
README_URL = "https://github.com/<owner>/<repo>/blob/main/README.md"

text = (ROOT / "README.md").read_text(encoding="utf-8")
readme = MarkdownIt("commonmark").enable("table").render(text[text.index("\n## "):])
readme = re.sub(r'href="([^"]+)"', lambda m: f'href="{urljoin(README_URL, m.group(1))}"', readme)  # 相对链接指向 GitHub
readme = re.sub(r"<h2>([^<]+)</h2>", r'<h2 id="\1">\1</h2>', readme)                                 # 二级标题可跳转
template = (ROOT / "site/index.html").read_text(encoding="utf-8")
(ROOT / "index.html").write_text(template.replace("__README__", readme), encoding="utf-8")
```

本地预览：`python3 site/build.py && python3 -m http.server 8770`。发布脚本每次发版都重新生成一次，README 改了页面才会跟着改。

## Pages 两种来源

**Deploy from a branch**：Settings → Pages → Source 选 Deploy from a branch → `main` / `/ (root)`。保存后 Actions 里立刻出现一条 `pages build and deployment`，之后每次推 main 自动更新。最省事。

**GitHub Actions**：仓库里要有部署工作流，只发页面用得到的文件，不把源码整个放上去：

```yaml
name: pages
on:
  push:
    branches: [main]
    paths: [index.html, assets/**, site/**, .github/workflows/pages.yml]
  workflow_dispatch:
permissions: { contents: read, pages: write, id-token: write }
concurrency: { group: pages, cancel-in-progress: true }
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: { name: github-pages, url: ${{ steps.deploy.outputs.page_url }} }
    steps:
      - uses: actions/checkout@v4
      - run: |
          mkdir -p public/site
          cp index.html .nojekyll public/
          cp -r assets public/
          cp site/style.css public/site/
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with: { path: public }
      - id: deploy
        uses: actions/deploy-pages@v4
```

`deploy-pages` 偶尔报「No artifacts named github-pages were found」而产物明明在，是 GitHub 那边的瞬时故障，重跑即可。步骤的大版本动手前到官方文档核对一次。
