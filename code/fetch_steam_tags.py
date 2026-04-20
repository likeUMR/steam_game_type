#!/usr/bin/env python3
"""抓取 Steam 全部标签及每个标签对应的网页端典型游戏。"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


BROWSE_TAGS_URL = "https://store.steampowered.com/tag/browse/"
TAG_GAMES_URL_TEMPLATE = "https://store.steampowered.com/tagdata/gettaggames/{path_language}/{tag_id}/"
DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
}
TAG_PATTERN = re.compile(r'data-tagid="(?P<tagid>\d+)">(?P<name>[^<]+)<')
TOTAL_GAMES_PATTERN = re.compile(r"(\d[\d,]*)")


def get_path_language(language: str) -> str:
    mapping = {
        "schinese": "zh-cn",
        "tchinese": "zh-tw",
        "english": "english",
        "japanese": "ja",
        "koreana": "ko",
    }
    return mapping.get(language, language)


class TagGamesHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tag_name: str | None = None
        self.tag_url: str | None = None
        self.total_games_text: str | None = None
        self.total_games: int | None = None
        self.games: list[dict[str, Any]] = []

        self._capture_tag_name = False
        self._capture_total_games = False
        self._capture_game_name = False
        self._capture_game_price = False
        self._inside_total_link = False

        self._current_game: dict[str, Any] | None = None
        self._current_game_div_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        classes = set(attr_map.get("class", "").split())

        if tag == "div" and "browse_tag_game" in classes and self._current_game is None:
            self._current_game = {
                "appid": None,
                "itemkey": None,
                "tagids": [],
                "creator_clan_ids": [],
                "store_url": None,
                "image_url": None,
                "name": None,
                "price_text": None,
            }
            self._current_game_div_depth = 1
            return

        if self._current_game is not None and tag == "div":
            self._current_game_div_depth += 1

        if tag == "a" and "tag_name" in classes:
            self._capture_tag_name = True
            self.tag_url = attr_map.get("href") or None
            return

        if tag == "a" and "btn_medium" in classes:
            self._inside_total_link = True
            if not self.tag_url:
                self.tag_url = attr_map.get("href") or None
            return

        if tag == "span" and self._inside_total_link:
            self._capture_total_games = True
            return

        if self._current_game is None:
            return

        if tag == "div" and "browse_tag_game_cap" in classes:
            self._current_game["appid"] = safe_int(attr_map.get("data-ds-appid"))
            self._current_game["itemkey"] = attr_map.get("data-ds-itemkey") or None
            self._current_game["tagids"] = parse_json_list(attr_map.get("data-ds-tagids"))
            self._current_game["creator_clan_ids"] = parse_json_list(attr_map.get("data-ds-crtrids"))
            return

        if tag == "div" and "browse_tag_game_name" in classes:
            self._capture_game_name = True
            return

        if tag == "div" and "browse_tag_game_price" in classes:
            self._capture_game_price = True
            return

        if tag == "a" and self._current_game.get("store_url") is None:
            href = attr_map.get("href")
            if href and "/app/" in href:
                self._current_game["store_url"] = href
            return

        if tag == "img" and self._current_game.get("image_url") is None:
            src = attr_map.get("src")
            if src:
                self._current_game["image_url"] = src

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._capture_tag_name = False
            self._inside_total_link = False

        if tag == "span":
            self._capture_total_games = False

        if tag == "div":
            self._capture_game_name = False
            self._capture_game_price = False
            if self._current_game is not None:
                self._current_game_div_depth -= 1
                if self._current_game_div_depth == 0:
                    self.games.append(self._current_game)
                    self._current_game = None

    def handle_data(self, data: str) -> None:
        text = clean_text(data)
        if not text:
            return

        if self._capture_tag_name:
            self.tag_name = merge_text(self.tag_name, text)
            return

        if self._capture_total_games:
            self.total_games_text = merge_text(self.total_games_text, text)
            self.total_games = parse_total_games(self.total_games_text)
            return

        if self._current_game is None:
            return

        if self._capture_game_name:
            self._current_game["name"] = merge_text(self._current_game.get("name"), text)
            return

        if self._capture_game_price:
            self._current_game["price_text"] = merge_text(self._current_game.get("price_text"), text)


def merge_text(old_value: str | None, new_value: str) -> str:
    if not old_value:
        return new_value
    if new_value in old_value:
        return old_value
    return f"{old_value} {new_value}".strip()


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(html.unescape(value).replace("\xa0", " ").split())


def parse_total_games(value: str | None) -> int | None:
    if not value:
        return None
    match = TOTAL_GAMES_PATTERN.search(value)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def parse_json_list(value: str | None) -> list[int]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    result: list[int] = []
    if isinstance(parsed, list):
        for item in parsed:
            converted = safe_int(item)
            if converted is not None:
                result.append(converted)
    return result


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class SteamClient:
    language: str
    country_code: str
    steam_realm: str
    timeout: int
    retries: int
    retry_delay: float
    request_delay: float

    def get_text(self, url: str, params: dict[str, Any]) -> str:
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"{url}?{query}",
            headers=DEFAULT_HEADERS,
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

    def fetch_tags(self) -> list[dict[str, Any]]:
        html_text = self.get_text(BROWSE_TAGS_URL, {"l": self.language})
        tags: list[dict[str, Any]] = []
        seen_tag_ids: set[int] = set()
        for match in TAG_PATTERN.finditer(html_text):
            tag_id = int(match.group("tagid"))
            if tag_id in seen_tag_ids:
                continue
            seen_tag_ids.add(tag_id)
            tags.append(
                {
                    "tagid": tag_id,
                    "name": clean_text(match.group("name")),
                }
            )
        if not tags:
            raise RuntimeError("标签浏览页返回格式异常，未解析到任何标签")
        return tags

    def fetch_tag_details(self, tag_id: int, tag_name: str) -> dict[str, Any]:
        url = TAG_GAMES_URL_TEMPLATE.format(
            path_language=get_path_language(self.language),
            tag_id=tag_id,
        )
        html_text = self.get_text(
            url,
            {
                "name": tag_name,
                "cc": self.country_code,
                "realm": self.steam_realm,
                "l": self.language,
                "v6": 2,
                "tag_tf": "true",
            },
        )
        parser = TagGamesHTMLParser()
        parser.feed(html_text)
        return {
            "tag_name": parser.tag_name or tag_name,
            "tag_url": parser.tag_url,
            "total_games": parser.total_games,
            "total_games_text": parser.total_games_text,
            "games": parser.games,
            "source_endpoint": url,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="保存 Steam 全部标签及每个标签对应的网页端典型游戏信息")
    parser.add_argument(
        "--output",
        default="steam_tags_with_top_games.json",
        help="输出 JSON 文件路径，默认: steam_tags_with_top_games.json",
    )
    parser.add_argument(
        "--games-per-tag",
        type=int,
        default=9,
        help="每个标签抓取的典型游戏数量，默认: 9",
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
        "--steam-realm",
        default="1",
        help="Steam realm，默认: 1",
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
        default=0.05,
        help="每次成功请求后的间隔（秒），默认: 0.05",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=6,
        help="并发抓取标签详情的线程数，默认: 6",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅抓取前 N 个标签，便于调试",
    )
    return parser.parse_args()


def normalize_game(game: dict[str, Any]) -> dict[str, Any]:
    price_text = clean_text(game.get("price_text"))
    return {
        "appid": safe_int(game.get("appid")),
        "itemkey": game.get("itemkey"),
        "name": clean_text(game.get("name")),
        "store_url": game.get("store_url"),
        "image_url": game.get("image_url"),
        "price_text": price_text,
        "is_free": "免费开玩" in price_text,
        "tagids": game.get("tagids", []),
        "creator_clan_ids": game.get("creator_clan_ids", []),
    }


def normalize_tag(tag: dict[str, Any], details: dict[str, Any], games_per_tag: int) -> dict[str, Any]:
    games = details.get("games", [])
    return {
        "tagid": tag.get("tagid"),
        "name": details.get("tag_name") or tag.get("name"),
        "browse_url": details.get("tag_url"),
        "total_games": details.get("total_games"),
        "total_games_text": details.get("total_games_text"),
        "typical_games_count": min(games_per_tag, len(games)),
        "typical_games": [normalize_game(game) for game in games[:games_per_tag]],
        "source": {
            "method": "tagdata/gettaggames",
            "endpoint": details.get("source_endpoint"),
        },
    }


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_one_tag(
    client: SteamClient,
    tag: dict[str, Any],
    games_per_tag: int,
) -> dict[str, Any]:
    tag_id = tag.get("tagid")
    tag_name = tag.get("name")
    if not isinstance(tag_id, int):
        raise RuntimeError(f"异常标签数据: {tag!r}")
    details = client.fetch_tag_details(tag_id=tag_id, tag_name=tag_name)
    return normalize_tag(tag, details, games_per_tag)


def main() -> int:
    args = parse_args()
    output_path = Path(args.output).expanduser().resolve()

    client = SteamClient(
        language=args.language,
        country_code=args.country_code,
        steam_realm=args.steam_realm,
        timeout=args.timeout,
        retries=args.retries,
        retry_delay=args.retry_delay,
        request_delay=args.delay,
    )

    tags = client.fetch_tags()
    if args.limit is not None:
        tags = tags[: args.limit]

    total_tags = len(tags)
    result_tags: list[dict[str, Any] | None] = [None] * total_tags
    completed = 0

    max_workers = max(1, min(args.workers, total_tags))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(fetch_one_tag, client, tag, args.games_per_tag): (index, tag)
            for index, tag in enumerate(tags)
        }

        for future in concurrent.futures.as_completed(future_map):
            index, tag = future_map[future]
            tag_id = tag.get("tagid")
            tag_name = tag.get("name")
            completed += 1
            try:
                result_tags[index] = future.result()
                print(f"[{completed}/{total_tags}] 抓取标签 {tag_name} ({tag_id})", flush=True)
            except Exception as exc:
                print(f"[{completed}/{total_tags}] 抓取失败 {tag_name} ({tag_id}): {exc}", file=sys.stderr, flush=True)
                raise

    payload = {
        "metadata": {
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "source": {
                "tags_endpoint": BROWSE_TAGS_URL,
                "games_endpoint_template": TAG_GAMES_URL_TEMPLATE,
                "method": "Steam 网页端 tag/browse + tagdata/gettaggames",
            },
            "language": args.language,
            "country_code": args.country_code,
            "steam_realm": args.steam_realm,
            "games_per_tag": args.games_per_tag,
            "workers": max_workers,
            "tag_count": len([tag for tag in result_tags if tag is not None]),
        },
        "tags": [tag for tag in result_tags if tag is not None],
    }

    save_json(output_path, payload)
    print(f"已保存到: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
