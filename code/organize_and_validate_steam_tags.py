#!/usr/bin/env python3
"""基于现有抓取结果生成中文版本，并校验网页端参考数据。"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


TAG_PATTERN = re.compile(r'data-tagid="(?P<tagid>\d+)">(?P<name>[^<]+)<')
PRICE_LINE_PATTERN = re.compile(r"^(¥\s*\d|免费开玩)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="整理 Steam 标签输出并校验网页端参考数据")
    parser.add_argument(
        "--input",
        default="steam_tags_with_top_games.json",
        help="原始汇总 JSON 文件路径",
    )
    parser.add_argument(
        "--tag-reference",
        default="all_type_reference.txt",
        help="网页端标签参考文件路径",
    )
    parser.add_argument(
        "--novel-reference",
        default="小说改编_reference.txt",
        help="网页端“小说改编”游戏参考文件路径",
    )
    parser.add_argument(
        "--localized-output",
        default="steam_tags_with_top_games_localized.json",
        help="中文整理版输出路径",
    )
    parser.add_argument(
        "--categories-json-output",
        default="steam_tag_categories_only.json",
        help="仅类别 JSON 输出路径",
    )
    parser.add_argument(
        "--categories-text-output",
        default="steam_tag_categories_only.txt",
        help="仅类别 TXT 输出路径",
    )
    parser.add_argument(
        "--validation-output",
        default="steam_validation_report.json",
        help="校验报告 JSON 输出路径",
    )
    parser.add_argument(
        "--validation-text-output",
        default="steam_validation_report.txt",
        help="校验报告 TXT 输出路径",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_tag_reference(path: Path) -> list[dict[str, Any]]:
    content = path.read_text(encoding="utf-8")
    tags: list[dict[str, Any]] = []
    for match in TAG_PATTERN.finditer(content):
        tags.append(
            {
                "tagid": int(match.group("tagid")),
                "name_cn": match.group("name").strip(),
            }
        )
    return tags


def parse_novel_reference(path: Path) -> list[str]:
    titles: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if PRICE_LINE_PATTERN.match(line):
            continue
        titles.append(line)
    return titles


def localize_tags(
    source_tags: list[dict[str, Any]],
    tag_reference: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reference_by_id = {item["tagid"]: item["name_cn"] for item in tag_reference}
    localized: list[dict[str, Any]] = []
    missing_localization: list[dict[str, Any]] = []

    for tag in source_tags:
        tag_id = tag.get("tagid")
        name_en = tag.get("name")
        name_cn = reference_by_id.get(tag_id)
        existing_name_en = tag.get("name_en")

        new_tag = dict(tag)
        if name_cn:
            if existing_name_en:
                new_tag["name_en"] = existing_name_en
            elif isinstance(name_en, str) and name_en.strip() != name_cn:
                new_tag["name_en"] = name_en
            else:
                new_tag["name_en"] = None
            new_tag["name"] = name_cn
            new_tag["name_cn"] = name_cn
        else:
            missing_localization.append({"tagid": tag_id, "name": name_en})
            new_tag["name_cn"] = None
            new_tag["name_en"] = existing_name_en or name_en

        localized.append(new_tag)

    return localized, missing_localization


def build_categories_only(tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "tagid": tag.get("tagid"),
            "name": tag.get("name"),
            "name_en": tag.get("name_en"),
        }
        for tag in tags
    ]


def validate_tag_reference(
    localized_tags: list[dict[str, Any]],
    tag_reference: list[dict[str, Any]],
) -> dict[str, Any]:
    localized_by_id = {item["tagid"]: item.get("name") for item in localized_tags}
    reference_by_id = {item["tagid"]: item["name_cn"] for item in tag_reference}

    localized_ids = set(localized_by_id)
    reference_ids = set(reference_by_id)

    missing_in_output = sorted(reference_ids - localized_ids)
    extra_in_output = sorted(localized_ids - reference_ids)

    name_mismatches: list[dict[str, Any]] = []
    for tag_id in sorted(localized_ids & reference_ids):
        output_name = (localized_by_id.get(tag_id) or "").strip()
        reference_name = reference_by_id[tag_id].strip()
        if output_name != reference_name:
            name_mismatches.append(
                {
                    "tagid": tag_id,
                    "output_name": output_name,
                    "reference_name": reference_name,
                }
            )

    return {
        "reference_count": len(tag_reference),
        "output_count": len(localized_tags),
        "missing_in_output": missing_in_output,
        "extra_in_output": extra_in_output,
        "name_mismatches": name_mismatches,
    }


def validate_novel_tag(source_tags: list[dict[str, Any]], novel_reference_titles: list[str]) -> dict[str, Any]:
    novel_tag = next((tag for tag in source_tags if tag.get("tagid") == 3796), None)
    if not novel_tag:
        return {
            "tagid": 3796,
            "tag_found": False,
            "reference_titles": novel_reference_titles,
            "output_titles": [],
            "missing_titles": novel_reference_titles,
            "unexpected_titles": [],
            "matched_titles": [],
        }

    output_titles = [game.get("name") for game in novel_tag.get("typical_games", []) if game.get("name")]
    output_title_set = set(output_titles)
    reference_title_set = set(novel_reference_titles)

    matched_titles = [title for title in novel_reference_titles if title in output_title_set]
    missing_titles = [title for title in novel_reference_titles if title not in output_title_set]
    unexpected_titles = [title for title in output_titles if title not in reference_title_set]

    return {
        "tagid": 3796,
        "tag_found": True,
        "tag_name": novel_tag.get("name"),
        "reference_count": len(novel_reference_titles),
        "output_count": len(output_titles),
        "reference_titles": novel_reference_titles,
        "output_titles": output_titles,
        "matched_titles": matched_titles,
        "missing_titles": missing_titles,
        "unexpected_titles": unexpected_titles,
        "match_ratio": round(len(matched_titles) / len(novel_reference_titles), 4) if novel_reference_titles else 1.0,
    }


def render_validation_text(report: dict[str, Any]) -> str:
    tag_validation = report["tag_validation"]
    novel_validation = report["novel_tag_validation"]

    lines = [
        "Steam 标签整理校验报告",
        f"生成时间: {report['generated_at']}",
        "",
        "一、标签总表校验",
        f"网页参考标签数: {tag_validation['reference_count']}",
        f"整理后输出标签数: {tag_validation['output_count']}",
        f"缺失标签数: {len(tag_validation['missing_in_output'])}",
        f"额外标签数: {len(tag_validation['extra_in_output'])}",
        f"名称不一致数: {len(tag_validation['name_mismatches'])}",
        "",
        "二、“小说改编”校验",
        f"网页参考游戏数: {novel_validation['reference_count']}",
        f"当前输出游戏数: {novel_validation['output_count']}",
        f"匹配游戏数: {len(novel_validation['matched_titles'])}",
        f"匹配率: {novel_validation['match_ratio']}",
        "",
        "网页参考游戏:",
        *[f"- {title}" for title in novel_validation["reference_titles"]],
        "",
        "当前输出游戏:",
        *[f"- {title}" for title in novel_validation["output_titles"]],
        "",
        "未匹配到的网页参考游戏:",
        *([f"- {title}" for title in novel_validation["missing_titles"]] or ["- 无"]),
        "",
        "当前输出里多出的游戏:",
        *([f"- {title}" for title in novel_validation["unexpected_titles"]] or ["- 无"]),
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()

    input_path = Path(args.input).expanduser().resolve()
    tag_reference_path = Path(args.tag_reference).expanduser().resolve()
    novel_reference_path = Path(args.novel_reference).expanduser().resolve()

    source_data = read_json(input_path)
    source_tags = source_data.get("tags", [])
    if not isinstance(source_tags, list):
        raise RuntimeError("输入 JSON 缺少 tags 列表")

    tag_reference = parse_tag_reference(tag_reference_path)
    novel_reference_titles = parse_novel_reference(novel_reference_path)

    localized_tags, missing_localization = localize_tags(source_tags, tag_reference)
    categories_only = build_categories_only(localized_tags)

    localized_payload = {
        "metadata": {
            **source_data.get("metadata", {}),
            "generated_at": datetime.now(tz=UTC).isoformat(),
        },
        "tags": localized_tags,
    }

    categories_payload = {
        "metadata": {
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "tag_count": len(categories_only),
        },
        "tags": categories_only,
    }

    tag_validation = validate_tag_reference(localized_tags, tag_reference)
    novel_validation = validate_novel_tag(localized_tags, novel_reference_titles)

    validation_report = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "missing_localization_entries": missing_localization,
        "tag_validation": tag_validation,
        "novel_tag_validation": novel_validation,
    }

    categories_text = "\n".join(
        f"{item['tagid']}\t{item['name']}" for item in categories_only
    ) + "\n"

    write_json(Path(args.localized_output).expanduser().resolve(), localized_payload)
    write_json(Path(args.categories_json_output).expanduser().resolve(), categories_payload)
    write_text(Path(args.categories_text_output).expanduser().resolve(), categories_text)
    write_json(Path(args.validation_output).expanduser().resolve(), validation_report)
    write_text(
        Path(args.validation_text_output).expanduser().resolve(),
        render_validation_text(validation_report),
    )

    print(f"已生成中文整理版: {Path(args.localized_output).expanduser().resolve()}")
    print(f"已生成仅类别 JSON: {Path(args.categories_json_output).expanduser().resolve()}")
    print(f"已生成仅类别 TXT: {Path(args.categories_text_output).expanduser().resolve()}")
    print(f"已生成校验报告 JSON: {Path(args.validation_output).expanduser().resolve()}")
    print(f"已生成校验报告 TXT: {Path(args.validation_text_output).expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
