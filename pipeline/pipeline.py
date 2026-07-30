"""四步知识库自动化流水线。

Collect -> Analyze -> Organize -> Save

用法:
    python pipeline/pipeline.py --sources github,rss --limit 10
    python pipeline/pipeline.py --sources github --limit 5
    python pipeline/pipeline.py --sources rss
    python pipeline/pipeline.py --sources github --limit 5 --dry-run
    python pipeline/pipeline.py --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from model_client import OpenAICompatibleProvider, chat_with_retry

logger = logging.getLogger(__name__)

# ── 路径常量 ──────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = _PROJECT_ROOT / "knowledge" / "raw"
ARTICLES_DIR = _PROJECT_ROOT / "knowledge" / "articles"
RSS_SOURCES_PATH = Path(__file__).resolve().parent / "rss_sources.yaml"

# ── 网络常量 ──────────────────────────────────────────────────────────────

GITHUB_SEARCH_API = "https://api.github.com/search/repositories"
GITHUB_TIMEOUT = 30.0
RSS_TIMEOUT = 30.0

TZ = timezone(timedelta(hours=8))

GITHUB_QUERIES = [
    "topic:llm",
    "topic:agent",
    "topic:rag",
    "topic:machine-learning",
    "topic:ai",
]

# ── 筛选常量 (对标 collector agent) ──────────────────────────────────────

_INCLUDE_KEYWORDS = {
    "ai", "llm", "gpt", "claude", "gemini", "copilot", "agent",
    "rag", "vector", "embedding", "transformer", "fine-tuning",
    "lora", "prompt", "langchain", "diffusion", "multimodal",
    "open-source model", "benchmark", "inference", "tool-use",
}

_EXCLUDE_KEYWORDS = {"awesome", "awesome-list", "curated-list"}

_EXCLUDE_DESC_PREFIXES = ("a curated list of", "awesome")

# ── Schema 常量 ──────────────────────────────────────────────────────────

_VALID_SOURCES = frozenset({"github-trending", "hackernews"})

_VALID_TAGS = frozenset({
    "llm", "agent", "rag", "embedding", "vector-db",
    "prompt-engineering", "fine-tuning", "transformer", "multimodal",
    "tool-use", "evaluation", "safety", "deployment", "benchmark",
    "open-source", "closed-source", "framework", "tutorial", "paper", "opinion",
})

_ANALYZE_SYSTEM_PROMPT = """你是一名 AI 技术分析助手。给定一条技术内容（GitHub 仓库或技术文章），请用中文输出结构化分析结果。

严格以 JSON 格式输出，不要包含其他文字：
{
  "summary": "一句话摘要（≤120 字，中文）",
  "highlights": ["亮点1", "亮点2", "亮点3"],
  "relevance_score": 7,
  "score_reason": "评分理由，20-80 字",
  "tags": ["tag1", "tag2"],
  "content": "Markdown 格式的结构化分析正文，包含项目概述、核心特性、适用场景等"
}

relevance_score 评分标准（1-10 整数）：
- 9-10: AI/LLM/Agent 领域突破性项目或深度技术文章，直接相关
- 7-8:  高度相关的 AI 技术内容，值得关注
- 5-6:  有一定关联的技术内容
- 1-4:  弱相关，建议跳过

