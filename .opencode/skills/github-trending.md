# GitHub Trending Skill

## 功能

从 GitHub Trending 页面采集热门仓库信息，过滤 AI/LLM/Agent 相关项目。

## API

- **接口**：`https://github.com/trending?since=daily`
- **备选**：`https://gh-trending-api.herokuapp.com/repositories` (非官方 API)

## 采集流程

1. 请求 GitHub Trending 页面或 API
2. 解析仓库列表（名称、描述、语言、stars、forks）
3. 使用关键词匹配过滤 AI 相关项目
4. 去重（与 `knowledge/raw/` 中已有条目对比）
5. 输出原始 JSON 文件

## 过滤关键词

`ai`, `llm`, `gpt`, `agent`, `rag`, `embedding`, `vector`, `transformer`, `fine-tune`, `prompt`, `langchain`, `llama`, `openai`, `anthropic`, `chatbot`, `copilot`, `diffusion`, `tts`, `stt`, `ocr`

## 错误处理

- 请求超时：30 秒，重试 3 次，指数退避
- 页面结构变更：记录 WARNING 日志，降级使用非官方 API
- 网络不可达：记录 ERROR 日志，终止本次采集
