# 数据库设计

Haven 使用 SQLite 作为长期记忆存储，数据库文件自动创建在 `.data/memory.db`，零运维开销。

## 概述

双层记忆架构：

```
短期记忆（deque, 100 条）── 内存中，当前对话上下文，进程重启后丢失
长期记忆（SQLite）       ── 跨会话持久化，自动提取用户事实
```

长期记忆负责两件事：
1. **对话归档** — 所有对话记录完整保存
2. **人物档案** — LLM 自动从对话中提取用户的个人信息（姓名、职业、偏好等），跨会话累积

## ER 图

```
┌──────────────┐       ┌──────────────────┐       ┌───────────────┐
│   entities   │       │   entity_facts   │       │ conversations │
├──────────────┤       ├──────────────────┤       ├───────────────┤
│ id        PK │──┐    │ id            PK │       │ id         PK │
│ name   UNIQUE│  └───>│ entity_id  FK ──┘       │ session_id    │
│ type         │        │ key               │       │ channel       │
│ created_at   │        │ value             │       │ role          │
│ updated_at   │        │ confidence        │       │ content       │
└──────────────┘        │ source            │       │ created_at    │
                        │ created_at        │       └───────────────┘
                        └──────────────────┘
```

## 表结构

### entities — 人物对象

记录对话中涉及的"人"（用户）。

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 主键 |
| `name` | TEXT | NOT NULL, UNIQUE | 人物名称（如 `"cli_user"`、`"张三"`） |
| `type` | TEXT | NOT NULL, DEFAULT `'person'` | 类型标签 |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间 |
| `updated_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 最后更新时间（有新事实写入时自动刷新） |

```sql
-- 实际数据示例
SELECT * FROM entities;

 id │   name    │  type  │     created_at      │     updated_at
────┼───────────┼────────┼─────────────────────┼─────────────────────
 1  │ cli_user  │ person │ 2026-05-20 22:00:00 │ 2026-05-21 00:30:00
 2  │ 张三      │ person │ 2026-05-21 08:15:00 │ 2026-05-21 09:00:00
```

### entity_facts — 人物属性

记录人物的结构化属性，每个 `(entity_id, key)` 唯一。同 key 再次写入时 **覆盖** value 和 confidence。

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 主键 |
| `entity_id` | INTEGER | NOT NULL, FK → entities(id) | 所属人物 |
| `key` | TEXT | NOT NULL | 属性名（英文 snake_case），如 `"job"`, `"health_condition"` |
| `value` | TEXT | NOT NULL | 属性值（保留原始语言），如 `"软件工程师"` |
| `confidence` | REAL | NOT NULL, DEFAULT 0.9 | 置信度 0.0~1.0 |
| `source` | TEXT | DEFAULT `''` | 来源标识（如 `"session:cli_main"`） |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间 |

约束：`UNIQUE(entity_id, key)` — 同一人物的同一属性只保留最新值。

**置信度语义：**

| 置信度 | 含义 | 示例 |
|--------|------|------|
| 0.9 | 用户明确陈述 | "我叫张三" → `name: 张三, 0.9` |
| 0.7 | 较确定推断 | "我在字节做了三年" → `company: 字节跳动, 0.7` |
| 0.5 | 暗示/模糊 | "最近有点头疼" → `health_condition: 头痛, 0.5` |
| 0.3 | 猜测 | 通常不提取 |

**注入 system prompt 时**，只取 `confidence >= memory.min_confidence`（默认 0.5）的事实。

```sql
-- 实际数据示例
SELECT e.name, f.key, f.value, f.confidence
FROM entity_facts f JOIN entities e ON f.entity_id = e.id
WHERE e.name = 'cli_user';

  name   │      key       │    value     │ confidence
─────────┼────────────────┼──────────────┼────────────
 cli_user│ name           │ 小明         │ 0.9
 cli_user│ job            │ 后端开发     │ 0.9
 cli_user│ preference     │ 喜欢简洁代码 │ 0.7
 cli_user│ health_condition│ 轻度颈椎病  │ 0.8
