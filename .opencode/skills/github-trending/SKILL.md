---
name: github-trending
description: 当需要采集 GitHub 热门开源项目时使用此技能
allowed-tools: read, grep, glob, webfetch
---

# GitHub Trending 采集技能

## 使用场景

- 每日/每周定时采集 GitHub 上 AI 领域的开源项目
- 需要按热度筛选 Top N 项目时
- 需要将采集结果格式化并存入 `knowledge/raw/` 时

## 执行步骤

### 第 1 步：搜索热门仓库

调用 GitHub Search API，按 stars 降序搜索 AI/LLM/Agent 相关仓库。

```
GET https://api.github.com/search/repositories
参数：
  q = topic:llm OR topic:agent OR topic:rag OR topic:machine-learning
  sort = stars
  order = desc
  per_page = 30
```

备选关键词补充搜索：`ai`, `gpt`, `transformer`, `fine-tuning`, `prompt-engineering`, `open-source-model`

### 第 2 步：提取信息

从 API 返回结果中提取每条仓库的关键字段：

| 字段     | 来源                     |
| -------- | ------------------------ |
| name     | `full_name`              |
| url      | `html_url`               |
| stars    | `stargazers_count`       |
| language | `language`               |
| topics   | `topics`                 |
| description | `description`         |

### 第 3 步：过滤

**纳入规则**（满足任一即保留）：
- topics 中包含 `ai`, `llm`, `agent`, `rag`, `gpt`, `transformer`, `fine-tuning`, `prompt-engineering`, `embedding`, `multimodal`, `tool-use` 之一
- description 命中关键词：`AI`, `LLM`, `GPT`, `agent`, `RAG`, `transformer`, `fine-tune`, `prompt`

**排除规则**（满足任一即丢弃）：
- topics 或 name 包含 `awesome`, `awesome-list`, `curated-list`
- description 以 `A curated list of` 或 `Awesome` 开头
- 与已有的 `knowledge/raw/*.json` 中条目 URL 相同

### 第 4 步：去重

与 `knowledge/raw/` 目录下历史采集文件比对，按 `url` 去重：
1. 使用 `glob` 查找 `knowledge/raw/github-trending-*.json`
2. 读取已有文件中的 `url` 集合
3. 从本次结果中剔除已存在的 URL

### 第 5 步：撰写中文摘要

对每条保留的仓库，按以下公式生成中文摘要（≤80 字）：

```
{项目名}是一个{做什么}的开源项目，其核心亮点是{为什么值得关注}。
```

示例：`AutoGPT 是一个自主 AI Agent 构建平台，其核心亮点是首创的规划-执行-反思 Agent 循环范式。`

### 第 6 步：排序取 Top 15

将所有保留条目按 `stars` 降序排列，取前 15 条作为最终输出。

### 第 7 步：输出 JSON 文件

将结果写入 `knowledge/raw/github-trending-YYYY-MM-DD.json`（日期使用当前日期）。

## 注意事项

- GitHub API 无需认证即可搜索，但限制 **10 次/分钟**。如需更高频率，请配置 `GITHUB_TOKEN` 环境变量（限频提升至 30 次/分钟）
- 所有 HTTP 请求必须设置 timeout（30s），失败时重试 3 次
- 摘要必须为中文，禁止直接复制英文 description 作为摘要
- 禁止编造不存在的项目或数据
- 过滤时注意：部分仓库 topics 字段为空，需同时检查 description 和 name
- 如果单次搜索返回不足 15 条，应补充其他关键词搜索并合并结果

## 输出格式

保存路径：`knowledge/raw/github-trending-YYYY-MM-DD.json`

```json
{
  "source": "github-trending",
  "skill": "github-trending",
  "collected_at": "2026-07-23T10:30:00+08:00",
  "items": [
    {
      "name": "owner/repo",
      "url": "https://github.com/owner/repo",
      "summary": "中文摘要（≤80字）",
      "stars": 12345,
      "language": "Python",
      "topics": ["llm", "agent", "rag"]
    }
  ]
}
```

### 字段说明

| 字段           | 类型     | 说明                                       |
| -------------- | -------- | ------------------------------------------ |
| `source`       | string   | 固定值 `github-trending`                   |
| `skill`        | string   | 固定值 `github-trending`                   |
| `collected_at` | string   | 采集时间（ISO 8601 + 时区）                |
| `items[].name` | string   | 仓库全名（owner/repo 格式）                |
| `items[].url`  | string   | 仓库链接                                   |
| `items[].summary` | string | 中文摘要，≤80 字                          |
| `items[].stars` | int     | 星标数                                     |
| `items[].language` | string | 主要编程语言                             |
| `items[].topics` | string[] | 项目主题标签                             |
