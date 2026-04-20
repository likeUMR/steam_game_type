#!/usr/bin/env python3
"""把 Steam tag JSON 转成便于人工浏览的三行文本格式。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将 steam_tags_with_top_games_localized.json 转成三行一组的文本文件。"
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="results/latest/steam_tags_with_top_games_localized.json",
        help="输入 JSON 文件路径",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="输出文本文件路径，默认与输入文件同目录同名加 _review.txt",
    )
    parser.add_argument(
        "--separator",
        default="；",
        help="游戏名之间的分隔符，默认使用中文分号",
    )
    return parser.parse_args()


def load_tags(input_path: Path) -> list[dict[str, Any]]:
    with input_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    tags = payload.get("tags")
    if not isinstance(tags, list):
        raise ValueError("输入文件缺少 tags 数组，无法继续处理。")
    return tags


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def build_lines(tags: list[dict[str, Any]], separator: str) -> list[str]:
    lines: list[str] = []
    for tag in tags:
        tag_name = normalize_text(tag.get("name")) or "未命名标签"
        total_games = normalize_text(tag.get("total_games")) or "0"

        game_names: list[str] = []
        for game in tag.get("typical_games", []):
            if not isinstance(game, dict):
                continue
            game_name = normalize_text(game.get("name"))
            if game_name:
                game_names.append(game_name)

        lines.extend(
            [
                f"《{tag_name}》",
                total_games,
                separator.join(game_names),
                "",
            ]
        )
    return lines


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else input_path.with_name(f"{input_path.stem}_review.txt")
    )

    tags = load_tags(input_path)
    lines = build_lines(tags, args.separator)

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已生成: {output_path}")
    print(f"标签数量: {len(tags)}")


if __name__ == "__main__":
    main()
