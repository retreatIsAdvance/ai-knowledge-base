# 01 — Collector

## depends_on

- `#00 Schema` — 公共契约，Collector 按 RawEntry Schema 产出，遵循 error 结构、文件路径、重试策略
- `github-trending.skill.md` — GitHub Trending 抓取指引，当前已删除，需恢复
- `hackernews.skill.md` — Hacker News 抓取指引，当前已删除，需恢复
- `knowledge/articles/*.json` — 历史入库条目，用于 URL 交叉去重

## acceptance

- [ ] `github-trending.skill.md` 恢复并可用，能正确抓取 GH Trending Top 50
- [ ] `hackernews.skill.md` 恢复并可用，能正确抓取 HN Top Stories
- [ ] 两个源采集合计 ≥ 15 条 AI/LLM/Agent 相关条目
- [ ] 输出格式符合 RawEntry Schema（title/url/source/popularity/summary 五字段齐全）
- [ ] 按 popularity 降序排列，无重复 URL
- [ ] 输出末尾带 `collected_at` 时间戳（ISO 8601）
- [ ] 采集失败时输出带 `error` 字段，结构：`{ node, message, source, timestamp }`

---

## 角色定位

采集 Agent，每日从 GitHub Trending 和 Hacker News 抓取 AI/LLM/Agent 领域热门条目，产出 RawEntry 交付给 Analyzer。

Agent 定义详见：`.opencode/agents/collector.md`

---

## RawEntry 输出 Schema（对 Analyzer 约定）

```json
{
  "title": "string（原始语言，不翻译）",
  "url": "string（可访问原始链接）",
  "source": "github-trending | hackernews",
  "popularity": "int（GH: stars / HN: upvotes）",
  "summary": "string（中文摘要，≤80 字）"
}
```

### 落盘路径

| 来源 | 文件路径 |
|------|----------|
| GitHub Trending | `knowledge/raw/github-trending-{YYYY-MM-DD}.json` |
| Hacker News | `knowledge/raw/hackernews-{YYYY-MM-DD}.json` |

---

## 公共依赖（与其他 Agent 共用）

| 依赖项 | 影响范围 |
|--------|----------|
| 筛选关键词集（20 个 AI/LLM/Agent 关键词） | Collector 过滤 + Analyzer/Organizer 标签参考 |
| `source` 枚举值 `github-trending` / `hackernews` | 三个 Agent 统一使用 |
| `collected_at` 时间戳 | Collector 产出，Analyzer/Organizer 继承 |
| 文件落盘：Collector 仅 stdout 输出，pipeline 统一写入 | 与 pipeline 的职责边界 |

---

## 错误传递

```json
{
  "error": {
    "node": "collector",
    "message": "具体错误原因",
    "source": "github-trending | hackernews | both",
    "timestamp": "ISO 8601"
  },
  "entries": []
}
```

下游 Analyzer 检查 `error` 字段，非空则终止链路。

### 重试

HTTP 请求 3 次，指数退避 1s / 2s / 4s。
