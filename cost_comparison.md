# 模型成本对比

## 测试条件

| 项目 | 值 |
|------|-----|
| 测试日期 | YYYY-MM-DD |
| 任务类型 | AI 知识库分析（摘要/评分/标签/正文生成） |
| 输入数据量 | N 条文章/仓库条目 |
| 平均输入长度 | ~XXX tokens/条 |
| 输出长度要求 | max_tokens=2048, temperature=0.3 |

## DeepSeek Chat

| 指标 | 值 |
|------|-----|
| 模型 | deepseek-chat |
| 调用次数 | — |
| Prompt tokens | — |
| Completion tokens | — |
| Total tokens | — |
| 单价（输入/输出） | ¥1 / ¥2 每百万 tokens |
| **估算成本** | **¥—** |

## Qwen Plus

| 指标 | 值 |
|------|-----|
| 模型 | qwen-plus |
| 调用次数 | — |
| Prompt tokens | — |
| Completion tokens | — |
| Total tokens | — |
| 单价（输入/输出） | ¥4 / ¥12 每百万 tokens |
| **估算成本** | **¥—** |

## 结论

| 维度 | DeepSeek Chat | Qwen Plus | 胜出 |
|------|:------------:|:---------:|:----:|
| 单价（元/百万输入） | 1 | 4 | DeepSeek |
| 单价（元/百万输出） | 2 | 12 | DeepSeek |
| 每次调用平均耗时 | — | — | — |
| 摘要质量 | — | — | — |
| 标签准确度 | — | — | — |
| **性价比** | — | — | **—** |

> 切换模型方式：`export LLM_PROVIDER=deepseek` 或 `export LLM_PROVIDER=qwen`
