#!/usr/bin/env python3
"""清理公开发布前不应保留的本机路径和本地元数据。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="清理结果文件中的本机路径字段")
    parser.add_argument(
        "--root",
        default=".",
        help="项目根目录，默认当前目录",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def drop_keys(obj: dict[str, Any], keys: list[str]) -> None:
    for key in keys:
        obj.pop(key, None)


def sanitize_tags_localized(path: Path) -> None:
    data = read_json(path)
    metadata = data.get("metadata", {})
    if isinstance(metadata, dict):
        drop_keys(metadata, ["localized_with_reference", "source_input", "source_reference"])
    write_json(path, data)


def sanitize_topics(path: Path) -> None:
    data = read_json(path)
    metadata = data.get("metadata", {})
    if isinstance(metadata, dict):
        drop_keys(metadata, ["checkpoint_path"])
    write_json(path, data)


def main() -> int:
    args = parse_args()
    root = Path(args.root).expanduser().resolve()

    targets = [
        root / "results" / "latest" / "steam_tags_with_top_games_localized.json",
        root / "results" / "latest" / "steam_topics_with_top_works.json",
        root / "results" / "latest" / "steam_topics_only.json",
    ]

    for target in targets:
        if not target.exists():
            continue
        if target.name == "steam_tags_with_top_games_localized.json":
            sanitize_tags_localized(target)
        else:
            sanitize_topics(target)
        print(f"已清理: {target}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
