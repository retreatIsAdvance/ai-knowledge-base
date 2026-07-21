# WeChat Push Skill

## 功能

通过 openclaw SDK 向微信订阅用户推送 AI 知识条目。

## 前提

- openclaw SDK 已正确安装和配置
- 微信企业应用凭据已通过环境变量注入
  - `WECOM_CORP_ID`
  - `WECOM_AGENT_ID`
  - `WECOM_APP_SECRET`

## 推送流程

1. 获取 `knowledge/articles/` 中 `status = "reviewed"` 的条目
2. 按 `relevance_score` 降序排列
3. 格式化消息（Markdown 格式）
4. 调用 openclaw 发送
5. 推送成功后将条目 `status` 更新为 `published`

## 消息模板

```markdown
## {title}
> {summary}

**相关度**：{relevance_score}  |  **标签**：{tags}
🔗 [查看原文]({source_url})

---
*AI 知识库 · 自动推送*
```

## 错误处理

- 发送失败：重试 3 次，间隔 5 秒
- 凭据过期：记录 ERROR 日志，发送告警
- 单日配额用尽：记录 WARNING，剩余条目顺延至次日
