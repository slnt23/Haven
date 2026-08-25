# Memory 架构设计文档（V2 Final）

> 基于真实代码分析。状态: 2026-06-13。
> 不包含未集成的组件（VectorMemory 旧版、ConflictResolver）。

---

## 第一部分：整体架构

```
                         Runtime._trigger_memory()
                              │
                              │ asyncio.create_task()  ← 后台异步
                              ▼
                      MemoryManager
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
        remember()    retrieve()    after_turn()
              │             │             │
              │        ┌────┴────┐   ┌────┴────┐
              │        │         │   │         │
              ▼        ▼         ▼   ▼         ▼
         FactStore  VectorStore FactStore FactExtractor VectorStore
         (SQLite)   (Chroma)    (SQLite)  (LLM)    (Chroma)
              │        │                        │
              └────────┼────────────────────────┘
                       │
                       ▼
                 ContextBuilder.format_memory()
                       │
                       ▼
                   system_prompt
                       │
                       ▼
                      LLM
```

**真实入口：** `MemoryManager` 是唯一的对外接口。

---

## 第二部分：完整数据流（一次对话）

```
User: "我最近胸口疼，我有高血压"
    │
    ▼
Runtime.execute(task)
    │
    ▼
Executor → Planner → Pipeline.run()
    │
    │  [READ] Pipeline._build_sp()
    │         ├── memory.retrieve(entity="user")       ← 检索入口
    │         │     ├── MemoryVectorStore.search()      ← 语义检索（可选）
    │         │     │     └── Chroma.similarity_search()
    │         │     └── FactStore.search()               ← SQLite LIKE
    │         │
    │         └── context_builder.build(memory_items=items)
    │               ├── _sort_memory(items)              ← importance DESC
    │               ├── _trim_memory(sorted, budget)     ← 800 token 裁剪
    │               └── format_memory(trimmed)           ← "[长期记忆]\n- ..."
    │
    ▼
Agent.run(task, system_prompt) → LLM
    │
    ▼
LLM 回复: "结合您的高血压病史，建议..."
    │
    ▼
Runtime._trigger_memory(user_input, response)
    │
    │  asyncio.create_task(...)  ← 不阻塞用户
    │
    │  [WRITE] MemoryManager.after_turn(user_input, response)
    │         ├── FactExtractor.extract(user_input, response)  ← aux_llm
    │         │     └── LLM Structured Output → [{content, importance}, ...]
    │         │
    │         └── for each fact:
    │               _dedup_and_store(entity, content, importance)
    │                 ├── MemoryVectorStore.search_similar()    ← 语义去重
    │                 │     └── Chroma.similarity_search_with_score()
    │                 │
    │                 ├── score ≥ threshold (0.90)?
    │                 │     YES → FactStore.add(existing_content) → UPDATE
    │                 │     NO  → FactStore.add(new_content)    → INSERT
    │                 │           + MemoryVectorStore.add(item) → Chroma INSERT
    │                 │
    │                 └── return
    │
    ▼
下一轮对话开始 → retrieve() 获取更新后的 Memory
```

---

## 第三部分：Memory 生命周期

```
┌──────────────────────────────────────────────────────────────────┐
│                        Memory 生命周期                             │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  [创建]  after_turn() 或 remember()                               │
│     │     FactExtractor 提取 → 语义去重 → 写入                     │
│     ▼                                                            │
│  [读取]  retrieve()                                               │
│     │     Pipeline._build_sp() 每次 Agent 调用前检索               │
│     ▼                                                            │
│  [更新]  _dedup_and_store()                                       │
│     │     语义相似 → FactStore UPDATE (importance 提升)            │
│     │     SQLite: SELECT → UPDATE importance, source              │
│     │     新增内容 → FactStore INSERT + VectorStore INSERT         │
│     ▼                                                            │
│  [删除]  forget(entity)                                           │
│     │     FactStore.clear(entity) + VectorStore.clear(entity)     │
│     │     SQLite: DELETE WHERE entity_name = ?                    │
│     │     VectorStore: collection.delete(where={"entity": ...})   │
│     ▼                                                            │
│  [过期]  FactStore.expire(days=90)                                 │
│           SQLite: DELETE WHERE created_at < datetime('now','-N')  │
│           ⚠ 当前未自动调用，需手动触发                               │
│                                                                  │
│  /clear         → Runtime.reset_session() → 清空对话历史          │
│                   ⚠ 不清除长期记忆                                 │
│                                                                  │
│  /memory-clear  → MemoryManager.forget() → 清空全部长期记忆       │
│                   ⚠ 不清除对话历史                                 │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 第四部分：读取流程（Retrieve）详细

```
User Query
    │
    ▼
