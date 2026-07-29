#!/usr/bin/env python3
"""MCP Server — 本地知识库搜索服务。

通过 JSON-RPC 2.0 over stdio 暴露三个工具：
  - search_articles: 关键词搜索文章
  - get_article:    按 ID 获取完整内容
  - knowledge_stats: 知识库统计
"""

import json
import sys
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

ARTICLES_DIR = Path(__file__).resolve().parent / "knowledge" / "articles"

_articles_cache: list[dict] = []
_cache_loaded = False


def _load_articles() -> list[dict]:
    global _articles_cache, _cache_loaded
    if _cache_loaded:
        return _articles_cache
    articles: list[dict] = []
    if ARTICLES_DIR.is_dir():
        for fp in sorted(ARTICLES_DIR.glob("*.json")):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                articles.append(data)
            except (json.JSONDecodeError, OSError):
                continue
    _articles_cache = articles
    _cache_loaded = True
    return _articles_cache


def _match_keywords(text: str, keyword: str) -> bool:
    return keyword.lower() in text.lower()


def search_articles(keyword: str, limit: int = 5) -> dict[str, Any]:
    articles = _load_articles()
    results = []
    for a in articles:
        if _match_keywords(a.get("title", ""), keyword) or _match_keywords(a.get("summary", ""), keyword):
            results.append({
                "id": a.get("id"),
                "title": a.get("title"),
                "source": a.get("source"),
                "summary": a.get("summary"),
                "tags": a.get("tags", []),
                "relevance_score": a.get("relevance_score"),
            })
            if len(results) >= limit:
                break
    return {"count": len(results), "results": results}


def get_article(article_id: str) -> dict[str, Any]:
    articles = _load_articles()
    for a in articles:
        if a.get("id") == article_id:
            return {"found": True, "article": a}
    return {"found": False, "article": None, "message": f"Article '{article_id}' not found"}


def knowledge_stats() -> dict[str, Any]:
    articles = _load_articles()
    total = len(articles)
    sources = Counter(a.get("source", "unknown") for a in articles)
    all_tags: Counter[str] = Counter()
    for a in articles:
        for t in a.get("tags", []):
            all_tags[t] += 1
    return {
        "total_articles": total,
        "source_distribution": dict(sources.most_common()),
        "top_tags": dict(all_tags.most_common(10)),
    }


TOOLS = {
    "search_articles": {
        "name": "search_articles",
        "description": "按关键词搜索文章标题和摘要，返回匹配的文章列表",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词"},
                "limit": {"type": "integer", "description": "返回结果数量上限，默认 5", "default": 5},
            },
            "required": ["keyword"],
        },
        "handler": lambda args: search_articles(
            keyword=args["keyword"],
            limit=args.get("limit", 5),
        ),
    },
    "get_article": {
        "name": "get_article",
        "description": "按文章 ID 获取完整文章内容",
        "inputSchema": {
            "type": "object",
            "properties": {
                "article_id": {"type": "string", "description": "文章唯一 ID"},
            },
            "required": ["article_id"],
        },
        "handler": lambda args: get_article(article_id=args["article_id"]),
    },
    "knowledge_stats": {
        "name": "knowledge_stats",
        "description": "返回知识库统计信息：文章总数、来源分布、热门标签",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "handler": lambda _args: knowledge_stats(),
    },
}


def _send_json(data: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def _serve() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        req_id = request.get("id")
        method = request.get("method", "")

        if method == "initialize":
            _send_json({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "mcp-knowledge-server", "version": "1.0.0"},
                    "capabilities": {"tools": {}},
                },
            })

        elif method == "tools/list":
            tools_list = [
                {"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
                for t in TOOLS.values()
            ]
            _send_json({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools_list}})

        elif method == "tools/call":
            params = request.get("params", {})
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            tool = TOOLS.get(tool_name)
            if not tool:
                _send_json({
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"},
                })
            else:
                try:
                    result = tool["handler"](tool_args)
                    _send_json({
                        "jsonrpc": "2.0", "id": req_id,
                        "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]},
                    })
                except Exception as e:
                    _send_json({
                        "jsonrpc": "2.0", "id": req_id,
                        "error": {"code": -32603, "message": str(e)},
                    })

        elif method == "notifications/initialized":
            pass

        else:
            _send_json({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Method '{method}' not found"},
            })


if __name__ == "__main__":
    _serve()
