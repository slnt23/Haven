# Memory 模块架构分析报告

> 分析日期: 2026-06-13
> 分析方式: 全量源码追踪
> 范围: `src/haven/memory/` + Runtime/Pipeline 集成点

---

## 第一部分：整体架构 —— 真实调用链

```
User Input
    │
    ▼
Runtime.execute() / execute_stream()
    │
    ▼
Executor.execute(request)
    │  session ← SessionManager.get_or_create()
    │
    ▼
Planner.plan(request)
    │  LangGraph StateGraph: classify → select_skills → build_plan → validate
    │
    ▼
Pipeline.run(plan, session) / run_stream(plan, session)
    │
    ├──► _build_sp(agent, skills, session)
    │      │
    │      ├── capability.get_skill(name)           # Skill prompt文本
    │      ├── _memory.recall_text(session.user_id) # ← 长期记忆注入
    │      │     └── FactStore.get_all_text(entity)  # SQLite SELECT
    │      │           └── 返回 "- 事实内容\n" 文本
    │      └── context_builder.build(
    │              skills, agent_prompt, task,
    │              history_summary="[长期记忆]\n{facts}",
    │              channel=session.channel
    │          )
    │          └── 组装 system_prompt
    │
    ├──► agent.run(task, system_prompt=sp, thread_id=session.id)
    │      └── LangChain create_agent (LLM + tools + checkpointer)
    │           └── LLM 接收 system_prompt (含记忆) + HumanMessage(task)
    │
    └──► _after_turn(session)  ← session_state.turn_count += 1
    │
    ▼
Runtime._trigger_memory(user_input, agent_response)
    │
    │  asyncio.create_task(...)   ← 后台异步，不阻塞主流程
    │
    ▼
MemoryManager.after_turn(user_input, agent_response, entity)
    │
    ├──► FactExtractor.extract(user_input, agent_response)
    │      └── aux_llm.ainvoke([HumanMessage(extraction_prompt)])
    │           └── LLM Structured Output → ExtractedFacts → list[dict]
    │              [{content: "用户有高血压", importance: 0.9}, ...]
    │
    └──► FactStore.add(entity, content, importance)
           └── SQLite: SELECT → UPDATE (if dup) / INSERT (if new)
```

---

## 第二部分：Memory 目录文件分析

### `memory/base.py`

| 维度 | 内容 |
|------|------|
| 职责 | 定义 `MemoryItem` 数据类 |
| 入口 | 无 |
| 被谁调用 | `fact_store.py` → `_row_to_item()`；`vector_memory.py` → `add(items)` |
| 调用谁 | 无 |
| 核心/辅助 | 辅助（纯数据类） |

### `memory/manager.py`

| 维度 | 内容 |
|------|------|
| 职责 | **Memory 模块唯一外部入口**。封装 FactStore + FactExtractor，提供 `remember/recall/forget/after_turn` |
| 入口函数 | `remember()`, `recall()`, `recall_text()`, `forget()`, `after_turn()` |
| 被谁调用 | `runtime/factory.py`（创建）；`execution/pipeline.py`（`recall_text`）；`Runtime._trigger_memory()`（`after_turn`） |
| 调用谁 | `FactStore.add/search/get_all/clear`；`FactExtractor.extract` |
| 核心/辅助 | **核心**——模块对外的唯一门面 |

### `memory/fact_store.py`

| 维度 | 内容 |
|------|------|
| 职责 | SQLite 语义事实 CRUD |
| 入口函数 | `add()`, `search()`, `get_all()`, `get_all_text()`, `delete()`, `clear()`, `expire()` |
| 被谁调用 | `MemoryManager`（全部包装调用） |
| 调用谁 | `memory.base.MemoryItem` |
| 核心/辅助 | **核心**——唯一的持久化存储 |

### `memory/extractor.py`

| 维度 | 内容 |
|------|------|
| 职责 | LLM 驱动的语义事实提取 |
| 入口函数 | `extract(user_input, agent_response) → list[dict]` |
| 被谁调用 | `MemoryManager.after_turn()` |
| 调用谁 | `aux_llm.ainvoke()`（辅助 LLM） |
| 核心/辅助 | **核心**——记忆的唯一写入来源 |

### `memory/conflict_resolver.py`