Pipeline._build_sp()                                          ← 调用入口
    │
    ▼
MemoryManager.retrieve(query="", entity="user", limit=10)
    │
    ├── [路径 A] VectorStore 可用 且 query 非空:
    │     MemoryVectorStore.search(query, entity, k=5)
    │       └── Chroma.similarity_search()                     ← LangChain 官方 API
    │     ↓
    │     对每条结果: FactStore.search(content[:30], entity, 1) ← 补全元数据
    │     ↓
    │     return list[MemoryItem]  (importance, source, created_at 从 SQLite)
    │
    └── [路径 B] VectorStore 不可用 或 query 为空:
          FactStore.search(query, entity, limit)
            └── SELECT * FROM facts
                  WHERE entity_name = ? AND content LIKE ?
                  ORDER BY importance DESC, created_at DESC
            ↓
            return list[MemoryItem]
    │
    ▼
ContextBuilder.build(memory_items=items)
    │
    ├── _sort_memory(items)                                     ← 排序
    │     └── key=(importance, created_at), reverse=True
    │
    ├── _trim_memory(sorted, budget=800 tokens)                 ← Token Budget
    │     └── 累加 token → 超标跳过整条（不截断半句话）
    │
    └── format_memory(trimmed)
          └── "[长期记忆]\n- fact1\n- fact2\n..."
    │
    ▼
system_prompt (第 5 层, Personality → Agent → Skills → Files → Memory → Channel)
```

**排序策略：** `importance DESC → created_at DESC`（高重要性优先，同重要性时更新者优先）

---

## 第五部分：写入流程（Remember / after_turn）详细

```
Assistant Reply 完成
    │
    ▼
Runtime._trigger_memory(user_input, response)
    │
    │  asyncio.create_task(...)  ← 后台异步, 不阻塞
    │
    ▼
MemoryManager.after_turn(user_input, response, entity)
    │
    ├── [1] FactExtractor.extract(user_input, response)          ← aux_llm
    │         │ prompt: _EXTRACTION_PROMPT (中文, 重要性评分 0.3-0.9)
    │         │ output: ExtractedFacts → [{content, importance}, ...]
    │         └── 失败 → 返回 [] → 不影响主流程
    │
    └── [2] for each fact {content, importance}:
              │
              _dedup_and_store(entity, content, importance)
                │
                ├── [2a] VectorStore 可用?
                │     MemoryVectorStore.search_similar(content, entity, k=3)
                │       └── Chroma.similarity_search_with_score()  ← LangChain
                │     ↓
                │     for each top-3 {content, score}:
                │       score ≥ dedup_threshold (0.90)?
                │         YES → FactStore.add(entity, existing_content)  ← UPDATE
                │                 只提升 importance, 不修改原始内容文本
                │                 不写入 VectorStore (已存在)
                │         NO  → 继续检查下一条
                │
                └── [2b] 无相似 或 VectorStore 不可用:
                      FactStore.add(entity, content)                  ← INSERT
                      MemoryVectorStore.add([MemoryItem(...)])        ← Chroma INSERT
    │
    ▼
返回写入数量 (int)
```

**谁负责抽取:** `FactExtractor` (aux_llm Structured Output)
**谁负责写入:** `_dedup_and_store` → `FactStore.add()` (SQLite)
**谁负责同步:** `_dedup_and_store` → `MemoryVectorStore.add()` (Chroma), 仅新增时
**谁负责更新:** `FactStore.add(existing_content)` → SELECT 命中 → UPDATE

---

## 第六部分：SQLite 职责

### Schema

```sql
CREATE TABLE facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_name TEXT NOT NULL,
    content     TEXT NOT NULL,              -- 自然语言事实句子
    importance  REAL NOT NULL DEFAULT 0.5,
    source      TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_facts_entity ON facts(entity_name);
