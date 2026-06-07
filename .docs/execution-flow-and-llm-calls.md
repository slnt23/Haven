# Haven 执行流程与 LLM 调用点

> 生成日期: 2026-06-07 | Haven v3.0.0

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                          CLI / Daemon                                │
│                     Runtime.execute(task)                             │
└────────────────────────────┬────────────────────────────────────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
     ┌────────────────┐           ┌─────────────────┐
     │  Coordinator    │           │   Dispatcher     │
     │  (任务规划)      │ ──────→  │  (执行调度)       │
     │                 │  plan    │                  │
     │  🤖 LLM 调用 #1  │          │  三条执行路径:     │
     │  Structured     │          │  ① Workflow      │
     │  Output         │          │  ② 多步编排       │
     └────────────────┘          │  ③ 直接对话       │
                                  └────────┬────────┘
                                           │
                         ┌─────────────────┼─────────────────┐
                         │                 │                 │
                         ▼                 ▼                 ▼
                  ┌────────────┐   ┌────────────┐   ┌────────────┐
                  │ Workflow   │   │ Multi-Step │   │  Direct    │
                  │ Graph      │   │ Loop       │   │  Agent     │
                  └─────┬──────┘   └─────┬──────┘   └─────┬──────┘
                        │                │                 │
                        ▼                ▼                 ▼
                  ┌─────────────────────────────────────────────┐
                  │              BaseAgent                       │
                  │        create_react_agent(model, tools)      │
                  │                                              │
                  │  🤖 LLM 调用 #2  (ReAct 循环)                │
                  │  ┌───────────────────────────────────────┐  │
                  │  │ LLM → ToolCall → ToolResult → LLM →  │  │
                  │  │ ... (可能多轮)                         │  │
                  │  └───────────────────────────────────────┘  │
                  └──────────────────────┬──────────────────────┘
                                         │
                                         ▼
                                  ┌─────────────┐
                                  │  返回结果    │
                                  └──────┬──────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │  MemoryPipeline      │
                              │  (后台异步, 非阻塞)   │
                              │                      │
                              │  🤖 LLM 调用 #3       │
                              │  FactExtractor        │
                              │  Structured Output    │
                              │         │             │
                              │         ▼             │
                              │  FactStore.add()      │
                              │  → memory.db          │
                              └─────────────────────┘
```

---

## 二、LLM 调用点详解

### 🤖 LLM 调用 #1：Coordinator 任务规划

| 项目 | 值 |
|------|-----|
| **位置** | `src/haven/runtime/coordinator.py:215` → `_llm_plan()` |
| **模型** | **主模型** `deepseek-v4-pro` |
| **调用方式** | `llm.with_structured_output(ExecutionPlan)` → `structured_llm.ainvoke([SystemMessage, HumanMessage])` |
| **输入** | System prompt（可用 Skill 菜单 + 可用 Workflow 菜单）+ 用户原始输入 |
| **输出** | `ExecutionPlan` JSON — goal / intent / agent_type / skills / workflow / steps |
| **特例** | 简单问候触发 `_is_trivial()` 快速路径，不调 LLM |
| **DeepSeek** | 此调用禁用 thinking 模式（`thinking: {type: disabled}`），因为 Structured Output 不支持 |

**调用流程**:
```
Coordinator.plan(task)
  → _is_trivial(task)  → 琐碎输入? 直接返回默认计划 (无 LLM)
  → _llm_plan(task)
      → 构建 Skill 菜单 (SkillRegistry.get_domain_skills())
      → 构建 Workflow 菜单 (WorkflowRegistry.get_selection_context())
      → llm.with_structured_output(ExecutionPlan).ainvoke(prompt)
      → 校验返回的 Plan (skill 引用是否有效)
```

---

### 🤖 LLM 调用 #2：Agent ReAct 循环

| 项目 | 值 |
|------|-----|
| **位置** | `src/haven/runtime/agents/base.py:109` → `agent.ainvoke()` |
| **模型** | **主模型** `deepseek-v4-pro` |
| **调用次数** | **单次 run() 内可能多次** — ReAct 循环中每轮 tool call 都是独立 LLM 调用 |
| **调用方式** | `create_react_agent(model=llm, tools=tools, checkpointer=...)` → LangGraph 自动管理 |
| **输入** | SystemMessage(system_prompt) + HumanMessage(task) + 历史消息（checkpointer 恢复） |
| **输出** | 文本响应 或 ToolCall → 工具执行 → 结果注入消息 → 再次 LLM |

**system_prompt 组装**（`ContextBuilder.build()`）:
```
① Personality    ← haven.md (全局人格, 始终注入)
② Agent prompt   ← haven.yaml agents.<name>.prompt
③ Skills prompt  ← Coordinator 选中的 skill.md
④ Project files  ← CWD 文件列表 (≤500 token)
⑤ History        ← FactStore.get_all_text(entity) [长期记忆]
```

**三种执行路径**:
```
Dispatcher.dispatch(plan, task)
  ├─ 路径 ①: plan.workflow 存在
  │   → _execute_via_workflow()
  │   → compiled_graph.ainvoke(state, config)
  │   → 每个节点内 run_agent_node() → agent.run()
  │   → 🤖 每个节点可能触发 LLM 调用 #2
  │
  ├─ 路径 ②: plan.steps 非空
  │   → 拓扑排序
  │   → 每步 agent.run(step_task)
  │   → 🤖 每步触发 LLM 调用 #2
  │
  └─ 路径 ③: 直接对话
      → agent.run(task, system_prompt)
      → 🤖 LLM 调用 #2
