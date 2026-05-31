# 数据库设计

Haven V2 使用 SQLite 作为主要持久化存储，数据库文件自动创建在 `.data/memory.db`，零运维开销。

## 概述

V2 四层记忆架构对应以下存储：

```
Working Memory  —— 内存 deque（不持久化）
Episodic Memory —— SQLite episodes 表
Semantic Memory —— SQLite memory_entities / memory_facts / memory_fact_history 表
Vector Memory   —— ChromaDB（.data/chroma/）
Workflow        —— SQLite workflow_checkpoints 表
```

## ER 图

```
┌──────────────────┐       ┌─────────────────────┐
│  memory_entities │       │   memory_facts      │
├──────────────────┤       ├─────────────────────┤
│ id            PK │──┐    │ id               PK │
│ name      UNIQUE │  └───>│ entity_id     FK ──┘
│ type             │        │ key                 │
│ description      │        │ value               │
│ created_at       │        │ confidence          │
│ updated_at       │        │ source_session      │
└──────────────────┘        │ source_turn         │
                            │ related_fact_ids    │
┌──────────────────────┐    │ tags                │
│ memory_fact_history  │    │ created_at          │
├──────────────────────┤    └─────────────────────┘
│ id               PK  │
│ fact_id       FK ────┘    ┌─────────────────────┐
│ old_value             │    │     episodes        │
│ new_value             │    ├─────────────────────┤
│ changed_at            │    │ id              PK  │
└───────────────────────┘    │ session_id          │
                             │ turn_number         │
┌──────────────────────────┐ │ user_message        │
│     conversations        │ │ assistant_response  │
│     （V1 保留兼容）       │ │ summary             │
├──────────────────────────┤ │ importance          │
│ id                   PK  │ │ metadata_json       │
│ session_id               │ │ created_at          │
│ channel                  │ └─────────────────────┘
│ role                     │
│ content                  │ ┌───────────────────────────┐
│ created_at               │ │  workflow_checkpoints     │
└──────────────────────────┘ ├───────────────────────────┤
                             │ id                    PK  │
┌──────────────────┐        │ session_id                │
│    entities      │        │ node_name                 │
│   （V1 保留兼容） │        │ state_json                │
├──────────────────┤        │ created_at                │
│ id            PK │        └───────────────────────────┘
│ name      UNIQUE │
│ type             │
│ created_at       │
│ updated_at       │
└──────────────────┘

┌──────────────────┐
│  entity_facts    │
│ （V1 保留兼容）   │
├──────────────────┤
│ id            PK │
│ entity_id  FK ───┘
│ key              │
│ value            │
│ confidence       │
│ source           │
│ created_at       │
└──────────────────┘
```

## V2 新表结构

### episodes — 对话记录（Episodic Memory）

完整保留每轮对话，支持摘要压缩和重要性评分。

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | TEXT | PK | 唯一标识，格式 `ep_{session}_{turn}_{uuid}` |
| `session_id` | TEXT | NOT NULL | 会话标识 |
| `turn_number` | INTEGER | NOT NULL | 轮次序号 |
| `user_message` | TEXT | NOT NULL | 用户消息原文 |
| `assistant_response` | TEXT | NOT NULL | AI 回复原文 |
| `summary` | TEXT | DEFAULT '' | LLM 生成的对话摘要（consolidation 阶段填充） |
| `importance` | REAL | DEFAULT 0.5 | 重要性评分 0-1 |
| `metadata_json` | TEXT | DEFAULT '{}' | 扩展元数据 JSON |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间 |

### memory_entities — 实体（Semantic Memory）

记录对话中涉及的对象（用户、项目等）。

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 主键 |
| `name` | TEXT | NOT NULL, UNIQUE | 实体名称 |
| `type` | TEXT | NOT NULL, DEFAULT 'user' | 类型（user / project / topic） |
| `description` | TEXT | DEFAULT '' | 实体描述 |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间 |
| `updated_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 最后更新时间 |

### memory_facts — 结构化事实（Semantic Memory）

记录实体的结构化属性，支持变更历史和置信度衰减。

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 主键 |
| `entity_id` | INTEGER | NOT NULL, FK → memory_entities(id) | 所属实体 |
| `key` | TEXT | NOT NULL | 属性名（英文 snake_case） |
| `value` | TEXT | NOT NULL | 属性值（保留原始语言） |
| `confidence` | REAL | NOT NULL, DEFAULT 0.9 | 置信度 0.0-1.0 |
| `source_session` | TEXT | DEFAULT '' | 来源会话标识 |
| `source_turn` | INTEGER | DEFAULT 0 | 来源轮次 |
| `related_fact_ids` | TEXT | DEFAULT '[]' | 关联事实 ID（JSON 数组） |
| `tags` | TEXT | DEFAULT '[]' | 分类标签（JSON 数组） |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建/更新 时间 |

约束：`UNIQUE(entity_id, key)` — 同一实体的同一属性只保留最新值。

### memory_fact_history — 事实变更历史（Semantic Memory）

同 key 被覆盖时自动存档旧值，支持属性时间线追踪。

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 主键 |
| `fact_id` | INTEGER | NOT NULL, FK → memory_facts(id) | 被变更的事实 |
| `old_value` | TEXT | NOT NULL | 旧值 |
| `new_value` | TEXT | NOT NULL | 新值 |
| `changed_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 变更时间 |

