# AI Knowledge Base Assistant

## 项目概述

AI 知识库助手是一个自动化的技术情报聚合与分发系统。系统定时从 GitHub Trending 和 Hacker News 采集 AI/LLM/Agent 领域的开源项目和技术动态，通过大模型进行语义分析和结构化整理后存储为 JSON 条目，最终经由多渠道（微信/飞书）推送给订阅用户，帮助团队持续追踪 AI 领域前沿进展。

## 技术栈

| 组件       | 选型                                           |
| ---------- | ---------------------------------------------- |
| 运行环境   | Python 3.12                                    |
| 编排框架   | opencode + 国产大模型                          |
| 工作流引擎 | LangGraph                                      |
| 多渠道 SDK | openclaw（微信/飞书消息通道）                   |

## 编码规范

- 严格遵循 **PEP 8**，使用 `ruff` 进行 lint 检查。
- 命名统一使用 **snake_case**（变量、函数、文件名）。
- 所有公开函数/类使用 **Google 风格 docstring**（Args/Returns/Raises）。
- **禁止裸 `print()`**——日志统一通过 `logging` 模块输出。

```python
# Good
logger = logging.getLogger(__name__)
logger.info("采集完成，共获取 %d 条数据", count)

# Bad
print(f"采集完成，共获取 {count} 条数据")
```

## 项目结构

```
.
├── AGENTS.md                    # 本文件
├── .opencode/
│   ├── agents/                  # Agent 定义
│   │   ├── collector.agent.md   # 采集 Agent
│   │   ├── analyzer.agent.md    # 分析 Agent
│   │   └── organizer.agent.md   # 整理分发 Agent
│   └── skills/                  # 可复用技能
│       ├── github-trending.skill.md
│       ├── hackernews.skill.md
│       └── wechat-push.skill.md
├── knowledge/
│   ├── raw/                     # 原始采集数据（保鲜层）
│   └── articles/                # 结构化分析后的文章 JSON
├── scripts/                     # 编排/调度脚本
│   ├── pipeline.py              # LangGraph 主流程
│   └── scheduler.py             # 定时任务
└── requirements.txt
```

## 知识条目 JSON 格式

每篇分析完成的知识条目存储为独立 JSON 文件，字段定义如下：

```json
{
  "id": "uuid-v4",
  "title": "文章或项目名称",
  "source": "github-trending | hackernews",
  "source_url": "https://原始链接",
  "author": "作者/组织名",
  "summary": "AI 生成的一句话摘要",
  "content": "AI 生成的结构化分析正文",
  "tags": ["分类标签1", "分类标签2"],
  "relevance_score": 0.92,
  "collected_at": "2026-07-16T10:30:00+08:00",
  "analyzed_at": "2026-07-16T10:35:00+08:00",
  "status": "draft | reviewed | published | skipped"
}
```

### 字段说明

| 字段            | 类型     | 说明                                       |
| --------------- | -------- | ------------------------------------------ |
| `id`            | string   | UUID v4 唯一标识                           |
| `title`         | string   | 文章/项目标题                               |
| `source`        | string   | 数据来源枚举值                              |
| `source_url`    | string   | 原始链接                                   |
| `author`        | string   | 作者或项目组织名                             |
| `summary`       | string   | 一句话摘要（≤120 字）                       |
| `content`       | string   | 结构化分析全文（Markdown）                   |
| `tags`          | string[] | 分类标签，如 `["llm", "agent", "rag"]`      |
| `relevance_score` | float  | 与 AI/LLM/Agent 领域的相关度评分（0-1）     |
| `collected_at`  | string   | 采集时间（ISO 8601 + 时区）                 |
| `analyzed_at`   | string   | 分析完成时间（ISO 8601 + 时区）             |
| `status`        | string   | 条目状态：草稿 → 已审核 → 已发布 → 已跳过   |

### 状态流转

```
draft ──(审校通过)──→ reviewed ──(推送完成)──→ published
  │                                              │
  └──(低相关/重复)──→ skipped                     │
```

## Agent 角色概览

| 角色     | Agent 文件                        | 职责                                                                 |
| -------- | --------------------------------- | -------------------------------------------------------------------- |
| 采集     | `.opencode/agents/collector.agent.md` | 定时抓取 GitHub Trending 和 Hacker News，过滤 AI/LLM/Agent 相关条目，存入 `knowledge/raw/` |
| 分析     | `.opencode/agents/analyzer.agent.md`  | 读取原始数据，调用大模型生成摘要/分析/打分/标签，输出结构化 JSON 到 `knowledge/articles/` |
| 整理分发 | `.opencode/agents/organizer.agent.md` | 筛选 `reviewed` 条目，通过 openclaw 推送到微信/飞书，更新 status 为 `published` |

### 调用链路

```
scheduler.py
  └── pipeline.py (LangGraph)
        ├── Node: collector  → 采集 raw JSON
        ├── Node: analyzer   → 生成 article JSON
        └── Node: organizer  → 多渠道分发
```

## 红线（绝对禁止）

1. **禁止提交 API Key、Token、Secret 到仓库。** 全部凭据通过环境变量注入。
2. **禁止直接调用外部 API 而不做错误处理和重试。** 所有 HTTP 请求必须有 timeout + retry 机制。
3. **禁止在 Agent 指令或 Prompt 中硬编码敏感信息。**
4. **禁止跳过 analyse 阶段直接发布。** 所有内容必须经过大模型分析并标记 `reviewed` 后方可分发。
5. **禁止在输出 JSON 中保留原始 HTML/CSS 残留。** 采集内容必须先清洗再入库。
6. **禁止依赖手动操作完成流水线。** 采集→分析→分发 全流程必须可无人值守自动运行。
7. **禁止修改 `knowledge/articles/` 下已标记为 `published` 的 JSON 文件。** 已发布条目不可篡改，如需修正应新增修订版本。