```

---

### 🤖 LLM 调用 #3：长期记忆事实提取

| 项目 | 值 |
|------|-----|
| **位置** | `src/haven/memory/extractor.py:94` → `self._llm.ainvoke()` |
| **模型** | **辅助模型** `deepseek-v4-flash` |
| **时机** | `Runtime.execute()` / `execute_stream()` **返回后**，通过 `asyncio.create_task()` 后台异步执行 |
| **调用方式** | `llm.with_structured_output(ExtractedFacts)` → `structured_llm.ainvoke([HumanMessage(prompt)])` |
| **输入** | 提取 prompt（规则说明 + 用户输入 + Agent 回复） |
| **输出** | `ExtractedFacts` JSON — `[{content: "事实句子", importance: 0.8}, ...]` |
| **DeepSeek** | 此调用禁用 thinking 模式 |

**调用流程**:
```
Runtime.execute(task)
  → plan = coordinator.plan(task)         # 🤖 LLM #1
  → result = dispatcher.dispatch(plan)     # 🤖 LLM #2
  → _trigger_memory(task, result)
      → asyncio.create_task(
            pipeline.after_turn(task, result)
              → extractor.extract(user_input, agent_response)  # 🤖 LLM #3
              → store.add(entity, content, importance) × N
        )
  → return result  (不等待 #3 完成)
```

---

## 三、各路径 LLM 调用次数统计

| 场景 | LLM #1 (规划) | LLM #2 (Agent) | LLM #3 (记忆) | 总计 |
|------|:------------:|:-------------:|:------------:|:----:|
| 琐碎问候 ("你好") | 0 (快速路径) | 1 | 1 (后台) | 2 |
| 简单问答 ("1+1=?") | 1 | 1+ (可能多轮 ReAct) | 1 (后台) | 3+ |
| 工作流 (dev_flow) | 1 | 5 × N (5 节点, 每节点可能多轮) | 1 (后台) | 7+ |
| 多步编排 | 1 | N 步 × 每步多轮 | 1 (后台) | 2+ |
| 流式对话 | 1 | 1+ (流式) | 1 (后台) | 3+ |

---

## 四、模型职责划分

```
主模型 (deepseek-v4-pro)
  ├── Coordinator.plan()       结构化任务分类
  ├── BaseAgent.run()          ReAct 循环 (对话 + 工具调用)
  └── Workflow 节点执行        代码生成 / 搜索 / 分析等

辅助模型 (deepseek-v4-flash)
  └── FactExtractor.extract()  后台语义事实提取
```

---

## 五、关键文件索引

| 文件 | 角色 |
|------|------|
| `runtime/coordinator.py` | Coordinator + ExecutionPlan schema + 🤖 LLM #1 |
| `runtime/dispatcher.py` | 三条执行路径路由 |
| `runtime/agents/base.py` | BaseAgent + create_react_agent + 🤖 LLM #2 |
| `runtime/context.py` | ContextBuilder — system_prompt 五段组装 |
| `runtime/factory.py` | Runtime 装配 + 触发 🤖 LLM #3 |
| `memory/extractor.py` | FactExtractor + 🤖 LLM #3 |
| `memory/pipeline.py` | MemoryPipeline — 编排 extract→store |
| `memory/fact_store.py` | FactStore — SQLite CRUD |
| `tools/loader.py` | ToolLoader — 工具发现+注册 |
| `tools/providers/builtin.py` | 内置工具自动发现 |
| `tools/providers/mcp.py` | MCP 工具接入 (stdio/HTTP/WS) |
| `config/haven.md` | 全局人格 (健健) |
| `config/haven.yaml` | Agent 定义 + 系统配置 |
| `config/models.yaml` | 模型定义 + API Key 映射 |