```

### SQLite 负责

- 元数据存储 (id, importance, source, created_at)
- 精确去重 (SELECT ON entity_name + content 二元组)
- 关键词检索 (LIKE)
- CRUD (add/get_all/search/delete/clear/expire)
- WAL 模式支持并发读

### SQLite 不负责

- Embedding 生成 (由 VectorStore/Embeddings model 负责)
- 语义检索 (由 VectorStore 负责)
- 语义去重 (由 MemoryManager._dedup_and_store 编排, VectorStore 提供相似度)
- Token Budget 裁剪 (由 ContextBuilder 负责)
- Prompt 格式化 (由 ContextBuilder.format_memory 负责)

---

## 第七部分：VectorStore 职责

### 实现

`MemoryVectorStore` — 基于 LangChain Chroma + OpenAIEmbeddings。

### VectorStore 负责

- Embedding 生成 (OpenAIEmbeddings: `text-embedding-3-small`)
- 语义相似度检索 (`similarity_search_with_score`)
- 语义去重辅助 (`search_similar` → score ≥ threshold)
- TopK 语义检索 (`similarity_search`)

### VectorStore 不负责

- 元数据存储 (由 SQLite 负责)
- 冲突检测 (不用 LLM)
- Prompt 格式化 (由 ContextBuilder 负责)

### 与 SQLite 协同

```
检索:  VectorStore.search() → 排序结果 → SQLite.search() 补全元数据
写入:  去重检测 → UPDATE SQLite (或 INSERT SQLite + INSERT VectorStore)
清空:  forget() → SQLite.clear() + VectorStore.clear()
```

### 降级策略

- ChromaDB 未安装 → `_enabled=False` → 检索回退 SQLite LIKE，去重回退精确匹配
- Embeddings API Key 不可用 → `_enabled=False` → 同上

---

## 第八部分：Deduplicate 机制

### 判断流程

```
新 Fact (content="用户名叫阿林")
    │
    ▼
VectorStore.search_similar("用户名叫阿林", entity, k=3)
    │
    └── [{content: "用户叫阿林", score: 0.94}, ...]
    │
    ▼
score ≥ 0.90?  ← dedup_threshold (可配置)
    │
    ├── YES: FactStore.add(entity, "用户叫阿林", importance)
    │         └── SQLite SELECT 精确匹配 "用户叫阿林" → UPDATE importance
    │         └── VectorStore 不变 (已有旧 embedding)
    │
    └── NO : FactStore.add(entity, "用户名叫阿林", importance)
              └── SQLite SELECT → 未命中 → INSERT
              └── VectorStore.add([new_item])
