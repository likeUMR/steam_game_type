#!/usr/bin/env python3
"""为 Steam tags / topics 结果生成词云和统计图。"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from wordcloud import WordCloud


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 Steam tags/topics 分析图表")
    parser.add_argument(
        "--tags",
        default="results/latest/steam_tags_with_top_games_localized.json",
        help="标签结果 JSON 路径",
    )
    parser.add_argument(
        "--topics",
        default="results/latest/steam_topics_with_top_works.json",
        help="主题结果 JSON 路径",
    )
    parser.add_argument(
        "--output-dir",
        default="results/latest/plots",
        help="图片输出目录",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def get_chinese_font_path() -> str:
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError("未找到可用中文字体，请安装微软雅黑或黑体。")


def configure_matplotlib_font(font_path: str) -> None:
    font_manager.fontManager.addfont(font_path)
    font_name = font_manager.FontProperties(fname=font_path).get_name()
    plt.rcParams["font.family"] = font_name
    plt.rcParams["axes.unicode_minus"] = False


def save_figure(fig: plt.Figure, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def shorten_labels(labels: list[str], max_length: int = 18) -> list[str]:
    result = []
    for label in labels:
        if len(label) <= max_length:
            result.append(label)
        else:
            result.append(label[: max_length - 1] + "…")
    return result


def plot_wordcloud(frequencies: dict[str, int], title: str, font_path: str, output_path: Path) -> None:
    wc = WordCloud(
        width=1600,
        height=900,
        background_color="white",
        font_path=font_path,
        max_words=200,
        collocations=False,
    ).generate_from_frequencies(frequencies)
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.imshow(wc, interpolation="bilinear")
    ax.set_title(title, fontsize=18)
    ax.axis("off")
    save_figure(fig, output_path)


def plot_horizontal_bar(
    labels: list[str],
    values: list[float],
    title: str,
    xlabel: str,
    output_path: Path,
    color: str,
) -> None:
    fig, ax = plt.subplots(figsize=(12, 8))
    short_labels = shorten_labels(labels)
    y_positions = list(range(len(short_labels)))
    ax.barh(y_positions, values, color=color)
    ax.set_yticks(y_positions)
    ax.set_yticklabels(short_labels)
    ax.invert_yaxis()
    ax.set_title(title, fontsize=16)
    ax.set_xlabel(xlabel)
    for idx, value in enumerate(values):
        ax.text(value, idx, f" {int(value):,}", va="center", fontsize=9)
    save_figure(fig, output_path)


def plot_vertical_bar(
    labels: list[str],
    values: list[float],
    title: str,
    ylabel: str,
    output_path: Path,
    color: str,
) -> None:
    fig, ax = plt.subplots(figsize=(12, 7))
    short_labels = shorten_labels(labels, max_length=14)
    ax.bar(short_labels, values, color=color)
    ax.set_title(title, fontsize=16)
    ax.set_ylabel(ylabel)
    plt.setp(ax.get_xticklabels(), rotation=25, ha="right")
    for idx, value in enumerate(values):
        ax.text(idx, value, f"{int(value):,}", ha="center", va="bottom", fontsize=9)
    save_figure(fig, output_path)


def plot_histogram(values: list[int], bins: int, title: str, xlabel: str, output_path: Path, color: str) -> None:
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(values, bins=bins, color=color, edgecolor="white")
    ax.set_title(title, fontsize=16)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("数量")
    save_figure(fig, output_path)


def analyze_tags(tags_data: dict[str, Any], output_dir: Path, font_path: str) -> dict[str, Any]:
    tags = tags_data["tags"]
    tag_freq = {item["name"]: int(item.get("total_games") or 0) for item in tags if item.get("name")}
    sorted_tags = sorted(tags, key=lambda item: int(item.get("total_games") or 0), reverse=True)

    plot_wordcloud(
        tag_freq,
        "Steam 标签词云（按标签覆盖作品数加权）",
        font_path,
        output_dir / "tags_wordcloud.png",
    )

    top20 = sorted_tags[:20]
    plot_horizontal_bar(
        [item["name"] for item in top20],
        [int(item.get("total_games") or 0) for item in top20],
        "Top 20 标签覆盖作品数",
        "作品数",
        output_dir / "tags_top20_total_games.png",
        "#4C78A8",
    )

    total_games_values = [int(item.get("total_games") or 0) for item in tags]
    plot_histogram(
        total_games_values,
        bins=20,
        title="标签覆盖作品数分布",
        xlabel="单个标签覆盖作品数",
        output_path=output_dir / "tags_total_games_distribution.png",
        color="#72B7B2",
    )

    return {
        "tag_count": len(tags),
        "top_tag_name": top20[0]["name"],
        "top_tag_total_games": int(top20[0].get("total_games") or 0),
        "median_total_games": int(median(total_games_values)),
        "mean_total_games": int(mean(total_games_values)),
    }


def analyze_topics(topics_data: dict[str, Any], output_dir: Path, font_path: str) -> dict[str, Any]:
    topics = topics_data["topics"]
    topic_freq = {item["name"]: int(item.get("match_count") or 0) for item in topics if item.get("name")}
    sorted_topics = sorted(topics, key=lambda item: int(item.get("match_count") or 0), reverse=True)

    plot_wordcloud(
        topic_freq,
        "Steam 主题词云（按主题匹配作品数加权）",
        font_path,
        output_dir / "topics_wordcloud.png",
    )

    top20 = sorted_topics[:20]
    plot_horizontal_bar(
        [item["name"] for item in top20],
        [int(item.get("match_count") or 0) for item in top20],
        "Top 20 主题匹配作品数",
        "匹配作品数",
        output_dir / "topics_top20_match_count.png",
        "#F58518",
    )

    group_counter = Counter(item.get("group") or "未分组" for item in topics)
    groups_sorted = sorted(group_counter.items(), key=lambda x: x[1], reverse=True)
    plot_vertical_bar(
        [name for name, _ in groups_sorted],
        [count for _, count in groups_sorted],
        "主题分组数量分布",
        "主题数量",
        output_dir / "topics_group_distribution.png",
        "#54A24B",
    )

    hot_works_counts = [int(item.get("hot_works_count") or 0) for item in topics]
    plot_histogram(
        hot_works_counts,
        bins=min(15, max(hot_works_counts) - min(hot_works_counts) + 1),
        title="每个主题实际热门作品数分布",
        xlabel="热门作品数",
        output_path=output_dir / "topics_hot_works_distribution.png",
        color="#E45756",
    )

    work_counter: Counter[str] = Counter()
    for topic in topics:
        for work in topic.get("hot_works", []):
            name = work.get("name")
            if name:
                work_counter[name] += 1
    recurring_works = work_counter.most_common(15)
    plot_horizontal_bar(
        [name for name, _ in recurring_works],
        [count for _, count in recurring_works],
        "跨主题重复出现最多的热门作品",
        "出现主题数",
        output_dir / "topics_recurring_works.png",
        "#B279A2",
    )

    return {
        "topic_count": len(topics),
        "top_topic_name": top20[0]["name"],
        "top_topic_match_count": int(top20[0].get("match_count") or 0),
        "median_topic_match_count": int(median(int(item.get("match_count") or 0) for item in topics)),
        "mean_topic_match_count": int(mean(int(item.get("match_count") or 0) for item in topics)),
        "median_hot_works_count": int(median(hot_works_counts)),
        "max_recurring_work_name": recurring_works[0][0],
        "max_recurring_work_count": recurring_works[0][1],
        "group_counts": dict(groups_sorted),
    }


def main() -> int:
    args = parse_args()
    tags_path = Path(args.tags).expanduser().resolve()
    topics_path = Path(args.topics).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    ensure_output_dir(output_dir)

    font_path = get_chinese_font_path()
    configure_matplotlib_font(font_path)

    tags_data = read_json(tags_path)
    topics_data = read_json(topics_path)

    tag_summary = analyze_tags(tags_data, output_dir, font_path)
    topic_summary = analyze_topics(topics_data, output_dir, font_path)

    summary = {
        "generated_at": tags_data["metadata"].get("generated_at"),
        "tag_summary": tag_summary,
        "topic_summary": topic_summary,
    }
    summary_path = output_dir / "analysis_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成分析图和摘要: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
