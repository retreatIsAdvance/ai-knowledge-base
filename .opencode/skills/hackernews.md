# Hacker News Skill

## 功能

从 Hacker News 采集技术热帖，过滤 AI/LLM/Agent 相关讨论。

## API

- **最佳故事**：`https://hacker-news.firebaseio.com/v0/topstories.json`
- **单条详情**：`https://hacker-news.firebaseio.com/v0/item/{id}.json`
- **官方搜索**：`https://hn.algolia.com/api/v1/search?query={keyword}&tags=story`

## 采集流程

1. 拉取 Top Stories ID 列表（前 100 条）
2. 批量获取每条详情（标题、链接、作者、评分、评论数）
3. 使用关键词匹配过滤 AI 相关帖子
4. 通过 Algolia API 补充关键词搜索
5. 合并去重后输出原始 JSON 文件

## 过滤关键词

`AI`, `LLM`, `GPT`, `ChatGPT`, `Claude`, `Gemini`, `Copilot`, `RAG`, `agent`, `vector database`, `embedding`, `transformer`, `fine-tuning`, `LoRA`, `prompt engineering`, `langchain`, `open source model`

## 错误处理

- Firebase API 不可用：降级使用 Algolia 搜索 API
- 单条详情获取失败：跳过，记录 WARNING
- 批量请求限频：每次 500ms 间隔
- 整体超时：120 秒
