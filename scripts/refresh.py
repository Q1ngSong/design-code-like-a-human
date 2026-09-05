#!/usr/bin/env python3
"""comment_standard 的命令入口。

科研环境里不能指望 pip install，所以这里把 `scripts/` 塞进 sys.path，
`python3 <插件>/scripts/refresh.py <项目>` 直接可跑。

`Path(__file__).resolve()` 会解开软链，所以软链进 PATH 起个短名字也能用。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from comment_standard.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
