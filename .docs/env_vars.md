# 环境变量说明

## 必填

模型 API Key，至少配一个：

| 变量 | 对应模型 | 说明 |
|------|----------|------|
| `OWL_DEEPSEEK_API_KEY` | deepseek-v4-pro / deepseek-v4-flash | DeepSeek 系列 |
| `OPENAI_API_KEY` | gpt-4o / gpt-4o-mini | OpenAI 系列 |
| `DASHSCOPE_API_KEY` | qwen-max / qwen-plus | 通义千问系列 |

模型定义见 `models.yaml`，新增模型需声明 `api_key_env` 字段。

---

## 可选

### Agent

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AGENT_MAX_ITERATIONS` | 20 | 工具调用最大轮次 |
| `AGENT_MAX_EXECUTION_TIME` | 300 | 最大执行时间（秒） |

### 网页搜索

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WEB_SEARCH_API_KEY` | — | 搜索引擎 API Key |
| `WEB_SEARCH_ENGINE` | bing | 搜索引擎 |

### 邮件通道

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EMAIL_SMTP_HOST` | smtp.qq.com | SMTP 服务器 |
| `EMAIL_SMTP_PORT` | 587 | SMTP 端口 |
| `EMAIL_SMTP_USERNAME` | — | 发件邮箱 |
| `EMAIL_SMTP_PASSWORD` | — | SMTP 授权码 |
| `EMAIL_USE_TLS` | true | 启用 TLS |
| `EMAIL_IMAP_HOST` | imap.qq.com | IMAP 服务器 |
| `EMAIL_IMAP_PORT` | 993 | IMAP 端口 |
| `EMAIL_IMAP_USERNAME` | — | 收件邮箱 |
| `EMAIL_IMAP_PASSWORD` | — | IMAP 密码 |
| `EMAIL_POLL_INTERVAL` | 60 | 轮询间隔（秒） |
| `EMAIL_USER_WHITELIST` | — | 用户白名单（逗号分隔） |
| `EMAIL_DIGEST_TIME` | 08:00 | 每日摘要时间 |

### 守护进程通道

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DAEMON_SOCKET_ENABLED` | false | 启用 TCP 通道 |
| `DAEMON_SOCKET_HOST` | 127.0.0.1 | TCP 监听地址 |
| `DAEMON_SOCKET_PORT` | 9020 | TCP 监听端口 |
| `DAEMON_EMAIL_ENABLED` | false | 启用邮件通道 |
| `DAEMON_FEISHU_ENABLED` | false | 启用飞书通道 |
| `DAEMON_FEISHU_APP_ID` | — | 飞书应用 App ID |
| `DAEMON_FEISHU_APP_SECRET` | — | 飞书应用 App Secret |

### RAG

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `RAG_EMBEDDING_MODEL` | text-embedding-3-small | Embedding 模型 |
| `RAG_EMBEDDING_API_BASE` | https://api.openai.com/v1 | Embedding API 地址 |
| `RAG_CHUNK_SIZE` | 1000 | 文本分块大小 |
| `RAG_CHUNK_OVERLAP` | 200 | 分块重叠长度 |
| `RAG_TOP_K` | 5 | 检索返回条数 |

### 记忆

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MEMORY_ENABLED` | true | 启用长期记忆 |
| `MEMORY_EXTRACT_AFTER_TURN` | true | 每轮对话后自动提取事实 |
| `MEMORY_MIN_CONFIDENCE` | 0.5 | 注入上下文的最低置信度 |

### 其他

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MCP_ENABLED` | true | 启用 MCP 工具集成 |
| `SKILL_DIRECTORY` | skills | Skill 文件目录 |
| `HAVEN_CONFIG_DIR` | — | 用户配置文件目录（替代 CWD） |

---

## 使用方式

**Linux / Mac：**
```bash
export OWL_DEEPSEEK_API_KEY=sk-xxxxx
haven
```

**Windows (PowerShell)：**
```powershell
$env:OWL_DEEPSEEK_API_KEY="sk-xxxxx"
haven
```

**Windows (CMD)：**
```cmd
set OWL_DEEPSEEK_API_KEY=sk-xxxxx
haven
```
