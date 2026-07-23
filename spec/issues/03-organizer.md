# 03 — Organizer

## depends_on

- `#00 Schema` — 公共契约，遵循 Article Schema 入库、状态机流转、文件命名、error 结构、推送重试策略
- `#01 Collector` — 依赖 Collector 的原始 URL/title 做历史交叉去重
- `#02 Analyzer` — 依赖 Analyzer 产出的 AnalyzedEntry（含 summary/highlights/tags/relevance_score）
- `wechat-push.skill.md` — 企微/飞书推送指引，当前已删除，需恢复
- `openclaw SDK` — 微信/飞书消息通道，需集成到项目依赖
- `knowledge/articles/*.json` — 历史入库条目，按 URL + title 联合去重

## acceptance

- [ ] 正确读取 Analyzer 产出，接收前检查 `error` 字段，非空则终止
- [ ] 按 URL + title 相似度联合去重，重复条目标记为 `skipped`
- [ ] relevance_score ≤ 4 → `skipped`，≥ 5 → `reviewed`
- [ ] 必填字段校验：title/url/source 缺失 → skipped；其余字段缺失 → 补 "N/A"
- [ ] 写入 `knowledge/articles/{date}-{source}-{slug}.json`，字段对齐 13 字段 Article Schema
- [ ] `id` 为 UUID v4，`collected_at`/`analyzed_at` 从上游继承，status 按规则判定
- [ ] 已标记 `published` 的 JSON 文件未被修改（红线）
- [ ] `wechat-push.skill.md` 恢复并可用
- [ ] `reviewed` 条目通过 openclaw 推送到微信/飞书
- [ ] 推送成功后 status → `published`；推送失败记录 `push_status=failed`，下次重试
- [ ] 整理失败时输出带 `error` 字段，结构：`{ node, message, failed_articles[], push_status, timestamp }`

---

## 角色定位

整理与分发 Agent，读取 Analyzer 产出的 AnalyzedEntry，完成去重、校验、过滤后入库 `knowledge/articles/`，并将 `reviewed` 条目推送到微信/飞书。

Agent 定义详见：`.opencode/agents/organizer.md`

---

## Article 入库 Schema（最终输出）

```json
{
  "id": "UUID v4（Organizer 生成）",
  "title": "string",
  "source": "github-trending | hackernews",
  "source_url": "string",
  "author": "string（从 URL 提取或填 N/A）",
  "summary": "string",
  "content": "string（Markdown 结构化正文）",
  "highlights": ["string"],
  "score_reason": "string（评分理由）",
  "tags": ["string"],
  "relevance_score": "float",
  "collected_at": "ISO 8601（从 Collector 继承）",
  "analyzed_at": "ISO 8601（从 Analyzer 继承）",
  "status": "reviewed | skipped"
}
```

### 文件命名

```
knowledge/articles/{date}-{source}-{slug}.json
```

- `date`: `YYYY-MM-DD`
- `source`: `gh` / `hn`
- `slug`: 标题简化，仅字母数字和连字符，≤50 字符

### 状态机

```
draft ──(score ≥ 5)──→ reviewed ──(推送成功)──→ published
  │
  └──(score ≤ 4 / 重复)──→ skipped
```

> **红线**：`published` 文件禁止修改。

### 消息推送格式

```
📌 [标签列表]
标题：{title}
摘要：{summary}
评分：{relevance_score} | 来源：{source}
链接：{source_url}
```

---

## 公共依赖

| 依赖项 | 影响范围 |
|--------|----------|
| wechat-push.skill.md + openclaw SDK | Organizer 专用 |
| `knowledge/articles/` 目录 | Organizer 写入，Collector 参考去重 |
| 13 字段 Article Schema | 三个 Agent 共同遵守 |

---

## 错误传递

```json
{
  "error": {
    "node": "organizer",
    "message": "具体错误原因",
    "failed_articles": ["id1", "id2"],
    "push_status": "success | partial | failed",
    "timestamp": "ISO 8601"
  },
  "articles": [...]
}
```

### 推送重试

推送失败保持 status=`reviewed`，下次 pipeline 运行时重试。
