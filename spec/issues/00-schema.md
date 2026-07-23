# 00 — 公共 Schema 与契约

## depends_on

None — 无上游依赖，所有 Agent 开发以此为基座。

## acceptance

- [ ] RawEntry Schema 落 `spec/schemas/raw-entry.json`
- [ ] AnalyzedEntry Schema 落 `spec/schemas/analyzed-entry.json`
- [ ] Article Schema 落 `spec/schemas/article.json`
- [ ] AgentError Schema 落 `spec/schemas/error.json`
- [ ] ArticleStatus 状态机定义：`draft → reviewed → published`，`draft → skipped`
- [ ] `source` 枚举值定义：`github-trending` / `hackernews`，含落盘缩写 `gh` / `hn`
- [ ] 预定义标签集定义：20 个标签，Analyzer 打标 + Organizer 校验共用
- [ ] 文件路径约定：`knowledge/raw/{source}-{date}.json`，`knowledge/articles/{date}-{source}-{slug}.json`
- [ ] 重试策略约定：HTTP 3 次（1s/2s/4s），LLM 2 次

---

## 角色定位

定义 Collector / Analyzer / Organizer 三个 Agent 之间的公共数据契约，是协作的语法层基础。不涉及具体实现，仅定义"数据结构长什么样"和"数据放哪里"。

---

## RawEntry Schema（Collector 产出 → Analyzer 消费）

```json
{
  "title": "string（原始语言，不翻译）",
  "url": "string（可访问原始链接）",
  "source": "github-trending | hackernews",
  "popularity": "int（GH: stars / HN: upvotes）",
  "summary": "string（中文摘要，≤80 字）",
  "collected_at": "ISO 8601 + 时区"
}
```

### 质量约束

| 约束 | 值 |
|------|----|
| 两源合计条目 | ≥ 15 |
| summary 长度 | ≤ 80 字（中文） |
| 排序 | popularity 降序 |
| 重复 | URL 唯一 |

---

## AnalyzedEntry Schema（Analyzer 产出 → Organizer 消费）

```json
{
  "title": "string（继承自 RawEntry）",
  "url": "string（继承）",
  "source": "github-trending | hackernews（继承）",
  "popularity": "int（继承）",
  "summary": "string（中文摘要，80–200 字，重写）",
  "highlights": ["string（2–3 条技术亮点）"],
  "relevance_score": "int（1–10）",
  "score_reason": "string（评分理由）",
  "tags": ["string（从预定义标签集选取，≤5 个）"],
  "analyzed_at": "ISO 8601 + 时区"
}
```

### 标签集（预定义，不可自创）

```
llm, agent, rag, embedding, vector-db, prompt-engineering, fine-tuning,
transformer, multimodal, tool-use, evaluation, safety, deployment, benchmark,
open-source, closed-source, framework, tutorial, paper, opinion
```

### 评分分档

| 分数 | 等级 | 含义 |
|------|------|------|
| 9–10 | S | 颠覆性 / 行业里程碑 |
| 7–8 | A | 成熟工具 / 重要改进 |
| 5–6 | B | 值得了解 |
| 1–4 | C | 可跳过（Organizer 舍弃） |

---

## Article Schema（Organizer 产出 → 最终入库）

```json
{
  "id": "string（UUID v4）",
  "title": "string",
  "source": "github-trending | hackernews",
  "source_url": "string",
  "author": "string",
  "summary": "string",
  "content": "string（Markdown 结构化正文）",
  "highlights": ["string"],
  "score_reason": "string",
  "tags": ["string"],
  "relevance_score": "float",
  "collected_at": "string（ISO 8601，从 Collector 继承）",
  "analyzed_at": "string（ISO 8601，从 Analyzer 继承）",
  "status": "draft | reviewed | published | skipped"
}
```

### 文件命名

```
knowledge/articles/{date}-{source}-{slug}.json
```

| 组成部分 | 取值 |
|----------|------|
| `date` | `YYYY-MM-DD` |
| `source` | `gh`（GitHub Trending）/ `hn`（Hacker News） |
| `slug` | 标题简化，字母数字 + 连字符，≤50 字符 |

### 状态机

```
draft ──(score ≥ 5)──→ reviewed ──(推送成功)──→ published
  │
  └──(score ≤ 4 / 重复)──→ skipped
```

| 规则 | status |
|------|--------|
| relevance_score ≥ 5 | `reviewed` |
| relevance_score ≤ 4 | `skipped` |
| URL / title 重复 | `skipped` |
| 推送完成 | `published` |

> **红线**：`published` 文件禁止修改。

---

## Error 契约（三个 Agent 统一）

所有 Agent 在失败时输出中需包含 `error` 字段：

```json
{
  "error": {
    "node": "collector | analyzer | organizer",
    "message": "string（人类可读错误原因）",
    "timestamp": "ISO 8601 + 时区"
  },
  "entries": []
}
```

### 特有字段

| Agent | 额外字段 |
|-------|---------|
| Collector | `source`: `github-trending \| hackernews \| both` |
| Analyzer | `failed_entries`: `["url1", "url2"]` |
| Organizer | `failed_articles`: `["id1"]`, `push_status`: `success \| partial \| failed` |

### 下游处理规则

- 任一 Agent 读到 `error` 非空 → 终止当前链路，透传 error
- `entries` 为空 + 无 `error` → WARNING，终止

---

## 文件路径约定

```
knowledge/
├── raw/
│   ├── github-trending-{YYYY-MM-DD}.json    ← Collector 输出
│   └── hackernews-{YYYY-MM-DD}.json         ← Collector 输出
└── articles/
    ├── {date}-gh-{slug}.json                ← Organizer 输出
    └── {date}-hn-{slug}.json                ← Organizer 输出
```

---

## 重试策略

| 场景 | 次数 | 间隔 |
|------|------|------|
| HTTP 请求（Collector 抓取） | 3 | 1s / 2s / 4s |
| LLM 调用（Analyzer 分析） | 2 | 即时重试 |
| 消息推送（Organizer 分发） | 不重试 | 失败保持 `reviewed`，下次 pipeline 再推 |