```

### 依据

- Embedding 相似度 (cosine similarity via Chroma)
- 阈值 0.90 (可配置, 默认 0.90)
- 不使用 LLM
- 不使用字符串精确匹配 (仅作为 SQLite UPDATE 的后端实现)

### 配置

| 配置 | 默认 | 环境变量 |
|------|------|---------|
| `memory.dedup_threshold` | `0.90` | `MEMORY_DEDUP_THRESHOLD` |

---

## 第九部分：Prompt 构建

### system_prompt 层级结构

```
┌─────────────────────────────────────┐
│ ① Personality                       │  haven.md (系统人格, 固定)
├─────────────────────────────────────┤
│ ② Agent prompt                      │  各 Agent 专属指令 (coder/researcher/...)
├─────────────────────────────────────┤
│ ③ Skills prompt                     │  激活 Skill 的 .md prompt
├─────────────────────────────────────┤
│ ④ Project files                     │  CWD 下 *.py/*.md/*.yaml 文件列表 (≤500 token)
├─────────────────────────────────────┤
│ ⑤ Memory                            │  "[长期记忆]\n- fact1\n- fact2\n..."
│   ← ContextBuilder.format_memory()  │  经排序(importance DESC) + Token Budget(800) 裁剪
├─────────────────────────────────────┤
│ ⑥ Channel hint                      │  "You are communicating via a terminal..."
│   ← _CHANNEL_HINTS[channel]         │
└─────────────────────────────────────┘
```

### Memory 格式化

```
ContextBuilder.format_memory(items)
    ↓
"[长期记忆]\n- 用户有高血压\n- 用户住北京\n- 用户是后端工程师"
```

Memory 作为 `system_prompt` 的第 5 层，在 Personality/Agent/Skills/Files 之后、Channel hint 之前。

---

## 第十部分：Runtime 调用关系

### 创建阶段 (create_runtime)

```
create_runtime()
    │
    ├── cfg = load_config()
    │
    ├── if cfg.memory.enabled:
    │     ├── FactStore(db_path)                                    # SQLite
    │     ├── aux_llm = model_factory.create(aux_model)._raw        # 辅助 LLM
    │     ├── FactExtractor(aux_llm)                                # 提取器
    │     ├── MemoryVectorStore()                                   # VectorStore (降级容错)
    │     └── MemoryManager(fact_store, extractor, vector_store)    # 管理器
    │
    └── Runtime(..., memory_manager=memory_manager)
```

### 读取调用 (每次 Agent 执行前)

```
Runtime.execute() / execute_stream()
    │
    Executor → Pipeline._build_sp()
                  │
                  memory.retrieve(entity=session.user_id)
                  │
                  context_builder.build(memory_items=items)
```

### 写入调用 (每次 Agent 回复后)

```
Runtime.execute() / execute_stream()
    │
    _trigger_memory(user_input, response)
      │
      asyncio.create_task(memory.after_turn(user_input, response))
```

### 清空调用

```
CLI /clear:
    Runtime.reset_session()
      → SessionManager.reset()
      → Agent.reset()

CLI /memory-clear:
    MemoryManager.forget(entity)
      → FactStore.clear(entity)
      → MemoryVectorStore.clear(entity)
```

---

## 第十一部分：命令系统

### `/clear`

| 影响范围 | 清除? | 说明 |
|---------|------|------|
| Conversation History | ✅ | `SessionManager.reset()` → 清空 turn_count/active_skills |
| LangGraph checkpointer | ✅ | `adelete_thread(session_id)` → 清空消息历史 |
| Runtime Context | ✅ | Agent 重置 |
| Memory (长期) | ❌ | 不调用 `forget()` |
| SQLite | ❌ | 不受影响 |
| VectorStore | ❌ | 不受影响 |

### `/memory-clear`

| 影响范围 | 清除? | 说明 |
|---------|------|------|
| SQLite | ✅ | `FactStore.clear(entity)` |
| VectorStore | ✅ | `MemoryVectorStore.clear(entity)` |
| Conversation History | ❌ | 不受影响 |
| LangGraph checkpointer | ❌ | 不受影响 |
| Runtime Context | ❌ | 不受影响 |

---

## 第十二部分：目录职责

| 文件 | 职责 | 入口函数 | 调用者 | 被调用 | 核心? |
|------|------|---------|--------|--------|-------|
| `base.py` | MemoryItem 数据类 | — | FactStore, VectorStore | — | 辅助 |
| `manager.py` | 统一记忆管理入口 | remember, retrieve, recall, forget, after_turn | Runtime, Pipeline | FactStore, FactExtractor, VectorStore | **核心** |
| `fact_store.py` | SQLite 语义事实 CRUD | add, search, get_all, get_all_text, delete, clear, expire | MemoryManager | — | **核心** |
| `extractor.py` | LLM 语义事实提取 | extract(user_input, agent_response) → list[dict] | MemoryManager.after_turn | aux_llm | **核心** |
| `vector_store.py` | LangChain Chroma VectorStore | search, search_similar, add, clear | MemoryManager | Chroma, OpenAIEmbeddings | **核心** |
| `conflict_resolver.py` | LLM 冲突检测 | check, resolve_batch | **零调用** (未集成) | — | 辅助(未集成) |
| `vector_memory.py` | 旧 ChromaDB 直接调用 | add, search, clear | **零调用** (被 MemoryVectorStore 替代) | — | 废弃(保留) |

---

## 第十三部分：最终总结

```
Memory 核心入口:         MemoryManager
Memory 核心类:           MemoryManager, FactStore, FactExtractor, MemoryVectorStore

Memory 读取入口:         MemoryManager.retrieve() → Pipeline._build_sp()
Memory 写入入口:         MemoryManager.after_turn() → Runtime._trigger_memory()
Memory 删除入口:         MemoryManager.forget() → CLI /memory-clear
Memory 检索入口:         MemoryVectorStore.search() (语义) + FactStore.search() (关键词)

SQLite 职责:            元数据存储、精确去重、关键词 LIKE 检索
VectorStore 职责:        Embedding 生成、语义检索、语义去重辅助

Runtime 调用链:          Runtime → Pipeline._build_sp → retrieve (读)
                        Runtime → _trigger_memory → after_turn (写)

Prompt 调用链:           Pipeline → retrieve → ContextBuilder.sort → trim(800t) → format → system_prompt[5]

Memory 生命周期:         创建(after_turn) → 更新(语义去重) → 查询(retrieve) → 删除(forget/expire)

优点:
  - 单一入口 (MemoryManager) 贯穿所有操作
  - SQLite + VectorStore 双存储，各自负责不同维度
  - 语义去重基于 Embedding 相似度，不依赖 LLM
  - 降级容错：VectorStore 不可用 → 纯 SQLite 模式
  - Token Budget 在 ContextBuilder，Memory 层不关心 Prompt 长度
  - 写入异步执行 (asyncio.create_task)，不阻塞对话

目前存在的限制（仅客观分析）:
  - FactStore.expire() 无自动调用者，旧记忆需手动清理
  - ConflictResolver 代码完整但未集成 (依赖 LLM 判断冲突)
  - VectorMemory (旧版) 代码保留但未使用，存在代码冗余
  - MemoryVectorStore 依赖 OpenAIEmbeddings API Key，无 Key 时降级
  - 检索结果未做 BM25 + Vector 混合排序 (当前仅 Vector 或 LIKE 二选一)
  - FactStore 同步 sqlite3，虽在后台协程中不影响主流程，但仍有改进空间
```

---

> 所有分析基于 `src/haven/memory/` 真实源码，日期 2026-06-13。