tags 只能从以下标签中选取（最多 5 个）：
llm, agent, rag, embedding, vector-db, prompt-engineering, fine-tuning,
transformer, multimodal, tool-use, evaluation, safety, deployment,
benchmark, open-source, closed-source, framework, tutorial, paper, opinion"""


# ── Step 1: 采集 ──────────────────────────────────────────────────────────

def _build_github_headers() -> dict[str, str]:
    """构建 GitHub API 请求头，自动注入 Token。"""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _match_keywords(text: str, keywords: frozenset[str]) -> bool:
    """检查文本中是否命中任一关键词（大小写不敏感）。"""
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def _should_include_repo(repo: dict[str, Any]) -> bool:
    """根据 collector agent 筛选规则判断仓库是否纳入。

    纳入规则 (满足任一)：
    - topics 中命中 _INCLUDE_KEYWORDS
    - description 或 name 中命中 _INCLUDE_KEYWORDS

    排除规则 (满足任一即丢弃)：
    - topics 或 name 中含 awesome/list 等
    - description 以 "A curated list of" 或 "Awesome" 开头
    """
    name = (repo.get("full_name") or "").lower()
    description = (repo.get("description") or "").lower()
    topics = {t.lower() for t in repo.get("topics", [])}

    for kw in _EXCLUDE_KEYWORDS:
        if kw in name or kw in " ".join(topics):
            return False
    if description.startswith(_EXCLUDE_DESC_PREFIXES):
        return False

    if topics & _INCLUDE_KEYWORDS:
        return True
    if _match_keywords(description, _INCLUDE_KEYWORDS):
        return True
    return bool(_match_keywords(name, _INCLUDE_KEYWORDS))


def _load_historical_urls(source: str) -> set[str]:
    """从 knowledge/raw/ 历史文件中加载已有 URL 集合。

    Args:
        source: 来源标识如 "github-trending"。

    Returns:
        去重用 URL 集合。
    """
    urls: set[str] = set()
    pattern = f"{source}-*.json"
    for path in RAW_DIR.glob(pattern):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for entry in data:
                    url = entry.get("url", "")
                    if url:
                        urls.add(url)
            elif isinstance(data, dict):
                for entry in data.get("items", data.get("entries", [])):
                    url = entry.get("url", "")
                    if url:
                        urls.add(url)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("读取历史文件失败 %s: %s", path, e)
    return urls


def _generate_cn_summary(name: str, description: str) -> str:
    """基于仓库名和描述生成中文摘要 (≤80 字)。"""
    desc = (description or "").strip()
    _, _, repo = name.partition("/")
    repo_name = repo or name

    if not desc:
        return f"{repo_name} 是一个 AI 相关的开源项目。"

    # 尝试提取 "做什么" 和 "为什么值得关注"
    what = desc
    why = ""
    for sep in ("，", "。", " - ", " — ", ".", ";"):
        if sep in desc:
            parts = desc.split(sep, 1)
            what = parts[0].strip()
            why = parts[1].strip()
            break

    what = what[:50]
    why = why[:30] if why else "其功能具有较高实用价值"
    summary = f"{repo_name} 是一个{what}的开源项目，核心亮点是{why}。"
    return summary[:80]


def collect_github(limit: int, client: httpx.Client) -> list[dict[str, Any]]:
    """从 GitHub Search API 采集 AI 相关仓库（对标 collector agent 规则）。

    流程：多轮搜索 → 关键词过滤 → awesome 排除 → 历史去重 → 中文摘要 → 热度排序 → 取 Top N。

    Args:
        limit: 最终输出条目数。
        client: httpx Client 实例。

    Returns:
        RawEntry 列表，满足 schema 约束。
    """
    headers = _build_github_headers()
    now_iso = datetime.now(TZ).isoformat()
    historical_urls = _load_historical_urls("github-trending")
    logger.debug("历史 URL 去重库: %d 条", len(historical_urls))

    raw_candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for query in GITHUB_QUERIES:
        params = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": 30,
        }
        try:
            resp = client.get(
                GITHUB_SEARCH_API, params=params, headers=headers, timeout=GITHUB_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                "GitHub API HTTP %d: %.200s", e.response.status_code, e.response.text,
            )
            continue
        except httpx.TimeoutException:
            logger.error("GitHub API 请求超时 (%.0fs)", GITHUB_TIMEOUT)
            continue
        except httpx.RequestError as e:
            logger.error("GitHub API 请求异常: %s", e)
            continue

        query_count = 0
        for repo in data.get("items", []):
            url = repo.get("html_url", "")
            if url in seen_urls or url in historical_urls:
                continue

            if not _should_include_repo(repo):
                continue

            seen_urls.add(url)
            raw_candidates.append({
                "title": repo.get("full_name", ""),
                "url": url,
                "source": "github-trending",
                "popularity": repo.get("stargazers_count", 0),
                "summary": "",
                "description": repo.get("description") or "",
                "collected_at": now_iso,
            })
            query_count += 1

        logger.debug(
            "查询 [%s] 返回 %d 仓库，纳入 %d 条",
            query, len(data.get("items", [])), query_count,
        )

    # 按热度降序，取前 limit
    raw_candidates.sort(key=lambda x: x["popularity"], reverse=True)
    items = raw_candidates[:limit]

    # 为每条生成中文摘要
    for item in items:
        item["summary"] = _generate_cn_summary(
            item["title"], item.get("description", item.get("summary", "")),
        )

    logger.info(
        "GitHub 采集: 候选 %d 条 → 过滤后 %d 条 → 输出 top %d",
        len(raw_candidates) + len(historical_urls), len(raw_candidates), len(items),
    )
    return items


# ── RSS ───────────────────────────────────────────────────────────────────

def _clean_html(text: str) -> str:
    """去除 HTML 标签和实体引用。"""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    return text.strip()


def _extract_rss_items(text: str) -> list[dict[str, str]]:
    """从 RSS/Atom XML 文本中提取条目。

    同时兼容 RSS 2.0 (<item>) 和 Atom (<entry>) 格式。
    """
    # 先尝试 RSS 2.0
    item_re = re.compile(r"<item>\s*(.*?)\s*</item>", re.DOTALL | re.IGNORECASE)
    blocks = item_re.findall(text)

    if not blocks:
        # 回退到 Atom
        entry_re = re.compile(r"<entry>\s*(.*?)\s*</entry>", re.DOTALL | re.IGNORECASE)
        blocks = entry_re.findall(text)

    results: list[dict[str, str]] = []
    for block in blocks:
        title = _extract_tag(block, "title")
        link = _extract_link(block)
        description = _extract_tag(block, "description")
        if title and link:
            results.append({
                "title": title,
                "link": link,
                "description": _clean_html(description),
            })
    return results


def _extract_tag(block: str, tag: str) -> str:
    """从 XML 片段中提取指定标签内容，支持 CDATA。"""
    cdata = re.search(
        rf"<{tag}[^>]*>\s*<!\[CDATA\[(.*?)\]\]>\s*</{tag}>", block, re.DOTALL | re.IGNORECASE
    )
    if cdata:
        return cdata.group(1).strip()
    plain = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.DOTALL | re.IGNORECASE)
    return plain.group(1).strip() if plain else ""


def _extract_link(block: str) -> str:
    """从 XML 片段中提取链接（兼容 href 属性形式和文本节点形式）。"""
    href = re.search(r"""<link[^>]*href=["']([^"']+)["']""", block, re.IGNORECASE)
    if href:
        return href.group(1).strip()
    text = _extract_tag(block, "link")
    return text


def _collect_rss_feed(
    url: str, name: str, client: httpx.Client,
) -> list[dict[str, Any]]:
    """采集单个 RSS/Atom 源。

    Args:
        url: RSS feed URL。
        name: 数据源名称（用于日志）。
        client: httpx Client 实例。

    Returns:
        该源的 RawEntry 列表。
    """
    try:
        resp = client.get(url, timeout=RSS_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("RSS 获取失败 %s (%s): %s", name, url, e)
        return []

    raw_entries = _extract_rss_items(resp.text)
    now_iso = datetime.now(TZ).isoformat()
    items: list[dict[str, Any]] = []
    for entry in raw_entries:
        items.append({
            "title": entry["title"],
            "url": entry["link"],
            "source": "hackernews",
            "popularity": 0,
            "summary": entry.get("description", "")[:500],
            "collected_at": now_iso,
        })
    logger.info("RSS [%s] 采集完成，共 %d 条", name, len(items))
    return items


def collect_rss(
    client: httpx.Client, limit: int,
) -> list[dict[str, Any]]:
    """从 rss_sources.yaml 配置的已启用源采集 RSS 内容。

    Args:
        client: httpx Client 实例。
        limit: 该来源采集条目上限。

    Returns:
        所有 RSS 源的 RawEntry 合并列表，总量不超过 limit。
    """
    if not RSS_SOURCES_PATH.exists():
        logger.warning("RSS 配置文件不存在: %s", RSS_SOURCES_PATH)
        return []

    with open(RSS_SOURCES_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    all_items: list[dict[str, Any]] = []
    sources = [s for s in config.get("sources", []) if s.get("enabled", False)]

    for src in sources:
        remaining = limit - len(all_items)
        if remaining <= 0:
            break

        items = _collect_rss_feed(src["url"], src["name"], client)
        items = items[:remaining]
        all_items.extend(items)
        if items:
            _save_raw(items, f"rss-{_slug(src['name'], 30)}")

    logger.info(
        "RSS 采集总计 %d 条 (来源 %d 个, 上限 %d)", len(all_items), len(sources), limit,
    )
    return all_items


# ── 保存原始数据 ──────────────────────────────────────────────────────────

def _save_raw(items: list[dict[str, Any]], source: str) -> Path:
    """保存原始采集数据到 knowledge/raw/ 目录。

    Args:
        items: 原始条目列表。
        source: 来源标识，如 "github" / "rss-lobsters"。

    Returns:
        写入的文件路径。
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    path = RAW_DIR / f"{source}-{today}.json"
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("原始数据已保存: %s (%d 条)", path, len(items))
    return path