| 维度 | 内容 |
|------|------|
| 职责 | LLM 驱动的冲突检测与合并 |
| 入口函数 | `check(fact_a, fact_b)`, `resolve_batch(existing, new)` |
| 被谁调用 | **零调用**——代码完整但从未被集成到 MemoryManager 或任何流程中 |
| 调用谁 | 自身 `_llm.ainvoke()` |
| 核心/辅助 | **辅助（未集成）**——已实现但未接入主流程 |

### `memory/vector_memory.py`

| 维度 | 内容 |
|------|------|
| 职责 | ChromaDB 向量语义检索（可选） |
| 入口函数 | `add()`, `search()`, `clear()` |
| 被谁调用 | **零调用**——代码完整但从未被集成到 MemoryManager 或任何流程中 |
| 调用谁 | `chromadb`（若已安装）；`memory.base.MemoryItem` |
| 核心/辅助 | **辅助（未集成）**——已实现但未接入 |

---

## 第三部分：Runtime 如何调用 Memory

### 创建阶段（`create_runtime`）

```
create_runtime()
    │
    ├── cfg = load_config()
    │
    ├── if cfg.memory.enabled:
    │     ├── fact_store = FactStore(db_path)          # SQLite 连接
    │     ├── aux_llm = model_factory.create(aux_model)._raw  # 辅助 LLM
    │     ├── extractor = FactExtractor(aux_llm)       # 事实提取器
    │     └── memory_manager = MemoryManager(
    │             fact_store, extractor=extractor, entity_name=entity_name
    │         )
    │
    └── Runtime(..., memory_manager=memory_manager)
```

### 执行阶段

```
每次对话（execute / execute_stream）完成后:

Runtime.execute(task)
    │
    ├── response = executor.execute(request)
    │     └── Planner → Pipeline → Agent → LLM → 回复文本
    │
    └── _trigger_memory(user_input, response_text)
          │
          └── asyncio.create_task(
                memory_manager.after_turn(user_input, response)
              )
```

`_trigger_memory` 在 `execute()` 和 `execute_stream()` 中都调用，**在 LLM 回复生成之后**。

---

## 第四部分：after_turn 流程

```
Assistant 回复完成
    │
    ▼
Runtime._trigger_memory(user_input, response_text)
    │
    │  asyncio.create_task(...)  ← 后台任务，不阻塞主流程
    │
    ▼
MemoryManager.after_turn(user_input, agent_response, entity="user")
    │
    ├── [步骤 1] FactExtractor.extract(user_input, agent_response)
    │     输入: user_input (str), agent_response (str)
    │     输出: list[dict] → [{"content": "用户有高血压", "importance": 0.9}, ...]
    │     异常: 捕获所有异常 → 记录 WARNING → 返回 []
    │           LLM 调用失败 → 返回 []
    │
    ├── [步骤 2] 遍历提取到的 facts
    │      for each fact:
    │          FactStore.add(entity, content, importance)
    │             ├── SELECT 检查 (entity, content) 是否已存在
    │             ├── 已存在 → UPDATE importance, source
    │             └── 不存在 → INSERT 新行
    │             异常: 捕获 → WARNING → 跳过单条，继续下一条
    │
    └── 返回写入数量 (int)
```

### 关键细节

| 步骤 | 调用 | 同步/异步 | 容错 |
|------|------|-----------|------|
| 触发 | `asyncio.create_task()` | 异步（后台） | 静默失败（不阻塞用户） |
| 提取 | `FactExtractor.extract()` | 异步（LLM 调用） | 失败返回 [] |
| 写入 | `FactStore.add()` | 同步（SQLite 写入） | 逐条 try/except |
| 去重 | `SELECT WHERE entity+content` | 精确匹配 | 否（语义相似=两条） |

### 注意

- **ConflictResolver 未集成** — `after_turn` 中不包含冲突检测，新增事实直接写入
- **VectorMemory 未集成** — 写入不进入向量库
- **同步 SQLite** — `FactStore.add()` 是同步的，在 `asyncio.create_task` 的后台协程中执行

---

## 第五部分：Recall 流程

### `remember()` — 程序化手动写入

```
MemoryManager.remember(content, entity, importance, source)
    │
    └── FactStore.add(entity, content, importance, source)
         ├── SELECT 去重 → UPDATE（已存在）/ INSERT（新增）
         └── 返回 id
```

**调用者**：非 CLI 接口（API/脚本手动写入）

