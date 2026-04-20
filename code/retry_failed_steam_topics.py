#!/usr/bin/env python3
"""只重试 Steam 主题抓取中的失败项，并合并回现有结果。"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fetch_steam_topics import (
    TOPIC_DEFINITIONS,
    SteamClient,
    fetch_topic_bundle,
    normalize_app_details,
    save_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="重试 Steam 主题抓取失败项")
    parser.add_argument(
        "--input",
        default="results/latest/steam_topics_with_top_works.json",
        help="现有主题结果文件路径",
    )
    parser.add_argument(
        "--topics-only-output",
        default="results/latest/steam_topics_only.json",
        help="主题列表输出路径",
    )
    parser.add_argument(
        "--country-code",
        default="HK",
        help="国家代码，默认 HK",
    )
    parser.add_argument(
        "--language",
        default="schinese",
        help="语言代码，默认 schinese",
    )
    parser.add_argument(
        "--works-per-topic",
        type=int,
        default=25,
        help="每个主题保留的热门作品数，默认 25",
    )
    parser.add_argument(
        "--topic-delay",
        type=float,
        default=0.2,
        help="主题接口请求间隔，默认 0.2 秒",
    )
    parser.add_argument(
        "--work-delay",
        type=float,
        default=1.2,
        help="作品详情请求间隔，默认 1.2 秒",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=5,
        help="重试次数，默认 5",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=2.0,
        help="失败后的基础等待秒数，默认 2.0",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_topic_payload(bundle: dict[str, Any], app_details_by_id: dict[int, dict[str, Any]], works_per_topic: int) -> dict[str, Any]:
    definition = bundle["topic_definition"]
    page_info = bundle["page_info"]
    metadata = bundle["metadata"]
    top_sellers = bundle["top_sellers"]
    appids = bundle["appids"][:works_per_topic]
    return {
        "name": definition["name"],
        "slug": definition["slug"],
        "group": definition["group"],
        "title_en": metadata.get("title"),
        "subtitle_en": metadata.get("subtitle"),
        "topic_url": page_info["topic_url"],
        "works_source": {
            "method": "saleaction/ajaxgetsaledynamicappquery",
            "flavor": "contenthub_topsellers",
            "announcement_gid": page_info.get("announcement_gid"),
        },
        "match_count": top_sellers.get("match_count"),
        "possible_has_more": top_sellers.get("possible_has_more"),
        "hot_works_count": len(appids),
        "hot_works": [app_details_by_id[appid] for appid in appids if appid in app_details_by_id],
    }


def topic_definition_by_name(name: str) -> dict[str, Any] | None:
    for item in TOPIC_DEFINITIONS:
        if item["name"] == name:
            return item
    return None


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    topics_only_output_path = Path(args.topics_only_output).expanduser().resolve()

    data = read_json(input_path)
    topics: list[dict[str, Any]] = data.get("topics", [])
    failed_topics: list[dict[str, Any]] = data.get("failed_topics", [])
    failed_works: list[dict[str, Any]] = data.get("failed_works", [])

    topic_client = SteamClient(
        language=args.language,
        country_code=args.country_code,
        timeout=30,
        retries=args.retries,
        retry_delay=args.retry_delay,
        request_delay=args.topic_delay,
    )
    work_client = SteamClient(
        language=args.language,
        country_code=args.country_code,
        timeout=30,
        retries=args.retries,
        retry_delay=args.retry_delay,
        request_delay=args.work_delay,
    )

    topic_map = {topic["name"]: topic for topic in topics}
    detail_map: dict[int, dict[str, Any]] = {}
    for topic in topics:
        for work in topic.get("hot_works", []):
            appid = work.get("appid")
            if isinstance(appid, int):
                detail_map[appid] = work

    remaining_failed_topics: list[dict[str, Any]] = []
    retried_topic_appids: set[int] = set()

    for item in failed_topics:
        definition = topic_definition_by_name(item["name"])
        if not definition:
            remaining_failed_topics.append(item)
            continue
        try:
            bundle = fetch_topic_bundle(topic_client, definition, args.works_per_topic)
            retried_topic_appids.update(bundle["appids"])
            print(f"已重试成功主题: {definition['name']} ({definition['slug']})", flush=True)
            # 暂时先占位，等 app 详情补完再统一组装
            topic_map[definition["name"]] = {"__bundle__": bundle}
        except Exception as exc:
            remaining_failed_topics.append(
                {
                    "name": definition["name"],
                    "slug": definition["slug"],
                    "group": definition["group"],
                    "error": str(exc),
                }
            )
            print(f"主题仍失败: {definition['name']} ({definition['slug']}): {exc}", flush=True)

    failed_work_ids = {item["appid"] for item in failed_works if isinstance(item.get("appid"), int)}
    pending_work_ids = sorted(failed_work_ids | retried_topic_appids)
    remaining_failed_works: list[dict[str, Any]] = []

    for index, appid in enumerate(pending_work_ids, start=1):
        try:
            details = normalize_app_details(appid, work_client.fetch_app_details(appid))
            detail_map[appid] = details
            print(f"[{index}/{len(pending_work_ids)}] 已补作品详情 {appid}", flush=True)
        except Exception as exc:
            remaining_failed_works.append({"appid": appid, "error": str(exc)})
            print(f"[{index}/{len(pending_work_ids)}] 作品仍失败 {appid}: {exc}", flush=True)

    rebuilt_topics: list[dict[str, Any]] = []
    for definition in TOPIC_DEFINITIONS:
        name = definition["name"]
        topic = topic_map.get(name)
        if not topic:
            continue
        if "__bundle__" in topic:
            rebuilt_topics.append(build_topic_payload(topic["__bundle__"], detail_map, args.works_per_topic))
        else:
            topic["hot_works"] = [
                detail_map[work["appid"]]
                for work in topic.get("hot_works", [])
                if isinstance(work.get("appid"), int) and work["appid"] in detail_map
            ]
            topic["hot_works_count"] = len(topic["hot_works"])
            rebuilt_topics.append(topic)

    data["metadata"]["generated_at"] = datetime.now(tz=UTC).isoformat()
    data["metadata"]["topic_count"] = len(rebuilt_topics)
    data["metadata"]["failed_topic_count"] = len(remaining_failed_topics)
    data["metadata"]["failed_work_count"] = len(remaining_failed_works)
    data["failed_topics"] = remaining_failed_topics
    data["failed_works"] = remaining_failed_works
    data["topics"] = rebuilt_topics
    save_json(input_path, data)

    topics_only_payload = {
        "metadata": {
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "language": data["metadata"]["language"],
            "country_code": data["metadata"]["country_code"],
            "topic_count": len(rebuilt_topics),
            "failed_topic_count": len(remaining_failed_topics),
            "failed_work_count": len(remaining_failed_works),
        },
        "failed_topics": remaining_failed_topics,
        "failed_works": remaining_failed_works,
        "topics": [
            {
                "name": item["name"],
                "slug": item["slug"],
                "group": item["group"],
                "title_en": item.get("title_en"),
                "topic_url": item.get("topic_url"),
                "match_count": item.get("match_count"),
            }
            for item in rebuilt_topics
        ],
    }
    save_json(topics_only_output_path, topics_only_payload)

    print(f"已更新主题结果: {input_path}")
    print(f"已更新主题列表: {topics_only_output_path}")
    print(f"剩余失败主题: {len(remaining_failed_topics)}")
    print(f"剩余失败作品: {len(remaining_failed_works)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