# ── Step 2: 分析 ──────────────────────────────────────────────────────────

def _parse_llm_json(content: str) -> dict[str, Any] | None:
    """从 LLM 返回文本中提取 JSON 对象。

    Args:
        content: LLM 返回的原始文本。

    Returns:
        解析后的 dict，失败返回 None。
    """
    content = content.strip()
    # 尝试直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # 尝试提取 ```json ... ``` 代码块
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    # 尝试提取裸 {}
    brace = re.search(r"\{.*\}", content, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group())
        except json.JSONDecodeError:
            pass
    logger.warning("LLM 返回无法解析为 JSON: %.300s...", content)
    return None


def analyze_item(
    provider: OpenAICompatibleProvider, item: dict[str, Any],
) -> dict[str, Any] | None:
    """调用 LLM 分析单条内容。

    Args:
        provider: LLMProvider 实例。
        item: RawEntry 字典。

    Returns:
        分析后的条目 dict，包含 LLM 生成的 summary/highlights/score/tags/content。
        调用失败返回 None。
    """
    prompt = (
        f"标题: {item.get('title', '')}\n"
        f"来源: {item.get('source', '')}\n"
        f"链接: {item.get('url', '')}\n"
        f"描述: {item.get('summary', '')}\n"
        f"热度: {item.get('popularity', 0)}\n"
    )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": _ANALYZE_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    try:
        response = chat_with_retry(provider, messages, temperature=0.3, max_tokens=2048)
    except httpx.HTTPError as e:
        logger.error("LLM 调用失败 [%s]: %s", item.get("title", ""), e)
        return None

    parsed = _parse_llm_json(response.content)
    if parsed is None:
        return None

    # 校验并规整字段
    relevance = int(parsed.get("relevance_score", 5))
    relevance = max(1, min(10, relevance))

    tags = [t for t in parsed.get("tags", []) if t in _VALID_TAGS]

    return {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "source": item.get("source", ""),
        "popularity": item.get("popularity", 0),
        "summary": str(parsed.get("summary", item.get("summary", "")))[:120],
        "highlights": [str(h) for h in parsed.get("highlights", [])][:5],
        "relevance_score": relevance,
        "score_reason": str(parsed.get("score_reason", "")),
        "tags": tags[:5],
        "content": str(parsed.get("content", "")),
        "collected_at": item.get("collected_at", ""),
        "analyzed_at": datetime.now(TZ).isoformat(),
    }