```

### conversations — 对话日志

完整记录所有对话，按 session 隔离。

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 主键 |
| `session_id` | TEXT | NOT NULL | 会话标识（`"cli_main"`, `"daemon"`, `"socket_192.168.1.1_54321"`） |
| `channel` | TEXT | NOT NULL, DEFAULT `'cli'` | 渠道（`cli` / `daemon` / `socket` / `email`） |
| `role` | TEXT | NOT NULL | 角色（`human` / `ai`） |
| `content` | TEXT | NOT NULL | 消息内容 |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间 |

```sql
-- 按 session 查看最近对话
SELECT role, substr(content, 1, 80) AS preview, created_at
FROM conversations
WHERE session_id = 'cli_main'
ORDER BY id DESC LIMIT 4;

 role  │                  preview                   │     created_at
───────┼───────────────────────────────────────────┼────────────────────
 ai    │ 您好，我是灯塔医疗助手健健，有什么可以帮您？│ 2026-05-21 10:05:00
 human │ 帮我写个快排                                │ 2026-05-21 10:04:55
 ai    │ 今天灯塔的补给很充足，大家情绪都不错。       │ 2026-05-21 09:30:00
 human │ 早上好                                      │ 2026-05-21 09:29:50
```

## 索引

| 索引名 | 列 | 用途 |
|--------|-----|------|
| `idx_conversations_session` | `(session_id, created_at)` | 按会话查询对话历史 |
| `idx_facts_entity` | `(entity_id)` | 按人物查询属性 |
| `idx_entities_name` | `(name)` | 按名称查找人物 |

## 数据流

```
用户输入 "我是张三，在字节做后端开发"
        │
        ▼
  ChatSession.process()
        │
        ├──→ agent.run()           # LLM 处理请求
        │
        └──→ agent.save_turn()     # 写入 conversations 表
                │
                ▼
          agent.extract_facts_async()   # 后台异步执行
                │
                ├── 取最近一轮对话 (human + ai)
                ├── LLM 提取结构化事实
                │     prompt: "从对话中提取用户的重要信息..."
                │     response: {"facts": [
                │       {"key": "name", "value": "张三", "confidence": 0.9},
                │       {"key": "job", "value": "后端开发", "confidence": 0.9},
                │       {"key": "company", "value": "字节跳动", "confidence": 0.7}
                │     ]}
                │
                ├── get_or_create_entity("张三")
                └── upsert_facts_batch(entity_id, facts)
                        │
                        ▼
                   entity_facts 表 (INSERT OR REPLACE)

下一轮对话:
  _build_system_prompt()
    └── memory.get_long_term_context("张三")
          └── format_facts_by_name("张三")
                │
                ▼
          "[长期记忆 — 以下是你已知的关于当前用户的信息]
           - name: 张三
           - job: 后端开发
           - company: 字节跳动"
```

## 维护

### 查看数据库

```bash
sqlite3 .data/memory.db

# 人物
SELECT * FROM entities;

# 某人的属性
SELECT key, value, confidence FROM entity_facts
WHERE entity_id = 1 ORDER BY created_at DESC;

# 最近对话
SELECT role, created_at, substr(content, 1, 100)
FROM conversations ORDER BY id DESC LIMIT 20;

# 统计
SELECT 'entities' AS tbl, COUNT(*) AS n FROM entities
UNION ALL SELECT 'facts', COUNT(*) FROM entity_facts
UNION ALL SELECT 'conversations', COUNT(*) FROM conversations;
```

### 清理

```bash
# 清除所有长期记忆（重置数据库）
rm .data/memory.db
# 下次启动自动重建
```

### 配置

在 `app.yaml` 中控制记忆行为：

```yaml
memory:
  enabled: true               # 是否启用长期记忆
  extract_after_turn: true    # 每轮对话后自动提取事实
  min_confidence: 0.5         # 注入 system prompt 的最低置信度
```