### `recall()` — 关键词检索

```
MemoryManager.recall(query, entity, limit)
    │
    └── FactStore.search(query, entity, limit)
         ├── WHERE entity_name = ? AND content LIKE ? (关键词 LIKE 匹配)
         ├── ORDER BY importance DESC, created_at DESC
         └── 返回 list[MemoryItem]
```

**调用者**：当前代码中无活跃调用。API/HPPT 接口未使用。

### `recall_text()` — 注入 ContextBuilder

```
MemoryManager.recall_text(entity)
    │
    └── FactStore.get_all_text(entity)
         ├── SELECT content FROM facts WHERE entity_name = ?
         ├── ORDER BY importance DESC, created_at DESC
         └── 返回 "- fact1\n- fact2\n- fact3" 文本
```

**调用者**：`Pipeline._build_sp()` — 每次 Agent 执行前调用。

### `forget()` — 清空记忆

```
MemoryManager.forget(entity)
    │
    └── FactStore.clear(entity)
         └── DELETE FROM facts WHERE entity_name = ?
```

**调用者**：CLI `/memory-clear` 命令。

---

## 第六部分：FactExtractor 分析

| 维度 | 说明 |
|------|------|
| 是否调用 LLM | **是**——使用辅助 LLM（默认 `deepseek-v4-flash`） |
| Prompt | 中文指令：提取关于用户的独立事实句子，按重要性评分 0.3-0.9 |
| 输出格式 | Pydantic `ExtractedFacts` → `list[dict]` `[{"content": "...", "importance": 0.8}]` |
| 失败处理 | 捕获异常 → WARNING 日志 → 返回空 `[]` |
| 缓存 | **否**——每次调用都请求 LLM |
| 同步/异步 | **异步**——`async def extract()` |
| DeepSeek 特殊处理 | 禁用 thinking 模式（`extra_body.thinking.disabled`），避免与 structured output 冲突 |

---

## 第七部分：FactStore 分析

### 数据库结构

```sql
CREATE TABLE facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_name TEXT NOT NULL,
    content     TEXT NOT NULL,       -- 自然语言事实句子
    importance  REAL NOT NULL DEFAULT 0.5,
    source      TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_facts_entity ON facts(entity_name);
```

### CRUD 策略

| 操作 | 方法 | SQL |
|------|------|-----|
| 新增 | `add()` | `INSERT INTO facts (...) VALUES (...)` |
| 更新 | `add()` 内部 | `SELECT` → 存在则 `UPDATE importance` |
| 删除 | `delete(id)` | `DELETE WHERE id = ?` |
| 清空 | `clear(entity)` | `DELETE WHERE entity_name = ?` 或 `DELETE FROM facts` |
| 过期 | `expire(days)` | `DELETE WHERE created_at < datetime('now', '-N days')` |

### 去重策略

- **精确匹配去重**：`(entity_name, content)` 二元组精确相等 → UPDATE 而非 INSERT
- **无语义去重**：`"用户叫阿林"` 和 `"用户名叫阿林"` → 两条独立记录（代码 TODO 注释注明了此问题）
- **无 embedding 去重**：不依赖向量相似度

---

## 第八部分：ConflictResolver 分析

### 设计意图

检测两条记忆事实是否矛盾，若矛盾则通过 LLM 给出合并后的正确版本。

### 实际状态

**未集成。** 代码完整但：

- `MemoryManager` 不持有 `ConflictResolver` 实例
- `after_turn()` 不调用 `ConflictResolver`
- `FactStore.add()` 内部不使用冲突检测
- 零外部调用者

### 如果被集成，预期行为

```
新事实 "用户讨厌Python"
    │
    ▼
ConflictResolver.resolve_batch(existing_facts, new_fact)
    │
    ├── for each existing:
    │     └── check(existing, new) → LLM 判断是否矛盾
    │           ├── 不矛盾 → 保留旧事实
    │           └── 矛盾 → 用 LLM 给出的 resolution 替换
    │
    └── 返回处理后的 facts 列表
```

### 为什么未集成

`ConflictResolver` 需要 LLM 调用，而 `after_turn` 已经在后台使用 LLM 提取事实。如果再对每条新事实与所有旧事实逐一对比，会显著增加 token 消耗和延迟。设计上可能是为后续"批量离线冲突检测"准备的。

