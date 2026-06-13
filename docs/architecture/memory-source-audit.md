# Memory Source Audit：/clear + /memory-clear 之后 Prompt 仍包含用户信息

> 分析日期: 2026-06-13
> 仅分析，不修改代码

---

## 问题复现

```
> /clear
  正在清空会话（对话历史 + 上下文）...
  会话已清除（长期记忆未受影响）

> /memory-clear
  长期记忆已清除（SQLite + VectorStore 同步）

> 我是？
  Agent: 您叫阿林，是自由职业者，独居在外，最近在学开发 Agent...
```

---

## 最终发送给 LLM 的 Prompt 构成

```
                    最终 Prompt
                         │
          ┌──────────────┼──────────────┐
          │              │              │
     SystemMessage   Conversation    HumanMessage
     (system_prompt)   History       (task="我是？")
          │              │
          ▼              ▼
    ContextBuilder   LangGraph
    .build()         SqliteSaver
          │          (checkpointer)
          │              │
    ┌─────┼─────┐       ▼
    │     │     │   resource/
 Persona Agent Skills checkpoint.db
(haven.md)│   (.md)      │
          │          thread_id=
     Memory+Channel  "default"
     (已清除✓)       (未清除✗)
```

---

## 逐来源分析

### 1. System Prompt (ContextBuilder)

| 维度 | 内容 |
|------|------|
| 名称 | system_prompt |
| 来源文件 | `runtime/context.py` → `ContextBuilder.build()` |
| 构建函数 | `build(agent_prompt, skills, task, memory_items, channel)` |
| 调用位置 | `execution/pipeline.py:209` → `context_builder.build(...)` |
| 是否参与 Prompt | **是** — 作为 `SystemMessage` 注入 |
| 会被 `/clear` 清除 | 否（system_prompt 每次动态构建，不持久化） |
| 会被 `/memory-clear` 清除 | **间接** — 如果 Memory 已清空，`memory_items` 为空列表，`format_memory([])` 返回空字符串 |

### 2. Memory Items (长期记忆)

| 维度 | 内容 |
|------|------|
| 名称 | memory_items → `[长期记忆]` |
| 来源文件 | `memory/manager.py` → `MemoryManager.retrieve()` |
| 构建函数 | `retrieve(entity, limit)` |
| 调用位置 | `execution/pipeline.py:204` → `memory.retrieve(entity=session.user_id)` |
| 是否参与 Prompt | **是** — 通过 `ContextBuilder.format_memory()` 格式化为 `[长期记忆]\n- fact1\n- fact2` |
| 会被 `/clear` 清除 | **否** |
| 会被 `/memory-clear` 清除 | **是** ✅ `MemoryManager.forget()` → SQLite + VectorStore 同步清除 |

### 3. Conversation History (LangGraph Checkpointer)

| 维度 | 内容 |
|------|------|
| 名称 | 对话历史 messages |
| 来源文件 | `agent/base.py:70` → `create_agent(model, tools, checkpointer=self._checkpointer)` |
| 构建函数 | `agent.ainvoke({"messages": [SystemMessage, HumanMessage]}, config={"configurable": {"thread_id": ...}})` |
| 调用位置 | `agent/base.py:142` → `agent.ainvoke(...)` |
| 是否参与 Prompt | **是** — LangGraph 自动从 checkpointer 读取 `thread_id` 对应的所有历史消息，注入到 messages 列表 |
| 会被 `/clear` 清除 | **否** ✗ `Runtime.reset_session()` 不调用 `checkpointer.adelete_thread()` |
| 会被 `/memory-clear` 清除 | **否** ✗ `MemoryManager.forget()` 不接触 checkpointer |

### 4. Runtime Context (SessionState)

| 维度 | 内容 |
|------|------|
| 名称 | turn_count, active_skills, active_tools |
| 来源文件 | `session/models.py` → `SessionState` |
| 构建函数 | `SessionManager.reset()` |
| 调用位置 | `Runtime.reset_session()` |
| 是否参与 Prompt | **否** — SessionState 是运行时元数据，不注入 Prompt |
| 会被 `/clear` 清除 | **是** ✅ |
| 会被 `/memory-clear` 清除 | **否** |