def analyze_items(
    provider: OpenAICompatibleProvider, items: list[dict[str, Any]], dry_run: bool,
) -> list[dict[str, Any]]:
    """批量分析内容条目。

    Args:
        provider: LLMProvider 实例。
        items: RawEntry 列表。
        dry_run: 干跑模式，跳过 LLM 调用。

    Returns:
        分析后的条目列表（含 analyze 字段）。
    """
    analyzed: list[dict[str, Any]] = []
    total = len(items)
    now_iso = datetime.now(TZ).isoformat()

    for i, item in enumerate(items, 1):
        title_short = (item.get("title") or "")[:60]
        logger.info("分析 [%d/%d]: %s", i, total, title_short)

        if dry_run:
            analyzed.append({
                **item,
                "relevance_score": 5,
                "highlights": [],
                "score_reason": "[dry-run] 跳过分析",
                "tags": ["tutorial"],
                "content": item.get("summary", ""),
                "analyzed_at": now_iso,
            })
            continue

        result = analyze_item(provider, item)
        if result:
            analyzed.append(result)
        else:
            logger.warning("分析失败，保留原始条目: %s", title_short)
            analyzed.append({
                **item,
                "relevance_score": 5,
                "highlights": [],
                "score_reason": "LLM 分析失败，使用默认评分",
                "tags": ["tutorial"],
                "content": item.get("summary", ""),
                "analyzed_at": now_iso,
            })

    logger.info("分析完成: 成功处理 %d/%d 条", len(analyzed), total)
    return analyzed