---

## 第九部分：VectorMemory 分析

### 作用

ChromaDB 向量语义检索——用 embedding 相似度替代 SQLite 的 LIKE 关键词匹配。

### 实际状态

**未集成。** 代码完整但：

- `MemoryManager` 不持有 `VectorMemory` 实例
- `recall()` 不调用 `VectorMemory.search()`
- `after_turn()` 不调用 `VectorMemory.add()`
- 零外部调用者

### 如果被集成，预期行为

```
recall() → FactStore.search() + VectorMemory.search() → 合并 → 重排序 → 返回
```

### ChromaDB 依赖

- `chromadb` 未在 `pyproject.toml` 中声明
- 默认未安装 → `VectorMemory.__init__` 捕获 `ImportError` → `_enabled = False`
- 当前环境中 ChromaDB 未安装 → 永久禁用状态

---

## 第十部分：ContextBuilder 中 Memory 的注入位置

### 注入链路

```
Pipeline._build_sp(agent, skills, session)
    │
    ├── memory.recall_text(session.user_id)           # ← Memory 读入口
    │     └── "- 用户有高血压\n- 用户是后端工程师\n..."
    │
    └── context_builder.build(
            agent_prompt=agent.agent_prompt,
            skills=skills,
            task=task,
            history_summary="[长期记忆]\n- 用户有高血压\n...",
            channel=session.channel,
        )
```

### system_prompt 中的位置

```
[Personality: haven.md 人格]
    ↓
[Agent prompt: "你是专业诊断助手..."]
    ↓
[Skills prompt: medical_triage skill 的 prompt]
    ↓
[Project files: 可选文件列表]
    ↓
[History summary: [长期记忆]\n- 用户有高血压\n- 用户住北京]
    ↓
[Channel hint: CLI 输出环境提示]
```

Memory 作为 **System Prompt 的第 5 层**（在人格/Agent/Skills/Files 之后），作为 `history_summary` 参数传入 `ContextBuilder.build()`。

---

## 第十一部分：短期记忆 vs 长期记忆

| 记忆类型 | 实现 | 存储 | 生命周期 | 归属 |
|---------|------|------|---------|------|
| **对话历史** | LangGraph `SqliteSaver` | `resource/checkpoint.db` | Session 内（thread_id 隔离） | 短期记忆 |
| **语义事实** | `FactStore` | `resource/memory.db` | 跨 Session 持久（90 天过期） | 长期记忆 |
| **向量检索** | `VectorMemory` | `resource/chroma/` | 跨 Session 持久 | 长期记忆（未启用） |
| **冲突检测** | `ConflictResolver` | 无持久化 | 无状态 | 工具 |

### 生命周期对比

```
短期记忆：
  创建 → Session 创建时分配 thread_id
  读写 → 每次 Agent 调用自动持久化
  清理 → /clear 命令 → checkpointer.adelete_thread()

长期记忆：
  创建 → after_turn() 从对话提取事实
  读写 → recall_text() 注入 Context
  清理 → /memory-clear → FactStore.clear()
  过期 → expire(90 days) 自动清理
```

---

## 第十二部分：完整数据流

