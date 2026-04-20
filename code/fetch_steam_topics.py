#!/usr/bin/env python3
"""抓取 Steam 所有主题及每个主题前 25 个热门作品。"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}

CONTENT_HUB_URL = "https://store.steampowered.com/contenthub/ajaxgetcontenthubdata"
TOPIC_QUERY_URL = "https://store.steampowered.com/saleaction/ajaxgetsaledynamicappquery"
APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
CATEGORY_PAGE_URL_TEMPLATE = "https://store.steampowered.com/category/{slug}/"

# 这个 content hub 账号是 Steam 官方 store_contenthubs 页面本身，不涉及用户登录态。
STORE_CONTENT_HUB_CLAN_ID = 41316928
TOPIC_SECTION_UNIQUE_ID = 13268
TOPIC_TAB_UNIQUE_ID = 6
TOPIC_FLAVOR = "contenthub_topsellers"
ANNOUNCEMENT_GID_PATTERN = re.compile(r'data-event="\{&quot;ANNOUNCEMENT_GID&quot;:&quot;(?P<gid>\d+)&quot;')


TOPIC_DEFINITIONS: list[dict[str, Any]] = [
    {"name": "第一人称射击", "slug": "action_fps", "group": "动作"},
    {"name": "第三人称射击", "slug": "action_tps", "group": "动作"},
    {"name": "砍杀", "slug": "hack_and_slash", "group": "动作"},
    {"name": "街机及节奏", "slug": "arcade_rhythm", "group": "动作"},
    {"name": "平台及奔跑", "slug": "action_run_jump", "group": "动作"},
    {"name": "清版射击", "slug": "shmup", "group": "动作"},
    {"name": "格斗及武术", "slug": "fighting_martial_arts", "group": "动作"},
    {"name": "隐藏物体", "slug": "hidden_object", "group": "冒险与叙事"},
    {"name": "休闲", "slug": "casual", "group": "冒险与叙事"},
    {"name": "类银河战士恶魔城", "slug": "metroidvania", "group": "冒险与叙事"},
    {"name": "解谜", "slug": "puzzle_matching", "group": "冒险与叙事"},
    {"name": "冒险角色扮演", "slug": "adventure_rpg", "group": "冒险与叙事"},
    {"name": "视觉小说", "slug": "visual_novel", "group": "冒险与叙事"},
    {"name": "剧情丰富", "slug": "story_rich", "group": "冒险与叙事"},
    {"name": "动作角色扮演", "slug": "rpg_action", "group": "角色扮演"},
    {"name": "策略及战术角色扮演", "slug": "rpg_strategy_tactics", "group": "角色扮演"},
    {"name": "日系角色扮演", "slug": "rpg_jrpg", "group": "角色扮演"},
    {"name": "类 Rogue 及轻度 Rogue", "slug": "rogue_like_rogue_lite", "group": "角色扮演"},
    {"name": "回合制角色扮演", "slug": "rpg_turn_based", "group": "角色扮演"},
    {"name": "团队制", "slug": "rpg_party_based", "group": "角色扮演"},
    {"name": "建造及自动化模拟", "slug": "sim_building_automation", "group": "模拟"},
    {"name": "爱好与工作模拟", "slug": "sim_hobby_sim", "group": "模拟"},
    {"name": "恋爱模拟", "slug": "sim_dating", "group": "模拟"},
    {"name": "农场及制作模拟", "slug": "sim_farming_crafting", "group": "模拟"},
    {"name": "太空及飞行模拟", "slug": "sim_space_flight", "group": "模拟"},
    {"name": "生活及沉浸式模拟", "slug": "sim_life", "group": "模拟"},
    {"name": "沙盒及物理模拟", "slug": "sim_physics_sandbox", "group": "模拟"},
    {"name": "回合制策略", "slug": "strategy_turn_based", "group": "策略"},
    {"name": "即时战略", "slug": "strategy_real_time", "group": "策略"},
    {"name": "塔防", "slug": "tower_defense", "group": "策略"},
    {"name": "卡牌及桌游", "slug": "strategy_card_board", "group": "策略"},
    {"name": "城市及定居点营造", "slug": "strategy_cities_settlements", "group": "策略"},
    {"name": "大战略及 4X", "slug": "strategy_grand_4x", "group": "策略"},
    {"name": "军事战略", "slug": "strategy_military", "group": "策略"},
    {"name": "体育模拟及体育管理", "slug": "sports_sim", "group": "体育与竞速"},
    {"name": "竞速", "slug": "racing", "group": "体育与竞速"},
    {"name": "竞速模拟", "slug": "racing_sim", "group": "体育与竞速"},
    {"name": "钓鱼及狩猎", "slug": "sports_fishing_hunting", "group": "体育与竞速"},
    {"name": "团队体育", "slug": "sports_team", "group": "体育与竞速"},
    {"name": "单人运动", "slug": "sports_individual", "group": "体育与竞速"},
    {"name": "体育", "slug": "sports", "group": "体育与竞速"},
    {"name": "恐怖", "slug": "horror", "group": "主题"},
    {"name": "科幻及赛博朋克", "slug": "science_fiction", "group": "主题"},
    {"name": "太空", "slug": "space", "group": "主题"},
    {"name": "开放世界", "slug": "exploration_open_world", "group": "主题"},
    {"name": "动漫", "slug": "anime", "group": "主题"},
    {"name": "生存", "slug": "survival", "group": "主题"},
    {"name": "悬疑及推理", "slug": "mystery_detective", "group": "主题"},
]


@dataclass(slots=True)
class SteamClient:
    language: str
    country_code: str
    timeout: int
    retries: int
    retry_delay: float
    request_delay: float

    def get_text(self, url: str, params: dict[str, Any], headers: dict[str, str] | None = None) -> str:
        merged_headers = dict(DEFAULT_HEADERS)
        if headers:
            merged_headers.update(headers)

        query = urllib.parse.urlencode(params, doseq=True)
        request = urllib.request.Request(
            f"{url}?{query}",
            headers=merged_headers,
            method="GET",
        )

        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = response.read().decode("utf-8")
                if self.request_delay > 0:
                    time.sleep(self.request_delay)
                return payload
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                last_error = exc
                if attempt == self.retries:
                    break
                time.sleep(self.retry_delay * attempt)

        raise RuntimeError(f"请求失败: {url} -> {last_error}") from last_error

    def get_json(self, url: str, params: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            payload = self.get_text(url, params, headers=headers)
            try:
                return json.loads(payload)
            except json.JSONDecodeError as exc:
                last_error = exc
                if attempt == self.retries:
                    break
                time.sleep(self.retry_delay * attempt)
        raise RuntimeError(f"JSON 解析失败: {url} -> {last_error}") from last_error

    def fetch_topic_page_info(self, slug: str) -> dict[str, Any]:
        html_text = self.get_text(
            CATEGORY_PAGE_URL_TEMPLATE.format(slug=slug),
            {
                "cc": self.country_code,
                "l": self.language,
            },
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        )
        announcement_gid = None
        match = ANNOUNCEMENT_GID_PATTERN.search(html_text)
        if match:
            announcement_gid = match.group("gid")
        return {
            "topic_url": f"{CATEGORY_PAGE_URL_TEMPLATE.format(slug=slug)}?cc={self.country_code}&l={self.language}",
            "announcement_gid": announcement_gid,
        }

    def fetch_topic_metadata(self, slug: str) -> dict[str, Any]:
        data = self.get_json(
            CONTENT_HUB_URL,
            {
                "hubtype": "category",
                "category": slug,
            },
        )
        if data.get("success") != 1:
            raise RuntimeError(f"主题元数据获取失败: {slug}")
        return data

    def fetch_topic_top_sellers(self, slug: str, count: int, announcement_gid: str | None) -> dict[str, Any]:
        params = {
            "cc": self.country_code,
            "l": self.language,
            "rgExcludedContentDescriptors[]": ["3", "4"],
            "clanAccountID": STORE_CONTENT_HUB_CLAN_ID,
            "flavor": TOPIC_FLAVOR,
            "strFacetFilter": "",
            "start": 0,
            "count": count,
            "tabuniqueid": TOPIC_TAB_UNIQUE_ID,
            "sectionuniqueid": TOPIC_SECTION_UNIQUE_ID,
            "return_capsules": "true",
            "origin": "https://store.steampowered.com",
            "strContentHubType": "category",
            "strContentHubCategory": slug,
            "bContentHubDiscountedOnly": "false",
            "strTabFilter": "",
            "bRequestFacetCounts": "true",
            "bUseCreatorHomeApps": "false",
            "bAllowDemos": "false",
        }
        if announcement_gid:
            params["clanAnnouncementGID"] = announcement_gid

        data = self.get_json(TOPIC_QUERY_URL, params)
        if data.get("success") != 1:
            raise RuntimeError(f"主题热门作品获取失败: {slug}")
        return data

    def fetch_app_details(self, appid: int) -> dict[str, Any]:
        data = self.get_json(
            APPDETAILS_URL,
            {
                "appids": appid,
                "cc": self.country_code,
                "l": self.language,
            },
            headers={"Accept": "application/json"},
        )
        app_data = data.get(str(appid), {})
        if not app_data.get("success"):
            raise RuntimeError(f"作品详情获取失败: {appid}")
        return app_data.get("data", {})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抓取 Steam 所有主题及其前 25 个热门作品")
    parser.add_argument(
        "--output",
        default="steam_topics_with_top_works.json",
        help="输出 JSON 文件路径",
    )
    parser.add_argument(
        "--topics-only-output",
        default=None,
        help="仅主题列表输出 JSON 文件路径，可选",
    )
    parser.add_argument(
        "--checkpoint",
        default=None,
        help="断点续跑 checkpoint 文件路径，可选；默认与 output 同目录同名 .checkpoint.json",
    )
    parser.add_argument(
        "--language",
        default="schinese",
        help="Steam 语言代码，默认: schinese",
    )
    parser.add_argument(
        "--country-code",
        default="HK",
        help="Steam 国家代码，默认: HK",
    )
    parser.add_argument(
        "--works-per-topic",
        type=int,
        default=25,
        help="每个主题抓取的热门作品数量，默认: 25",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=6,
        help="并发线程数，默认: 6",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="单次请求超时时间（秒），默认: 30",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="请求失败重试次数，默认: 3",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=1.5,
        help="失败重试前的基础等待时间（秒），默认: 1.5",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.02,
        help="每次成功请求后的间隔（秒），默认: 0.02",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅抓取前 N 个主题，便于调试",
    )
    parser.add_argument(
        "--checkpoint-interval",
        type=int,
        default=10,
        help="每抓取多少个作品详情保存一次 checkpoint，默认: 10",
    )
    return parser.parse_args()


def price_to_text(price_overview: dict[str, Any] | None) -> str | None:
    if not price_overview:
        return None
    return price_overview.get("final_formatted") or price_overview.get("initial_formatted")


def normalize_app_details(appid: int, details: dict[str, Any]) -> dict[str, Any]:
    price_overview = details.get("price_overview")
    platforms = details.get("platforms", {})
    return {
        "appid": appid,
        "name": details.get("name"),
        "type": details.get("type"),
        "is_free": details.get("is_free", False),
        "store_url": f"https://store.steampowered.com/app/{appid}/",
        "header_image": details.get("header_image"),
        "short_description": details.get("short_description"),
        "developers": details.get("developers", []),
        "publishers": details.get("publishers", []),
        "price_text": "免费开玩" if details.get("is_free") else price_to_text(price_overview),
        "price_overview": {
            "currency": price_overview.get("currency") if price_overview else None,
            "initial": price_overview.get("initial") if price_overview else None,
            "final": price_overview.get("final") if price_overview else None,
            "discount_percent": price_overview.get("discount_percent") if price_overview else None,
            "initial_formatted": price_overview.get("initial_formatted") if price_overview else None,
            "final_formatted": price_overview.get("final_formatted") if price_overview else None,
        },
        "platforms": {
            "windows": platforms.get("windows", False),
            "mac": platforms.get("mac", False),
            "linux": platforms.get("linux", False),
        },
    }


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def default_checkpoint_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".checkpoint.json")


def load_checkpoint(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_checkpoint(
    path: Path,
    *,
    args: argparse.Namespace,
    topic_results: list[dict[str, Any]],
    failed_topics: list[dict[str, Any]],
    failed_appids: list[dict[str, Any]],
    app_details_by_id: dict[int, dict[str, Any]],
) -> None:
    serializable_app_details = {str(appid): details for appid, details in app_details_by_id.items()}
    payload = {
        "saved_at": datetime.now(tz=UTC).isoformat(),
        "config": {
            "language": args.language,
            "country_code": args.country_code,
            "works_per_topic": args.works_per_topic,
        },
        "topic_results": topic_results,
        "failed_topics": failed_topics,
        "failed_appids": failed_appids,
        "app_details_by_id": serializable_app_details,
    }
    save_json(path, payload)


def fetch_topic_bundle(
    client: SteamClient,
    topic_definition: dict[str, Any],
    works_per_topic: int,
) -> dict[str, Any]:
    slug = topic_definition["slug"]
    page_info = client.fetch_topic_page_info(slug)
    metadata = client.fetch_topic_metadata(slug)
    top_sellers = client.fetch_topic_top_sellers(slug, works_per_topic, page_info.get("announcement_gid"))

    top_seller_appids = [appid for appid in top_sellers.get("appids", []) if isinstance(appid, int)]
    return {
        "topic_definition": topic_definition,
        "page_info": page_info,
        "metadata": metadata,
        "top_sellers": top_sellers,
        "appids": top_seller_appids,
    }


def fetch_app_detail_entry(client: SteamClient, appid: int) -> tuple[int, dict[str, Any]]:
    return appid, normalize_app_details(appid, client.fetch_app_details(appid))


def main() -> int:
    args = parse_args()
    output_path = Path(args.output).expanduser().resolve()
    topics_only_output_path = (
        Path(args.topics_only_output).expanduser().resolve() if args.topics_only_output else None
    )
    checkpoint_path = (
        Path(args.checkpoint).expanduser().resolve()
        if args.checkpoint
        else default_checkpoint_path(output_path)
    )

    client = SteamClient(
        language=args.language,
        country_code=args.country_code,
        timeout=args.timeout,
        retries=args.retries,
        retry_delay=args.retry_delay,
        request_delay=args.delay,
    )

    topic_definitions = TOPIC_DEFINITIONS[: args.limit] if args.limit else TOPIC_DEFINITIONS[:]
    total_topics = len(topic_definitions)
    workers = max(1, min(args.workers, max(total_topics, 1)))

    checkpoint = load_checkpoint(checkpoint_path)
    topic_results_by_slug: dict[str, dict[str, Any]] = {}
    failed_topics_by_slug: dict[str, dict[str, Any]] = {}
    app_details_by_id: dict[int, dict[str, Any]] = {}
    failed_appids_by_id: dict[int, dict[str, Any]] = {}

    if checkpoint:
        for item in checkpoint.get("topic_results", []):
            if isinstance(item, dict) and item.get("topic_definition", {}).get("slug"):
                topic_results_by_slug[item["topic_definition"]["slug"]] = item
        for item in checkpoint.get("failed_topics", []):
            if isinstance(item, dict) and item.get("slug"):
                failed_topics_by_slug[item["slug"]] = item
        for appid, details in checkpoint.get("app_details_by_id", {}).items():
            try:
                app_details_by_id[int(appid)] = details
            except (TypeError, ValueError):
                continue
        for item in checkpoint.get("failed_appids", []):
            if isinstance(item, dict) and item.get("appid") is not None:
                failed_appids_by_id[int(item["appid"])] = item
        print(
            f"已加载 checkpoint：{len(topic_results_by_slug)} 个主题结果，"
            f"{len(failed_topics_by_slug)} 个失败主题，"
            f"{len(app_details_by_id)} 个作品详情，"
            f"{len(failed_appids_by_id)} 个失败作品",
            flush=True,
        )

    pending_topic_definitions = [
        topic_definition
        for topic_definition in topic_definitions
        if topic_definition["slug"] not in topic_results_by_slug
        and topic_definition["slug"] not in failed_topics_by_slug
    ]

    if pending_topic_definitions:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(fetch_topic_bundle, client, topic_definition, args.works_per_topic): topic_definition
                for topic_definition in pending_topic_definitions
            }

            completed = len(topic_results_by_slug) + len(failed_topics_by_slug)
            for future in concurrent.futures.as_completed(future_map):
                topic_definition = future_map[future]
                completed += 1
                slug = topic_definition["slug"]
                name = topic_definition["name"]
                try:
                    result = future.result()
                    topic_results_by_slug[slug] = result
                    print(f"[{completed}/{total_topics}] 抓取主题 {name} ({slug})", flush=True)
                except Exception as exc:
                    failed_topics_by_slug[slug] = {
                        "name": name,
                        "slug": slug,
                        "group": topic_definition["group"],
                        "error": str(exc),
                    }
                    print(f"[{completed}/{total_topics}] 跳过失败主题 {name} ({slug}): {exc}", flush=True)

                save_checkpoint(
                    checkpoint_path,
                    args=args,
                    topic_results=list(topic_results_by_slug.values()),
                    failed_topics=list(failed_topics_by_slug.values()),
                    failed_appids=list(failed_appids_by_id.values()),
                    app_details_by_id=app_details_by_id,
                )

    ordered_resolved_topics = [
        topic_results_by_slug[topic_definition["slug"]]
        for topic_definition in topic_definitions
        if topic_definition["slug"] in topic_results_by_slug
    ]
    ordered_failed_topics = [
        failed_topics_by_slug[topic_definition["slug"]]
        for topic_definition in topic_definitions
        if topic_definition["slug"] in failed_topics_by_slug
    ]

    unique_appids = sorted({appid for item in ordered_resolved_topics for appid in item["appids"]})
    pending_appids = [
        appid for appid in unique_appids if appid not in app_details_by_id and appid not in failed_appids_by_id
    ]

    if pending_appids:
        detail_workers = max(1, min(args.workers, max(len(pending_appids), 1)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=detail_workers) as executor:
            future_map = {
                executor.submit(fetch_app_detail_entry, client, appid): appid for appid in pending_appids
            }
            completed = len(app_details_by_id)
            for future in concurrent.futures.as_completed(future_map):
                appid = future_map[future]
                completed += 1
                try:
                    appid, details = future.result()
                    app_details_by_id[appid] = details
                    print(f"[{completed}/{len(unique_appids)}] 抓取作品详情 {appid}", flush=True)
                except Exception as exc:
                    failed_appids_by_id[appid] = {"appid": appid, "error": str(exc)}
                    print(f"[{completed}/{len(unique_appids)}] 跳过失败作品 {appid}: {exc}", flush=True)

                if completed % max(1, args.checkpoint_interval) == 0 or completed == len(unique_appids):
                    save_checkpoint(
                        checkpoint_path,
                        args=args,
                        topic_results=ordered_resolved_topics,
                        failed_topics=ordered_failed_topics,
                        failed_appids=list(failed_appids_by_id.values()),
                        app_details_by_id=app_details_by_id,
                    )

    topics_payload: list[dict[str, Any]] = []
    for item in ordered_resolved_topics:
        definition = item["topic_definition"]
        page_info = item["page_info"]
        metadata = item["metadata"]
        top_sellers = item["top_sellers"]
        appids = item["appids"]

        topics_payload.append(
            {
                "name": definition["name"],
                "slug": definition["slug"],
                "group": definition["group"],
                "title_en": metadata.get("title"),
                "subtitle_en": metadata.get("subtitle"),
                "topic_url": page_info["topic_url"],
                "works_source": {
                    "method": "saleaction/ajaxgetsaledynamicappquery",
                    "flavor": TOPIC_FLAVOR,
                    "announcement_gid": page_info.get("announcement_gid"),
                },
                "match_count": top_sellers.get("match_count"),
                "possible_has_more": top_sellers.get("possible_has_more"),
                "hot_works_count": len(appids),
                "hot_works": [app_details_by_id[appid] for appid in appids if appid in app_details_by_id],
            }
        )

    payload = {
        "metadata": {
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "language": args.language,
            "country_code": args.country_code,
            "works_per_topic": args.works_per_topic,
            "topic_count": len(topics_payload),
            "failed_topic_count": len(ordered_failed_topics),
            "failed_work_count": len(failed_appids_by_id),
            "unique_work_count": len(app_details_by_id),
            "workers": workers,
            "source": {
                "contenthub_endpoint": CONTENT_HUB_URL,
                "works_endpoint": TOPIC_QUERY_URL,
                "appdetails_endpoint": APPDETAILS_URL,
                "flavor": TOPIC_FLAVOR,
                "anonymous": True,
            },
        },
        "failed_topics": ordered_failed_topics,
        "failed_works": list(failed_appids_by_id.values()),
        "topics": topics_payload,
    }
    save_json(output_path, payload)

    if topics_only_output_path:
        topics_only_payload = {
            "metadata": {
                "generated_at": datetime.now(tz=UTC).isoformat(),
                "language": args.language,
                "country_code": args.country_code,
                "topic_count": len(topics_payload),
                "failed_topic_count": len(ordered_failed_topics),
                "failed_work_count": len(failed_appids_by_id),
            },
            "failed_topics": ordered_failed_topics,
            "failed_works": list(failed_appids_by_id.values()),
            "topics": [
                {
                    "name": item["name"],
                    "slug": item["slug"],
                    "group": item["group"],
                    "title_en": item["title_en"],
                    "topic_url": item["topic_url"],
                    "match_count": item["match_count"],
                }
                for item in topics_payload
            ],
        }
        save_json(topics_only_output_path, topics_only_payload)

    if checkpoint_path.exists():
        checkpoint_path.unlink()

    print(f"已保存主题结果到: {output_path}")
    if topics_only_output_path:
        print(f"已保存主题列表到: {topics_only_output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