### 5. SQLite Memory (FactStore)

| 维度 | 内容 |
|------|------|
| 名称 | 语义事实 |
| 来源文件 | `memory/fact_store.py` |
| 构建函数 | `FactStore.get_all_text()` |
| 调用位置 | 经 `MemoryManager.retrieve()` → `Pipeline` → `ContextBuilder` |
| 是否参与 Prompt | **是** — 格式化后作为 `[长期记忆]` |
| 会被 `/clear` 清除 | **否** |
| 会被 `/memory-clear` 清除 | **是** ✅ |

### 6. VectorStore Memory (Chroma)

| 维度 | 内容 |
|------|------|
| 名称 | embedding + 语义检索结果 |
| 来源文件 | `memory/vector_store.py` |
| 构建函数 | `MemoryVectorStore.search()` |
| 调用位置 | `MemoryManager.retrieve()` |
| 是否参与 Prompt | **是** — 结果传给 `ContextBuilder.format_memory()` |
| 会被 `/clear` 清除 | **否** |
| 会被 `/memory-clear` 清除 | **是** ✅ |

---

## 根因定位

### 真正导致问题的是：**LangGraph SqliteSaver Checkpointer**

```
Agent 看到的对话历史:
┌──────────────────────────────────────────────────────────────┐
│  User: 我叫阿林，自由职业者，最近在学开发 Agent               │  ← checkpointer 持久化
│  Agent: 好的阿林，记住了！                                    │  ← checkpointer 持久化
│  User: 有什么增肥的方法？                                     │  ← checkpointer 持久化
│  Agent: (workflow 输出，含用户信息回顾)                       │  ← checkpointer 持久化
│  ─── /clear ───                                              │
│  ─── /memory-clear ───                                       │
│  User: 我是？                                                │  ← 新消息
│  Agent 看到的历史: 所有上面的消息 ← 仍在 checkpointer 中！     │
└──────────────────────────────────────────────────────────────┘
```

**结论：** Agent 通过 LangGraph SqliteSaver 看到了自己之前的回复，其中包含"阿林"、"自由职业者"等信息。这是 LangGraph 的 checkpointer 自动行为——它以 `thread_id` 为键持久化所有消息，并在每次调用时自动注入。

### 为什么 `/clear` 没清除

```python
# runtime/factory.py:105-108
async def reset_session(self, session_id: str = "default") -> None:
    self.session_manager.reset(session_id)     # ← 只清除 SessionState
    for agent in self.agents.values():
        agent.reset()                          # ← 只清除 Agent 内部缓存
    # ← 缺失: await self.checkpointer.adelete_thread(session_id)
```

`SessionManager.reset()` 的 docstring 写道 "消息历史在 checkpointer 中由新 thread_id 隔离"，但实际上：
1. 没有删除旧 thread
2. 没有生成新 thread_id
3. Session 的 `id` 属性是 frozen 的，无法更改

---

## Memory Source Diagram

```
                    LLM Prompt
                         │
          ┌──────────────┼──────────────┐
          │              │              │
    SystemMessage   History       HumanMessage
          │         (messages)        │
          │              │              │
    ┌─────┴─────┐       │         "我是？"
    │           │       │
 Persona    Skills      │
(haven.md)  (.md)       │
    │           │       │
 Memory    Channel   ★ 问题来源 ★
[长期记忆]   Hint    LangGraph SqliteSaver
(已清空✓)          (checkpoint.db)
                    thread_id="default"
                    ─────────────────
                    │  User: 我叫阿林...
                    │  Agent: 好的阿林...
                    │  User: 有什么增肥...
                    │  Agent: (回复)...
                    ─────────────────
                    
 ★ 这是 /clear 和 /memory-clear 都无法清除的来源 ★
```

---

## 修复方向（不实施，仅记录）

`Runtime.reset_session()` 需要增加：

```python
await self.checkpointer.adelete_thread(session_id)
```

或者 `SessionManager.reset()` 内部生成新 thread_id 以隔离旧消息。
