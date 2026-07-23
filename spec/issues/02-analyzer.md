# 02 — Analyzer

## depends_on

- `#00 Schema` — 公共契约，遵循 AnalyzedEntry Schema 产出，标签集、评分分档、error 结构、重试策略均由此定义
- `#01 Collector` — 依赖 Collector 产出的 RawEntry JSON（`knowledge/raw/*.json`）
- `LLM 调用能力` — 核心依赖，需保证 LLM 可用并正确返回结构化结果

## acceptance

- [ ] 能正确读取 `knowledge/raw/` 下所有当日 RawEntry 文件
- [ ] 读取时先检查 `error` 字段：非空则终止分析并透传错误
- [ ] 每条输出含 `analyzed_at` 时间戳（ISO 8601）
- [ ] 每条 `summary` 为中文 80–200 字，`highlights` 为 2–3 条具体亮点
- [ ] 每条 `tags` 均来自预定义标签集，未使用自创标签
- [ ] 每条 `relevance_score` 在 1–10 范围内，≤4 分的条目给出明确降级原因
- [ ] 分析失败时输出带 `error` 字段，结构：`{ node, message, failed_entries[], timestamp }`
- [ ] LLM 调用遵循重试策略：2 次重试

---

## 角色定位

分析 Agent，读取 Collector 产出的 RawEntry，调用大模型逐条生成摘要、亮点、标签和评分，产出 AnalyzedEntry 交付给 Organizer。

Agent 定义详见：`.opencode/agents/analyzer.md`

---

## AnalyzedEntry 输出 Schema（对 Organizer 约定）

```json
{
  "title": "string（继承自 Collector）",
  "url": "string（继承，必要时回访原文）",
  "source": "github-trending | hackernews（继承）",
  "popularity": "int（继承）",
  "summary": "string（中文摘要，80–200 字，重写版本）",
  "highlights": ["string（2–3 条技术亮点）"],
  "relevance_score": "int（1–10）",
  "tags": ["string（从预定义标签集中选取，≤5 个）"],
  "analyzed_at": "ISO 8601 时间戳"
}
```

### 标签集（与 Organizer 共用校验）

```
llm, agent, rag, embedding, vector-db, prompt-engineering, fine-tuning,
transformer, multimodal, tool-use, evaluation, safety, deployment, benchmark,
open-source, closed-source, framework, tutorial, paper, opinion
```

### 评分分档（Organizer 依此过滤）

| 分数 | 等级 | Organizer 处理 |
|------|------|---------------|
| 9–10 | S | 入库 → `reviewed` |
| 7–8 | A | 入库 → `reviewed` |
| 5–6 | B | 入库 → `reviewed` |
| 1–4 | C | **丢弃** → `skipped` |

> ≤4 被 Organizer 舍弃，≥5 入库。Analyzer 需对此边界负责。

---

## 公共依赖

| 依赖项 | 影响范围 |
|--------|----------|
| 预定义标签集 | Analyzer 打标 + Organizer 校验 |
| 评分标准 S/A/B/C | 三个 Agent 共同理解 |

---

## 错误传递

```json
{
  "error": {
    "node": "analyzer",
    "message": "具体错误原因",
    "failed_entries": ["url1", "url2"],
    "timestamp": "ISO 8601"
  },
  "entries": [...]
}
```

上游 Collector 失败检查逻辑：
- `error` 非空 → 终止分析，透传错误
- `entries` 为空 → WARNING，终止
- 部分源失败 → 仅分析可用数据，error 透传

### 重试

LLM 调用 2 次重试。