### workflow_checkpoints — 工作流状态快照

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | INTEGER | PK, AUTOINCREMENT | 主键 |
| `session_id` | TEXT | NOT NULL | 工作流会话标识 |
| `node_name` | TEXT | NOT NULL | 当前节点名 |
| `state_json` | TEXT | NOT NULL | 完整状态 JSON |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 快照时间 |

约束：`UNIQUE(session_id, node_name)` — 同 session 同节点只保留最新快照。

## V1 保留表

以下表从 V1 继承，保持向后兼容。新代码优先使用 V2 表。

### entities / entity_facts（V1 Semantic）

V1 的人物实体和属性存储。V2 使用 `memory_entities` + `memory_facts` + `memory_fact_history`。

### conversations（V1 Episodic）

V1 的对话日志。V2 使用 `episodes` 表（含 summary / importance / metadata 字段）。

## 索引

| 索引名 | 列 | 用途 |
|--------|-----|------|
| `idx_episodes_session` | `(session_id, turn_number)` | 按会话查询对话历史 |
| `idx_episodes_created` | `(created_at DESC)` | 时间排序检索 |
| `idx_memory_facts_entity` | `(entity_id)` | 按实体查询事实 |
| `idx_memory_facts_confidence` | `(confidence)` | 按置信度过滤 |
| `idx_memory_entities_name` | `(name)` | 按名称查找实体 |
| `idx_mf_entity` | `(entity_id)` | V1 facts 索引 |
| `idx_mf_confidence` | `(confidence)` | V1 facts 置信度索引 |
| `idx_checkpoint_session` | `(session_id, created_at DESC)` | 按会话查询 checkpoint |
| `idx_conversations_session` | `(session_id, created_at)` | V1 对话索引 |

## 数据流

```
User: "我是张三，在字节做后端开发"
  │
  ├─ MemoryManager.record_turn(user_msg, assistant_msg)
  │     │
  │     ├─ WorkingMemory.add_message()          # 内存追加
  │     ├─ EpisodicMemory.store_turn()          # SQLite episodes 写入
  │     ├─ VectorMemory.store()                 # ChromaDB embed
  │     └─ asyncio.create_task(extract_facts)   # 异步提取
  │           │
  │           ├─ LLM 提取结构化事实
  │           │     prompt: "从对话中提取关于'张三'的信息..."
  │           │     → {"facts": [
  │           │         {"key":"name","value":"张三","confidence":0.9},
  │           │         {"key":"job","value":"后端开发","confidence":0.9},
  │           │         {"key":"company","value":"字节跳动","confidence":0.7}
  │           │       ]}
  │           │
  │           ├─ SemanticMemory.store(items)
  │           │     ├─ get_or_create_entity("张三", "user")
  │           │     ├─ 如有旧值不同 → record_history() 存档
  │           │     └─ upsert_fact() 写入 memory_facts
  │           │
  │           └─ 10轮对话后 → MemoryManager.consolidate()
  │                 ├─ Episodic: 旧 episode LLM 摘要压缩
  │                 ├─ Semantic: 低置信度事实衰减 (confidence -= 0.1)
  │                 └─ Vector: 超过 10000 条时清理旧条目

下一轮对话:
  MemoryManager.retrieve(task)
    ├─ Working: 最近 20 条消息
    ├─ Semantic: memory_facts WHERE entity_name='张三' AND confidence>=0.3
    ├─ Episodic: episodes WHERE (content LIKE '%关键词%') ORDER BY importance*时间衰减
    └─ Vector: ChromaDB.query(task_embedding, top_k=5)
          │
          ▼
    MemoryContext → format_for_prompt()
      → "[长期记忆] name: 张三 / job: 后端开发
         [相关历史] [05-28] 用户: 我用Python做后端..."
```

## 维护

### 查看数据库

```bash
sqlite3 .data/memory.db

# Episodic: 最近对话
SELECT session_id, turn_number, substr(user_message,1,60), importance
FROM episodes ORDER BY created_at DESC LIMIT 10;

# Semantic: 用户事实
SELECT e.name, f.key, f.value, f.confidence, f.created_at
FROM memory_facts f JOIN memory_entities e ON f.entity_id = e.id
ORDER BY e.name, f.confidence DESC;

# Fact 变更历史
SELECT e.name, f.key, h.old_value, h.new_value, h.changed_at
FROM memory_fact_history h
JOIN memory_facts f ON h.fact_id = f.id
JOIN memory_entities e ON f.entity_id = e.id;

# Workflow Checkpoints
SELECT session_id, node_name, created_at
FROM workflow_checkpoints ORDER BY created_at DESC;
```

### 清理

```bash
# 清除所有记忆数据
rm .data/memory.db
# 下次启动自动重建

# 清除向量数据
rm -rf .data/chroma/
```
