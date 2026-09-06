"""把 .comment-standard.json 里的 codegraph 段写出成 codegraph.json。

两处配置说的是同一件事(哪些目录算这个项目的源码),让用户维护两份必然不同步。
所以只维护一处:`.comment-standard.json` 的 `codegraph` 键是唯一事实来源,
`codegraph.json` 由我们生成、每次刷新覆盖。

例外是配置里没有 `codegraph` 段的时候 —— 那时不碰已存在的 codegraph.json,
因为分不清它是我们早先生成的、还是用户自己写的。

写出必须发生在 `codegraph sync` **之前** —— 否则这次同步仍按旧配置建索引,
改动要下一次才生效。
"""
import json

FILENAME = "codegraph.json"


def sync(proj):
    """把 codegraph 段写出到 codegraph.json。[主线]

    Args:
        proj: Project 实例。

    Returns:
        str，面向用户的一行状态；无事发生时返回 None。

    声明了 `codegraph` 段就无条件覆盖 —— 不做「内容相同就跳过」的优化，
    反正紧接着的 sync 每次都会重读配置，省下的那次写入不换来任何东西。

    没声明时**不删**已存在的 codegraph.json：用户可能在用本工具之前就自己
    写过它，删掉是毁数据。这时只报告一句，让用户自己决定。
    """
    path = proj.root / FILENAME
    desired = proj.codegraph

    if desired is None:   # 只有「没写这个键」才不管;写了 {} 是显式回到默认,要覆盖
        if path.is_file():
            return (f"{FILENAME} 存在，但 .comment-standard.json 里没有 codegraph 段"
                    f"——它不受本工具管理，内容以磁盘上那份为准")
        return None

    existed = path.is_file()
    path.write_text(
        json.dumps(desired, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    verb = "已更新" if existed else "已生成"
    return f"{verb} {FILENAME}（来自 .comment-standard.json 的 codegraph 段）"