```
┌─────────────────────────────────────────────────────────────────────┐
│                          一次完整对话                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  User: "我最近胸口疼，我有高血压"                                     │
│      │                                                              │
│      ▼                                                              │
│  Runtime.execute(task)                                               │
│      │                                                              │
│      ▼                                                              │
│  Executor → Planner → plan: {agent_type=diagnosis, skills=[medical]} │
│      │                                                              │
│      ▼                                                              │
│  Pipeline._build_sp()                                                │
│      │                                                              │
│      ├──→ memory.recall_text("user")  ← 读取长期记忆                  │
│      │      └── FactStore.get_all_text("user")                       │
│      │           └── "- 用户有高血压"                                 │
│      │                                                              │
│      └──→ context_builder.build(history_summary="[长期记忆]\n...")   │
│           └── system_prompt = "人格 + Agent + Skills + [长期记忆]"    │
│      │                                                              │
│      ▼                                                              │
│  Agent.run(task, system_prompt, thread_id)                           │
│      │                                                              │
│      │  LLM 收到:                                                    │
│      │    System: "人格...你是诊断助手...[长期记忆]\n- 用户有高血压"    │
│      │    Human:  "我最近胸口疼，我有高血压"                          │
│      │                                                              │
│      ▼                                                              │
│  LLM 回复: "结合您的高血压病史和胸痛症状，建议..."                     │
│      │                                                              │
│      ▼                                                              │
│  Runtime._trigger_memory("我最近胸口疼", LLM回复)                      │
│      │                                                              │
│      │  asyncio.create_task(...)  ← 后台异步                          │
│      │                                                              │
│      ▼                                                              │
│  MemoryManager.after_turn(user_input, response)                      │
│      │                                                              │
│      ├──→ FactExtractor.extract(...) → aux_LLM                      │
│      │      └── [{content: "用户有胸痛症状", importance: 0.7}]       │
│      │                                                              │
│      └──→ FactStore.add("user", "用户有胸痛症状", 0.7)               │
│           └── INSERT INTO facts                                      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 第十三部分：存在的问题

| # | 问题 | 详情 | 严重程度 |
|---|------|------|---------|
| 1 | **ConflictResolver 未集成** | 完整实现但从未调用。冲突检测形同虚设。 | 中 |
| 2 | **VectorMemory 未集成** | 完整实现但从未调用。没有 embedding，所有检索依赖 SQLite LIKE。 | 中 |
| 3 | **语义去重缺失** | `"用户叫阿林"` vs `"用户名叫阿林"` → 两条独立记录。仅靠精确字符串匹配。 | 中 |
| 4 | **同步 SQLite** | `FactStore.add()` 是同步调用。在 `asyncio.create_task` 后台执行，不阻塞主流程，但内部使用同步 `sqlite3`。 | 低 |
| 5 | **after_turn 无冲突检测** | 新事实直接写入，不检查是否与已有事实矛盾。用户可能先后说 "喜欢 Python" 和 "讨厌 Python"，两条都保留。 | 中 |
| 6 | **单实体假设** | `MemoryManager` 创建时固定 `entity_name`，多用户场景需要外部管理 entity 参数（已支持但需显式传递）。 | 低 |
| 7 | **无 Embedding 模型** | `VectorMemory` 需要 ChromaDB + embedding 模型，但未引入 `langchain.embeddings`，也未在 `pyproject.toml` 声明 `chromadb` 依赖。 | 高 |
| 8 | **Memory 过期机制未被调用** | `FactStore.expire()` 方法存在但无调用者，旧记忆不会自动清理。 | 低 |
| 9 | **无 Context 裁剪** | `recall_text()` 返回全部事实，不按 token 预算裁剪。如果用户有 100 条事实，全部注入 prompt 可能超限。 | 低 |
| 10 | **MemoryManager 与 ContextBuilder 间接耦合** | `Pipeline._build_sp()` 调用 `memory.recall_text()` 获取文本，再传给 `context_builder.build()`。MemoryManager 不直接被 ContextBuilder 持有，而是通过 Pipeline 中转。 | 低 |

---

## 第十四部分：总结

```
Memory 核心入口:       MemoryManager
Memory 核心类:         MemoryManager, FactStore, FactExtractor
真正写入位置:         FactStore.add() (via MemoryManager.after_turn)
真正读取位置:         FactStore.get_all_text() (via MemoryManager.recall_text → Pipeline._build_sp)
真正更新位置:         FactStore.add() → SELECT + UPDATE (去重时)
真正删除位置:         FactStore.clear() (via MemoryManager.forget → CLI /memory-clear)
数据库:              SQLite → resource/memory.db (WAL 模式)
向量库:              ChromaDB → resource/chroma/ (未集成，依赖未安装)
LLM 参与环节:         FactExtractor.extract() (aux_llm), ConflictResolver.check() (未调用)
Runtime 调用链:       Runtime._trigger_memory → MemoryManager.after_turn → FactExtractor.extract + FactStore.add
Context 构建链:       Pipeline._build_sp → MemoryManager.recall_text → FactStore.get_all_text → ContextBuilder.build(history_summary)
建议后续重构方向:
  1. 将 ConflictResolver 集成到 MemoryManager.after_turn() 中
  2. 将 VectorMemory 接入 recall() 流程（需要 embedding 模型 + chromadb 依赖）
  3. 语义去重：引入 embedding 相似度比较
  4. recall_text() 添加 token 预算裁剪
  5. 将 VectorMemory 所需依赖加入 pyproject.toml
```