# ── Step 3: 整理 ──────────────────────────────────────────────────────────

def _slug(text: str, max_len: int = 80) -> str:
    """生成 URL 友好的 slug。"""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    return slug[:max_len]


def deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 URL 去重，保留首次出现。

    Args:
        items: 待去重的条目列表。

    Returns:
        去重后的条目列表。
    """
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        url = item.get("url", "")
        if url and url not in seen:
            seen.add(url)
            result.append(item)
        elif not url:
            result.append(item)
    removed = len(items) - len(result)
    if removed:
        logger.info("去重: 移除 %d 条重复，保留 %d 条", removed, len(result))
    return result


def _normalize_relevance(item: dict[str, Any]) -> dict[str, Any]:
    """将 relevance_score 从 1-10 归一化到 0-1。"""
    score = item.get("relevance_score", 5)
    if isinstance(score, (int, float)) and score > 1:
        item["relevance_score"] = round(score / 10.0, 2)
    elif isinstance(score, (int, float)) and 0 <= score <= 1:
        pass
    else:
        item["relevance_score"] = 0.5
    return item


def _normalize_source(value: str) -> str:
    """规整 source 字段为 schema 接受的枚举值。"""
    if value in _VALID_SOURCES:
        return value
    if "github" in value.lower():
        return "github-trending"
    return "hackernews"


def validate_article(item: dict[str, Any]) -> tuple[bool, list[str]]:
    """校验条目是否符合 Article JSON Schema。

    Args:
        item: 待校验的条目。

    Returns:
        (is_valid, error_messages) 元组。
    """
    errors: list[str] = []

    # 必需字段
    if not isinstance(item.get("title"), str) or not item["title"].strip():
        errors.append("title 缺失或为空")
    if not isinstance(item.get("summary"), str) or not item["summary"].strip():
        errors.append("summary 缺失或为空")
    if not isinstance(item.get("tags"), list) or len(item["tags"]) == 0:
        errors.append("tags 缺失或为空")
    if not isinstance(item.get("relevance_score"), (int, float)):
        errors.append("relevance_score 缺失或类型错误")
    else:
        score = item["relevance_score"]
        if score < 0 or score > 1:
            errors.append(f"relevance_score 超出 [0, 1]: {score}")

    # source_url 整理
    url = item.get("source_url") or item.get("url")
    if isinstance(url, str) and url.strip():
        item["source_url"] = url
    else:
        errors.append("source_url 缺失")

    # source 规整
    item["source"] = _normalize_source(item.get("source", "hackernews"))

    # tags 过滤
    item["tags"] = [t for t in item.get("tags", []) if t in _VALID_TAGS][:5]

    return len(errors) == 0, errors


def organize(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """整理流程：去重 -> 归一化 -> 校验 -> 分类。

    Args:
        items: Analyze 产出的条目列表。

    Returns:
        (articles, skipped) 元组。articles 为通过校验的高相关条目，
        skipped 为校验失败或低相关的条目。
    """
    items = deduplicate(items)

    articles: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for item in items:
        item = _normalize_relevance(item)
        valid, errors = validate_article(item)

        if not valid:
            logger.warning(
                "校验失败 [%s]: %s", (item.get("title") or "?")[:50], "; ".join(errors)
            )
            item["status"] = "skipped"
            skipped.append(item)
            continue

        score = item.get("relevance_score", 0)
        if score < 0.5:
            logger.debug(
                "低相关跳过 [%.2f]: %s", score, (item.get("title") or "?")[:50]
            )
            item["status"] = "skipped"
            skipped.append(item)
            continue

        item["status"] = "reviewed"
        articles.append(item)

    logger.info("整理完成: 保留 %d 条, 跳过 %d 条", len(articles), len(skipped))
    return articles, skipped


# ── Step 4: 保存 ──────────────────────────────────────────────────────────

def _derive_author(title: str, item: dict[str, Any]) -> str:
    """从条目信息推导作者/组织名。

    Args:
        title: 条目标题。
        item: 完整条目字典。

    Returns:
        作者字符串。
    """
    existing = item.get("author", "")
    if existing and existing != "N/A":
        return str(existing)
    # GitHub 仓库: owner/repo -> 提取 owner
    if "/" in title:
        return title.split("/")[0]
    return "N/A"


def _generate_filename(item: dict[str, Any], existing_names: set[str]) -> str:
    """生成唯一文件名。

    Args:
        item: 文章条目。
        existing_names: 已使用的文件名集合（防冲突）。

    Returns:
        文件名，格式 {date}-{src}-{slug}.json。
    """
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    source_abbr = "gh" if item.get("source") == "github-trending" else "hn"
    title = item.get("title", "untitled")
    base_slug = _slug(title, 60) or "unknown"

    # 去冲突
    suffix = 0
    slug = base_slug
    while f"{today}-{source_abbr}-{slug}.json" in existing_names:
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    filename = f"{today}-{source_abbr}-{slug}.json"
    existing_names.add(filename)
    return filename


def _extract_date(iso_string: str) -> str:
    """从 ISO 8601 时间字符串提取 YYYYMMDD 日期。

    Args:
        iso_string: ISO 8601 格式时间字符串，如 "2026-07-29T16:00:00+08:00"。

    Returns:
        YYYYMMDD 格式字符串，解析失败时返回今天的日期。
    """
    try:
        dt = datetime.fromisoformat(iso_string)
        return dt.strftime("%Y%m%d")
    except (ValueError, TypeError):
        return datetime.now(TZ).strftime("%Y%m%d")


def _next_article_id(source: str, date_str: str, existing_ids: set[str]) -> str:
    """生成下一个文章 ID，格式 {source}-{YYYYMMDD}-{NNN}。

    Args:
        source: 来源，如 github-trending / hackernews。
        date_str: 日期 YYYYMMDD。
        existing_ids: 本次保存已使用的 ID 集合（防冲突）。

    Returns:
        唯一 ID 字符串。
    """
    prefix = f"{source}-{date_str}-"
    # 扫描 knowledge/articles/ 下已有 ID + 本次 session 中已分配 ID
    all_ids = existing_ids.copy()
    for p in ARTICLES_DIR.glob(f"*-{date_str}-*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            article_id = data.get("id", "")
            if article_id:
                all_ids.add(article_id)
        except (json.JSONDecodeError, OSError):
            pass

    max_seq = 0
    for aid in all_ids:
        if aid.startswith(prefix):
            try:
                seq = int(aid[len(prefix):])
                max_seq = max(max_seq, seq)
            except ValueError:
                pass

    next_seq = max_seq + 1
    return f"{prefix}{next_seq:03d}"


def save_articles(
    articles: list[dict[str, Any]], dry_run: bool,
) -> list[Path]:
    """将文章保存为独立 JSON 到 knowledge/articles/。

    Args:
        articles: 通过整理的文章列表。
        dry_run: True 时跳过写入，仅打印路径。

    Returns:
        已保存（或将要保存）的文件路径列表。
    """
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    existing_names = {p.name for p in ARTICLES_DIR.glob("*.json")}
    paths: list[Path] = []
    used_ids: set[str] = set()

    for item in articles:
        filename = _generate_filename(item, existing_names)
        filepath = ARTICLES_DIR / filename

        source = item.get("source", "hackernews")
        collected = item.get("collected_at", "")
        date_str = _extract_date(collected) if collected else datetime.now(TZ).strftime("%Y%m%d")
        article_id = _next_article_id(source, date_str, used_ids)
        used_ids.add(article_id)

        article = {
            "id": article_id,
            "title": item.get("title", ""),
            "source": source,
            "source_url": item.get("source_url", item.get("url", "")),
            "author": _derive_author(item.get("title", ""), item),
            "summary": item.get("summary", ""),
            "content": item.get("content", item.get("summary", "")),
            "highlights": item.get("highlights", []),
            "score_reason": item.get("score_reason", ""),
            "tags": item.get("tags", []),
            "relevance_score": item.get("relevance_score", 0),
            "collected_at": item.get("collected_at", ""),
            "analyzed_at": item.get("analyzed_at", ""),
            "status": item.get("status", "draft"),
        }

        if dry_run:
            logger.info("[dry-run] 将保存: %s", filepath)
        else:
            filepath.write_text(
                json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            logger.info("已保存: %s", filepath)

        paths.append(filepath)

    return paths


# ── 主流程 ──────────────────────────────────────────────────────────────

def run_pipeline(
    sources: list[str],
    limit: int,
    dry_run: bool,
    verbose: bool,
) -> None:
    """执行四步流水线：Collect → Analyze → Organize → Save。

    Args:
        sources: 数据源列表，支持 "github" 和 "rss"。
        limit: GitHub 采集条目上限。
        dry_run: 干跑模式，跳过 LLM 和文件写入。
        verbose: 详细日志。
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("流水线启动: sources=%s limit=%d dry_run=%s", sources, limit, dry_run)

    all_raw: list[dict[str, Any]] = []

    with httpx.Client() as http_client:
        # ── Step 1: 采集 ──
        if "github" in sources:
            items = collect_github(limit, http_client)
            if items:
                _save_raw(items, "github")
            all_raw.extend(items)

        if "rss" in sources:
            items = collect_rss(http_client, limit)
            all_raw.extend(items)

    if not all_raw:
        logger.warning("未采集到任何内容，流水线终止")
        return

    logger.info("Step 1 完成: 共采集 %d 条原始内容", len(all_raw))

    # ── Step 2: 分析 ──
    provider = None
    try:
        provider = OpenAICompatibleProvider()
    except ValueError as e:
        logger.warning("无法创建 LLM Provider: %s，跳过分析步骤", e)

    if provider is not None:
        try:
            analyzed = analyze_items(provider, all_raw, dry_run)
        finally:
            provider.close()
    else:
        analyzed = all_raw

    logger.info("Step 2 完成: 分析 %d 条", len(analyzed))

    # ── Step 3: 整理 ──
    articles, skipped = organize(analyzed)
    logger.info("Step 3 完成: 保留 %d 条, 跳过 %d 条", len(articles), len(skipped))

    # ── Step 4: 保存 ──
    saved = save_articles(articles, dry_run)
    logger.info("Step 4 完成: 保存 %d 篇文章", len(saved))

    # ── 汇总 ──
    logger.info("=" * 60)
    logger.info("流水线执行完成")
    logger.info("  采集总数: %d", len(all_raw))
    logger.info("  分析条目: %d", len(analyzed))
    logger.info("  保留文章: %d", len(articles))
    logger.info("  跳过条目: %d", len(skipped))
    logger.info("  保存文件: %d", len(saved))
    if dry_run:
        logger.info("  [DRY-RUN] 未实际调用 LLM / 写入文件")
    logger.info("=" * 60)


# ── CLI ──────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    """CLI 入口。

    Args:
        argv: 命令行参数列表，为 None 时使用 sys.argv[1:]。
    """
    parser = argparse.ArgumentParser(
        prog="pipeline",
        description="AI 知识库自动化流水线: Collect → Analyze → Organize → Save",
    )
    parser.add_argument(
        "--sources",
        default="github,rss",
        help="数据源，逗号分隔 (github, rss)，默认: github,rss",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="GitHub 采集条目数，默认: 10（前 10 排名）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="干跑模式，不调用 LLM 也不写入文件",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="输出 DEBUG 级别详细日志",
    )

    args = parser.parse_args(argv)
    sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]

    valid_sources = {"github", "rss"}
    for src in sources:
        if src not in valid_sources:
            parser.error(f"不支持的数据源: {src}，可选: github, rss")

    if args.limit < 1:
        parser.error("--limit 必须为正整数")

    run_pipeline(
        sources=sources,
        limit=args.limit,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
