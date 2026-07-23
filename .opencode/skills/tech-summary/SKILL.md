---
name: tech-summary
description: 当需要对采集的技术内容进行深度分析总结时使用此技能
allowed-tools: Read, Grep, Glob, WebFetch
---

# 技术深度分析总结技能

## 使用场景

- 阅读 `knowledge/raw/` 中采集完成的技术条目后，需要对每条内容进行结构化分析
- 需要从批量条目中发现共同主题和新概念趋势
- 需要将分析结果输出为标准化 JSON，供下游整理分发使用

## 执行步骤

### 第 1 步：读取最新采集文件

使用 `glob` 查找 `knowledge/raw/` 下当日最新的采集文件：

```
knowledge/raw/github-trending-YYYY-MM-DD.json
knowledge/raw/hackernews-YYYY-MM-DD.json
```

使用 `read` 读取文件内容，获取待分析的条目列表。

### 第 2 步：逐条深度分析

对每条条目进行四维分析：

**a. 摘要（≤50 字）**

用中文一句话概括项目的核心价值，不使用形容词堆砌，直接说明它解决了什么问题。

**b. 技术亮点（2–3 条，用事实说话）**

每条亮点需包含具体的技术事实，避免空洞评价：

| 差（禁止） | 好（推荐） |
|-----------|-----------|
| 性能很好 | 推理延迟从 200ms 降至 30ms |
| 很受欢迎 | GitHub 30 天内增长 5k star |
| 架构优秀 | 基于 MoE 架构，8 个专家子网动态路由 |
| 支持多种模型 | 兼容 GPT-4/Claude/Gemini/Qwen 等 15+ 模型 |

**c. 评分（1–10，附理由）**

基于以下标准评分，必须给出具体评分理由：

| 分数 | 等级 | 标准 |
|------|------|------|
| 9–10 | S | 改变格局 — 颠覆性技术突破、行业里程碑、重大模型发布 |
| 7–8 | A | 直接有帮助 — 成熟可用工具/框架、重要技术改进 |
| 5–6 | B | 值得了解 — 有一定参考价值但非必需追踪 |
| 1–4 | C | 可略过 — 相关性低、信息量小、纯营销内容 |

**强制约束：每 15 个项目中 9–10 分不超过 2 个**。若前 2 个名额已用满，后续即使符合 S 档标准也降为 8 分并在理由中说明。

**d. 标签建议**

从预定义标签集中选取 2–5 个最匹配的标签：

```
llm, agent, rag, embedding, vector-db, prompt-engineering, fine-tuning,
transformer, multimodal, tool-use, evaluation, safety, deployment,
benchmark, open-source, framework, tutorial, paper, opinion
```

### 第 3 步：趋势发现

横向对比所有条目，识别并输出：

**a. 共同主题**

- 找出出现频率最高的 2–3 个技术方向（如"多模态 Agent"、"推理优化"）
- 说明这些方向在本批次条目中的具体体现

**b. 新概念**

- 识别本批次中出现的新术语、新范式或新工具链
- 对每个新概念用一句话解释其含义
- 若无明显新概念则标注 `"无"`

### 第 4 步：输出分析结果 JSON

将分析结果以 JSON 格式输出到 stdout，格式见下方「输出格式」。

## 注意事项

- 摘要严禁直接复制项目 description 翻译，必须基于理解重新提炼
- 亮点必须使用事实和数据支撑，禁止使用"非常强大""极其好用"等空洞措辞
- 评分必须严格执行约束：15 条中 9–10 分不超过 2 个
- 标签仅从预定义集合中选取，禁止自创标签
- 所有 HTTP 请求设置 30s timeout，失败时重试 3 次（指数退避）
- 趋势发现需基于实际数据归纳，不得编造不存在的趋势

## 输出格式

标准输出（stdout），不做文件写入，最终一行单一 JSON：

```json
{
  "skill": "tech-summary",
  "analyzed_at": "2026-07-23T10:35:00+08:00",
  "trends": {
    "themes": [
      {
        "name": "主题名称",
        "count": 5,
        "detail": "在本批次中体现为：项目A、项目B、项目C 均围绕该方向"
      }
    ],
    "new_concepts": [
      {
        "term": "新术语",
        "explain": "一句话解释"
      }
    ]
  },
  "items": [
    {
      "title": "项目或文章标题",
      "url": "https://原始链接",
      "source": "github-trending | hackernews",
      "popularity": 12345,
      "summary": "中文摘要（≤50字）",
      "highlights": [
        "具体事实亮点1",
        "具体事实亮点2",
        "具体事实亮点3"
      ],
      "relevance_score": 8,
      "score_reason": "评分理由",
      "tags": ["llm", "agent", "open-source"]
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `skill` | string | 固定值 `tech-summary` |
| `analyzed_at` | string | 分析完成时间（ISO 8601 + 时区） |
| `trends.themes[].name` | string | 趋势主题名称 |
| `trends.themes[].count` | int | 该主题在本批次中出现的次数 |
| `trends.themes[].detail` | string | 趋势在本批次中的具体体现说明 |
| `trends.new_concepts[].term` | string | 新术语/概念名称 |
| `trends.new_concepts[].explain` | string | 对新概念的一句话解释 |
| `items[].title` | string | 项目或文章标题 |
| `items[].url` | string | 原始链接 |
| `items[].source` | string | 数据来源 |
| `items[].popularity` | int | 热度指标 |
| `items[].summary` | string | 中文摘要，≤50 字 |
| `items[].highlights` | string[] | 2–3 条基于事实的技术亮点 |
| `items[].relevance_score` | int | 相关度评分 1–10 |
| `items[].score_reason` | string | 评分理由 |
| `items[].tags` | string[] | 2–5 个预定义分类标签 |
