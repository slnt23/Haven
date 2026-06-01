# Haven Runtime 审计

> 审计日期: 2026-06-01  
> 审计范围: `src/haven/runtime/` + `src/haven/core/` + `src/haven/memory/` + `src/haven/tools/` + `src/haven/workflows/`  
> 版本: V2.0.0

---

## 1. Runtime Architecture

### 1.1 AgentRuntime — 纯执行引擎

| 属性 | 说明 |
|------|------|
| **文件** | `src/haven/runtime/runtime.py` (388 行) |
| **职责** | LLM 初始化/切换、工具注册/绑定/执行调度、消息组装、工具调用循环 |
| **明确排除** | 不分类用户意图、不决定激活哪些 skill、不含硬编码人格 prompt、不直接读取子系统 |

**核心字段:**

```
AgentRuntime
├── llm: BaseChatModel | None          # 当前 LLM
├── _tools: dict[str, BaseTool]         # 全部已注册工具
├── _active_tools: list[BaseTool]       # 当前 bind 到 LLM 的工具
├── memory: AgentMemory                 # V1 兼容 facade → V2 MemoryManager
├── state: RuntimeState                 # 会话级状态
├── prompt_builder: PromptBuilder       # System prompt 薄层校验
├── context_manager: ContextManager     # 统一上下文收集
├── _tool_manager: ToolManager          # Provider 编排
├── _tool_resolver: ToolResolver        # 动态工具解析
└── max_iterations: int                 # 工具调用循环上限 (默认 20)
```

**核心方法:**

| 方法 | 职责 |
|------|------|
| `init_llm(model_name?)` | 延迟初始化 LLM |
| `switch_model(model_name)` | 切换模型 + 工具自动重绑 |
| `register_tool(tool)` | 注册单个工具 |
| `activate_tools(names)` | 激活工具子集 |
| `bind_tools_to_llm()` | 将激活工具 bind 到 LLM |
| `resolve_tools(skills, permissions)` | 委托 ToolResolver 解析 |
| `build_system_prompt(...)` | 委托 ContextManager.build() → PromptBuilder.build() |
| `build_messages(task, system_prompt, history)` | 组装消息列表 |
| `run(task, **kwargs)` | **核心入口** — 一次完整 LLM+Tool 调用 |
| `save_turn(user, response)` | 保存一轮对话到 Memory |
| `reset()` | 清空 memory + 重置 turn_count |

### 1.2 PlannerAgent — 任务规划层

| 属性 | 说明 |
|------|------|
| **文件** | `src/haven/runtime/planner.py` (432 行) |
| **职责** | 意图分类 + Skill 选择 + 任务拆解 + Workflow 匹配 |
| **核心输出** | `ExecutionPlan` Pydantic 模型 |

**3 条执行路径:**

```
planner.execute(task)
├── 路径 1: simple + no workflow + no steps → runtime.run() 直通
├── 路径 2: medium/complex + steps + no workflow → _execute_steps() 拓扑排序
└── 路径 3: workflow != null → _execute_via_workflow() → WorkflowGraph.run()
```

**关键设计决策:** 一次 LLM 调用完成全部规划（`with_structured_output(ExecutionPlan)`），不再像 V1 那样先分类再选 Skill 再拆步骤——三次 LLM 调用合成一次。

### 1.3 MemoryManager — 四层记忆编排

| 属性 | 说明 |
|------|------|
| **文件** | `src/haven/memory/manager.py` (295 行) |
| **职责** | 统一编排 Working / Episodic / Semantic / Vector 四层 |

**数据流:**

```
record_turn(user, assistant)
├── 1. WorkingMemory.add_message()          # 立即追加到滑动窗口
├── 2. EpisodicMemory.store_turn()          # 持久化到 SQLite
├── 3. VectorMemory.store()                 # 异步 embed (可选)
├── 4. asyncio.create_task(_extract_facts)  # LLM 提取事实 → Semantic
├── 5. asyncio.create_task(working.summarize) # 滑动窗口溢出时 LLM 摘要
└── 6. 每 10 轮触发 consolidate()          # 后台衰减清理
```

**检索:**

```
retrieve(task) → MemoryContext
├── working.retrieve()         # 最近 20 条消息
├── episodic.retrieve()       # 30 天内高重要性记录
├── semantic.retrieve()       # 实体-事实知识图
└── vector.retrieve()         # 语义相似度检索 (可选)
```

### 1.4 ToolManager — 统一工具管理

| 属性 | 说明 |
|------|------|
| **文件** | `src/haven/tools/manager.py` (253 行) |
| **职责** | Provider 注册/启停、全局工具注册表、多条件检索 |

**架构:**

```
ToolManager
├── _providers: dict[str, ToolProvider]     # builtin, mcp:puppeteer, ...
├── _tools: dict[str, HavenTool]            # 全局注册表 (去重)
├── _tool_to_provider: dict[str, str]       # 来源映射
│
├── 生命周期: start_all() / stop_all() / refresh_all()
├── 检索:
│   ├── get_tool(name)
│   ├── get_tools_for_skills(names)
│   ├── get_tools_by_names(names)
│   ├── get_tools_by_tags(tags)
│   ├── get_tools_by_categories(categories)
│   ├── get_tools_by_provider(name)
│   └── filter_tools(category, tag, provider, only_available)
└── 状态: get_status() / format_status()
```

### 1.5 WorkflowGraph — DAG 执行引擎

| 属性 | 说明 |
|------|------|
| **文件** | `src/haven/workflows/graph.py` (266 行) |
| **职责** | 图构建、节点调度、条件路由、重试、Checkpoint |

```
WorkflowGraph
├── _nodes: dict[str, WorkflowNode]
├── _edges: dict[str, Edge | ConditionalEdge]
├── _entry_point: str
├── _checkpointer: Checkpointer
├── _max_iterations: int (默认 20)
│
├── 构建: add_node / add_edge / add_conditional_edge / set_entry_point
└── 执行: run(state, runtime) → WorkflowState
          ├── 恢复 checkpoint (如果 resume_from)
          ├── es.start()
          ├── while current != END:
          │   ├── node(state) → updates dict
          │   ├── _apply_updates(state, updates)
          │   ├── checkpoint.save(state)
          │   └── edge.resolve(state) → next_node
          └── return state
```

### 1.6 ContextManager — 统一上下文收集

| 属性 | 说明 |
|------|------|
| **文件** | `src/haven/core/context.py` (424 行) |
| **职责** | 从 6 个来源收集 ContextItem，按优先级组装为 system prompt |

**6 个上下文来源 + 优先级:**

| 来源 | ContextSource | Priority | 内容 |
|------|--------------|----------|------|
| 人格 Skill | PERSONALITY | 0 (最高) | `haven.md` 的 system persona |
| 领域 Skill | SKILL | 1 | Planner 激活的领域 skill prompt |
| 长期记忆 | MEMORY | 2 | SemanticMemory 事实 (confidence ≥ 0.3，最多 15 条) |
| 工作流状态 | WORKFLOW | 3 | current_node + node_outputs (截断 600 字符) |
| 工具结果 | TOOL_RESULT | 4 | 前步骤工具执行结果 (截断 800 字符) |
| RAG | RAG | 5 (最低) | 外部知识检索结果 |

---

## 2. 生命周期 — 一次请求完整流程

```
Phase 0: 初始化 (首次)
─────────────────────────────────────────────────────
CLI: RuntimeService.start()
  └─ Factory.create_agent(session_id, entity_name, channel)
       ├─ AgentRuntime() + init state/memory
       ├─ _load_all_skills() → SkillRegistry (haven.md + skills/*.md)
       ├─ init_llm() → create_llm() → ChatDeepSeek / ChatOpenAI
       ├─ _init_tools()
       │    ├─ ToolManager.add_provider(BuiltinProvider)
       │    ├─ ToolManager.add_provider(MCPProvider) × N
       │    ├─ ToolManager.start_all() → discover → sync
       │    └─ ToolResolver(tm) → runtime._tool_resolver
       ├─ bind_tools_to_llm()
       └─ PlannerAgent(runtime, WorkflowRegistry)

Phase 1: 规划 (每次请求)
─────────────────────────────────────────────────────
User Input → PlannerAgent.plan(task)
  │
  ├─ _is_trivial(task)? → fast-path ExecutionPlan
  │    (你好/hi/谢谢 等 10 个硬编码关键词或 ≤2 字符)
  │
  └─ _llm_plan(task)
       ├─ SkillRegistry.get_selection_context() → skill 菜单
       ├─ WorkflowRegistry.get_selection_context() → workflow 菜单
       ├─ SystemMessage(PLANNER_SYSTEM_PROMPT.format(skill_menu, workflow_menu))
       ├─ llm.with_structured_output(ExecutionPlan).ainvoke([System, Human(task)])
       └─ → ExecutionPlan {goal, intent, skills, steps, workflow}
            │
            ├─ SkillRegistry.resolve_dependencies(skills) → 传递闭包
            └─ _validate_plan(plan) → 过滤无效 skill

Phase 2: 执行 (3 条路径)
─────────────────────────────────────────────────────

路径 1 — Runtime 直通:
  runtime.run(task, use_memory=True)
    ├─ context_manager.build(personality_skills=[haven], use_memory=True)
    │    ├─ collect() → 6 源 ContextItem[]
    │    └─ assemble() → 优先级排序 + token 预算裁剪
    ├─ build_messages(task, system_prompt) → [System, History..., Human]
    ├─ _invoke_direct(llm, messages) → llm.ainvoke → response
    └─ save_turn(task, response)

路径 2 — 多步编排:
  planner._execute_steps(plan, task)
    ├─ _topological_sort(steps) → 按依赖拓扑排序
    └─ for step in ordered:
         ├─ runtime.resolve_tools([step.skill])
         │    └─ ToolResolver.resolve(skill_names, channel, permissions)
         │         ├─ 5 级匹配: name → MCP → tag → category → capability
         │         └─ _apply_filters: availability + permissions + channel
         ├─ runtime.run(step_task, active_skills, tool_results)
         │    └─ context_manager.build(..., tool_results=prev_results)
         └─ step_outputs[step.order] = result

路径 3 — Workflow DAG:
  planner._execute_via_workflow(plan, task)
    ├─ WorkflowRegistry.build(plan.workflow) → WorkflowGraph
    ├─ _make_state(wf_name, task) → DevWorkflowState / ResearchWorkflowState / ...
    └─ graph.run(state, runtime)
         ├─ es.start()
         ├─ while current ≠ END:
         │    ├─ node = _nodes[current]
         │    ├─ updates = await node(state) → 内部调用 runtime.run()
         │    ├─ _apply_updates(state, updates) → execution.* + state.*
         │    ├─ checkpoint.save(state) → SQLite
         │    └─ edge.resolve(state) → next_node / RETRY / END
         └─ return state

Phase 3: 后处理
─────────────────────────────────────────────────────
  ├─ save_turn(task, response)
  ├─ asyncio.create_task(extract_facts_async)  # 后台 LLM 事实提取
  └─ state.turn_count += 1
```

---

## 3. 状态管理

### 3.1 RuntimeState — 会话级状态

| 字段 | 类型 | 生命周期 | 说明 |
|------|------|---------|------|
| `session_id` | str | 会话期间 | 会话标识 |
| `entity_name` | str | 会话期间 | 用户实体名 (用于 Semantic Memory) |
| `channel` | str | 会话期间 | cli / socket / feishu / email |
| `active_skills` | list[str] | 单轮 (reset_turn 清空) | Planner 注入的当前轮 skill |
| `active_tools` | list[str] | 单轮 | Planner 注入的当前轮工具 |
| `turn_count` | int | 会话期间 (累加) | 当前会话轮次计数 |
| `current_node` | str | 不定 | Workflow 当前节点名 |
| `context` | dict[str,str] | 单轮 | 跨步骤临时上下文 |
| `last_plan` | dict | 单轮 | 最近一次 ExecutionPlan |

**边界:** RuntimeState = 会话级身份 + 单轮配置。不追踪任务进度。

### 3.2 ExecutionState — 任务级状态

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | str | UUID4 12 位 hex，唯一标识一次任务执行 |
| `goal` | str | 任务目标 (从 ExecutionPlan.goal 同步) |
| `current_step` | str | 当前执行的节点/步骤名 |
| `completed_steps` | list[str] | 已完成步骤名列表 |
| `failed_steps` | list[str] | 失败步骤名列表 |
| `step_outputs` | dict[str,str] | {步骤名: 输出文本} |
| `retry_count` | int | 当前步骤重试计数 |
| `max_retries` | int | 每节点最大重试次数 (默认 3) |
| `node_retry_counts` | dict[str,int] | {节点名: 重试次数} |
| `status` | str | pending → running → completed / failed / paused |
| `final_output` | str | 最终输出 |
| `errors` | list[str] | 错误收集 |
| `created_at` | float | `time.time()` |
| `updated_at` | float | 每次变更自动更新 |

**生命周期方法:**

```
es.start()           pending → running
es.complete_step()   completed_steps += [name], step_outputs[name] = output
es.fail_step()       failed_steps += [name], errors += [error]
es.finish()          running → completed
es.fail()            running → failed, errors += [error]
es.pause()           running → paused
es.resume()          paused → running
```

**边界:** ExecutionState = 任务级进度 + 重试追踪。不关心会话身份（那是 RuntimeState 的事），不关心领域数据（那是 WorkflowState 的事）。

**三者关系:**

```
RuntimeState (会话级)   →  谁在对话，第几轮，当前用哪些 skill/tool
ExecutionState (任务级) →  这个任务进行到哪了，哪步完成了，哪步失败了
WorkflowState (领域级)  →  架构文档、源代码、review 反馈、测试报告...
```

---

## 4. 上下文管理

### 4.1 收集流程

```
ContextManager.build(personality_skills, domain_skills, workflow_state, tool_results, rag_context, use_memory)
  │
  ├─ collect()
  │   ├─ _collect_skills(personality_skills, PERSONALITY)
  │   │    └─ 遍历 skill，提取 prompt_extension 或 prompt 字段
  │   │       → ContextItem(content=prompt, source=PERSONALITY, priority=0)
  │   │
  │   ├─ _collect_skills(domain_skills, SKILL)
  │   │    └─ 同上 → ContextItem(source=SKILL, priority=1)
  │   │
  │   ├─ _collect_memory()  (if use_memory)
  │   │    └─ memory.get_long_term_context()
  │   │       → "长期记忆 — 以下是你已知的关于当前用户的信息\n- key: value\n..."
  │   │       → ContextItem(source=MEMORY, priority=2)
  │   │
  │   ├─ _collect_workflow(workflow_state)  (if given)
  │   │    ├─ f"[当前工作流阶段: {state.current_node}]"
  │   │    └─ f"[工作流节点 '{name}' 输出]\n{output[:600]}"
  │   │       → ContextItem(source=WORKFLOW, priority=3)
  │   │
  │   ├─ _collect_tool_results(results)  (if given)
  │   │    └─ f"[工具 '{name}' 执行结果]\n{result[:800]}"
  │   │       → ContextItem(source=TOOL_RESULT, priority=4)
  │   │
  │   ├─ _collect_rag(rag_context)  (if non-empty)
  │   │    └─ "[参考知识 — 请优先基于以下资料回答]\n{content}"
  │   │       → ContextItem(source=RAG, priority=5)
  │   │
  │   └─ extra_collectors  (插件扩展点)
  │
  └─ assemble(items)
       └─ ContextAssembler.assemble(items)
            ├─ sorted(items, key=priority)   # 低优先级数值 = 高优先级
            ├─ for each item:
            │    ├─ TokenBudget.estimate(content)
            │    │    └─ chinese_chars × 1.5 + other_chars ÷ 3
            │    ├─ if fits → append
            │    └─ else → truncate + "已截断" → break
            └─ join("\n\n") → system prompt string
```

### 4.2 Token 预算

```
TokenBudget (默认 max_tokens=4000)
├─ 中文: 1 token ≈ 1.5 字符
├─ ASCII: 1 token ≈ 3 字符
└─ 超出预算: 从低优先级 SOURCE 开始裁剪 + 截断标记
```

---

## 5. Tool 调用流程

```
Skill.tools: ["code_exec", "file_ops", "web_search"]
  │
  ▼
ToolResolver.resolve(skill_names=["coder"], channel="cli", permissions=["read","write"])
  │
  ├─ _collect_requirements(["coder"])
  │    └─ SkillRegistry.get("coder").tools → ["code_exec", "file_ops", "web_search"]
  │
  ├─ _match_all(requirements)
  │    └─ for each req:
  │         ├─ Level 1: _name_index.get("code_exec") → HavenTool ✅ 命中
  │         ├─ Level 2: MCP 前缀 "github__search_code" → 按名查找
  │         ├─ Level 3: _tag_index.get("code_exec") → 标签匹配
  │         ├─ Level 4: _category_index.get("code") → 类别匹配
  │         └─ Level 5: _CAPABILITY_CATEGORY["code"] → ToolCategory.CODE
  │              → _category_index["code"] → 候选列表 → _pick_best()
  │
  ├─ _apply_filters(tools, channel, permissions, only_available)
  │    ├─ _is_available(tool): 检查 provider 是否 CONNECTED
  │    ├─ _has_permission(tool, granted): execute → 需要 write
  │    └─ channel 过滤: tags 中若有 "channel:email" 则限 email 通道
  │
  └─ → ResolveResult
       ├─ tools: [HavenTool("code_exec"), HavenTool("file_ops"), HavenTool("web_search")]
       ├─ unresolved: []
       ├─ warnings: []
       └─ source_map: {code_exec: "builtin", file_ops: "builtin", ...}

  ▼
AgentRuntime.bind_tools_to_llm()
  └─ llm.bind_tools(active_tools)

  ▼
LLM 调用 → response.tool_calls:
  [
    {"name": "code_exec", "args": {"code": "print('hello')"}, "id": "call_abc"},
    {"name": "file_ops", "args": {"op": "read", "path": "/tmp/test.py"}, "id": "call_def"}
  ]

  ▼
_invoke_with_tool_loop(llm, messages):
  while iteration < max_iterations:
    response = await llm.ainvoke(messages)
    if not response.tool_calls:
      return response.content   # 最终文本
    
    for tc in tool_calls:
      tool = _tools.get(tc["name"])        # 从注册表查找
      result = await tool.ainvoke(args)     # 执行工具
      messages.append(ToolMessage(result))   # 追加结果

    iteration += 1
```

---

## 6. Workflow 执行流程

```
                      WorkflowGraph.run(state, runtime)
                      ═══════════════════════════════

                        ┌──────────────────┐
                        │   es.start()     │  pending → running
                        │   current =      │
                        │   entry_point    │
                        └────────┬─────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   current == END ?      │──── yes ──→ es.finish()
                    └────────────┬────────────┘
                                 │ no
                    ┌────────────▼────────────┐
                    │   node = _nodes[current]│
                    │   es.current_step =     │
                    │   current               │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   await node(state)     │  ← 节点内部调用 runtime.run()
                    │                         │
                    │   内部:                  │
                    │   prompt = _build_      │
                    │   prompt(state)          │
                    │   output = await        │
                    │   runtime.run(prompt)    │
                    │   updates =             │
                    │   _process_output()     │
                    │   return updates        │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   _apply_updates(       │  双写:
                    │     state, updates)     │  execution.* ← 权威
                    │                         │  state.*     ← 兼容
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   checkpoint.save(      │  SQLite
                    │     session_id,         │  UPSERT
                    │     current, state)     │  state_json + execution_json
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   edge = _edges[current]│
                    └────────────┬────────────┘
                                 │
                 ┌───────────────┼───────────────┐
                 │               │               │
            Edge          ConditionalEdge     No Edge
           ┌─────┐        ┌──────────┐       ┌──────┐
           │target│        │ router() │       │ END  │
           └──┬──┘        └────┬─────┘       └──┬───┘
              │                │                │
              │    ┌───────────┼───────────┐    │
              │    │           │           │    │
              │  node       RETRY        END    │
              │    │      ┌──────┐               │
              │    │      │retry<│               │
              │    │      │max?  │               │
              │    │      └──┬───┘               │
              │    │      yes│no                  │
              │    │      retry  fail()           │
              │    │      current                 │
              ▼    ▼       ▼         ▼            ▼
              next_node    current   END         END
```

### 预定义工作流拓扑

**dev_flow (5 节点):**
```
planner → architect → coder → reviewer → tester
                          ▲                   │
                          │    fail (≤3)      │
                          └───────────────────┘
```

**research_flow (3 节点):**
```
searcher → analyst → synthesizer
    ▲                     │
    │   知识缺口 (≤3)     │
    └─────────────────────┘
```

**diagnosis_flow (3 节点):**
```
collector → analyzer → adviser
```

---

## 7. 错误恢复机制

### 7.1 当前实现的恢复层级

| 层级 | 机制 | 位置 | 行为 |
|------|------|------|------|
| **L1: 工具调用异常** | try/except | `runtime.py:_invoke_with_tool_loop` | 单个 tool_call 失败 → 错误消息作为 ToolMessage 返回 LLM，LLM 可决定重试 |
| **L2: 节点执行异常** | try/except | `workflows/graph.py:run()` | 节点抛异常 → `updates = {"errors": [...], "status": "failed"}` → `es.fail()` |
| **L3: 节点重试 (RETRY)** | ConditionalEdge.RETRY | `workflows/graph.py:run()` | Router 返回 RETRY → 回跳当前节点（≤ max_retries） |
| **L4: 工作流失败** | es.fail() | `workflows/graph.py:run()` | 超过最大重试 → `es.fail(error_msg)` → `status = "failed"` |
| **L5: LLM 规划失败** | try/except | `planner.py:_llm_plan()` | Structured Output 失败 → fallback ExecutionPlan(intent=chat, steps=[]) |

### 7.2 缺失的恢复机制

| 缺失项 | 严重程度 | 说明 |
|--------|---------|------|
| **LLM 调用重试** | HIGH | `_invoke_direct` 和 `_invoke_with_tool_loop` 无 LLM 层面的 retry (network error / rate limit) |
| **MCP 连接断线重连** | MEDIUM | Provider 状态 DEGRADED/ERROR 后无自动重连 |
| **Workflow 超时中断** | MEDIUM | `_max_iterations=20` 仅有循环计数器，无 wall-clock 超时 |
| **部分失败回滚** | LOW | 多步任务中步骤 N 失败后，步骤 1..N-1 的副作用无法回滚 |
| **Checkpoint 损坏恢复** | LOW | `execution_json` 解析失败时吞掉异常返回 None，无降级策略 |

---

## 8. Checkpoint 机制

### 8.1 架构

```
SQLiteCheckpointer (.data/memory.db)
  │
  ├─ 表: workflow_checkpoints
  │    ├─ session_id TEXT
  │    ├─ node_name TEXT
  │    ├─ state_json TEXT         ← 完整 WorkflowState (asdict, 排除 _前缀)
  │    ├─ execution_json TEXT     ← ExecutionState.snapshot() 单独列
  │    └─ created_at TIMESTAMP
  │    UNIQUE(session_id, node_name)  — UPSERT 语义
  │
  ├─ save(session_id, node_name, state):
  │    ├─ _serialize(state) → 排除 _runtime / _前缀字段
  │    ├─ state_json = json.dumps(state_dict)
  │    ├─ execution_json = json.dumps(state.execution.snapshot())
  │    └─ INSERT ... ON CONFLICT DO UPDATE
  │
  ├─ load(session_id):
  │    ├─ SELECT ... ORDER BY created_at DESC LIMIT 1
  │    ├─ state_dict = json.loads(state_json)
  │    ├─ ExecutionState.from_snapshot(execution_json) → 重建 ES 对象
  │    └─ return {state, execution, node_name}
  │
  └─ list_sessions() → 列出所有活跃 checkpoint (node_name ≠ '__END__')
```

### 8.2 恢复流程

```
graph.run(state, runtime, resume_from="session_abc")
  ├─ saved = checkpoint.load("session_abc")
  ├─ if saved["execution"]:
  │    state.execution = saved["execution"]   # 恢复 ExecutionState 对象
  ├─ if es.status == "paused":
  │    es.resume()
  ├─ current = es.current_step or entry_point  # 从断点继续
  └─ 正常执行循环...
```

### 8.3 Checkpoint 时机

```
每个节点执行完成后 → checkpoint.save()
工作流正常结束 (END) → checkpoint.save(node="__END__")
```

---

## 9. 当前缺失能力

| # | 缺失能力 | 优先级 | 说明 |
|---|---------|--------|------|
| 1 | **LLM 调用重试** | P0 | 网络错误 / rate limit 无自动重试，直接抛异常 |
| 2 | **流式 Streaming** | P0 | `RuntimeService.chat_stream()` 是模拟的 (字符分块 sleep)，Runtime 无原生 `astream` |
| 3 | **取消/中断** | P0 | 无 `CancellationToken` 或 `asyncio.CancelledError` 传递。用户 Ctrl+C 直接杀进程 |
| 4 | **MCP 断线重连** | P1 | Provider 进入 ERROR 后无自动恢复 |
| 5 | **请求级超时** | P1 | `agent_max_execution_time` 配置了但未在 Runtime 中强制 |
| 6 | **并行工具调用** | P1 | `_invoke_with_tool_loop` 串行执行 tool_calls。LangChain 支持 `batch` 但未使用 |
| 7 | **Tool 结果缓存** | P2 | 同一轮内多次调用同一工具(相同参数)无缓存 |
| 8 | **Token 用量追踪** | P2 | 无累计 token 计数、无成本估算 |
| 9 | **多模态** | P2 | 不支持图片/音频输入 |
| 10 | **Human-in-the-loop** | P2 | Tool 的 `requires_confirmation` 字段声明了但未实现确认流程 |
| 11 | **Agent 间通信** | P2 | 无子 agent 或 agent 间消息传递 |
| 12 | **Skill 热加载** | P2 | Skill 修改后需重启，无法 `refresh_all()` |
| 13 | **Rate Limit** | P2 | ToolMetadata 有 `rate_limit_per_minute` 但未实施 |
| 14 | **审计日志** | P3 | 无结构化日志/审计追踪 |

---

## 10. 与 Cursor Runtime 对比

| 维度 | Haven V2 | Cursor |
|------|----------|--------|
| **编程语言** | Python 3.14+ | TypeScript (VS Code 扩展) |
| **Agent 架构** | PlannerAgent + AgentRuntime (规划/执行分离) | Composer Agent (一体化) |
| **上下文管理** | ContextManager 6 源收集 + 优先级 + Token 预算 | VS Code 原生 API (editor context, terminal, file system, LSP) |
| **工具系统** | ToolManager + Provider (Builtin + MCP) | VS Code 扩展 API + 内置工具 |
| **记忆系统** | 四层记忆 (Working/Episodic/Semantic/Vector) | 会话上下文 + .cursorrules |
| **工作流** | WorkflowGraph DAG 引擎 + 3 预定义工作流 | 无独立工作流引擎，Agent 内联处理 |
| **多通道** | CLI + Socket + Email + 飞书 | VS Code IDE 内 |
| **流式输出** | **缺失** (模拟) | 原生 SSE streaming |
| **代码编辑** | 通过 FileOpsTool，无 diff 粒度 | 内联 diff apply，精确到行 |
| **RAG** | RAGSearchTool (外部) | @Codebase / @Docs 语义索引 |
| **MCP 支持** | 原生 stdio + HTTP SSE | 原生 (Cursor 是 MCP 主要推动者) |
| **错误恢复** | 基本的 try/except + Workflow RETRY | 自动修正循环 + Apply/Reject |
| **扩展性** | Skill .md 文件 + MCP 工具 | .cursorrules + MCP + VS Code 扩展 |
| **成熟度** | Alpha (~8K 行, 0 测试) | Production (数百万用户) |

**Haven 优势:** 四层记忆系统、独立 DAG 工作流引擎、多通道守护进程  
**Haven 劣势:** 无流式输出、无代码 diff、无 LSP 集成、无测试、成熟度差距巨大

---

## 11. 与 Claude Code Runtime 对比

| 维度 | Haven V2 | Claude Code |
|------|----------|-------------|
| **编程语言** | Python 3.14+ | TypeScript (Node.js) |
| **Agent 架构** | PlannerAgent (规划) + AgentRuntime (执行) + WorkflowGraph (DAG) | 单一 Agent 循环 (Think → Act → Observe) |
| **规划方式** | 一次 LLM Structured Output 生成完整 ExecutionPlan | 逐步推理，每步基于当前状态决策 |
| **上下文管理** | ContextManager 6 源收集 + TokenBudget | 系统 prompt + 对话历史 + 文件内容 + Agent 子任务 |
| **工具系统** | ToolManager + Provider 架构 | 内置工具集 (Bash, Read, Write, Edit, Glob, Grep) |
| **工具调用** | 串行 (`_invoke_with_tool_loop`) | 并行工具调用 (独立工具同时执行) |
| **子 Agent** | 无 | Agent 工具可 spawn 子 agent (Explore, Plan, general-purpose) |
| **工作流** | 预定义固定 DAG (dev/research/diagnosis) | `Plan` agent + TaskCreate/TaskUpdate 动态任务追踪 |
| **记忆系统** | 四层持久化记忆 (SQLite + ChromaDB) | CLAUDE.md + memory/ 文件系统持久化 |
| **Checkpoint** | SQLiteCheckpointer (节点级) | 对话上下文压缩 (compaction) |
| **模型切换** | `switch_model()` 运行时切换 | 支持多模型族 (Opus/Sonnet/Haiku) |
| **流式输出** | **缺失** | 原生 |
| **权限系统** | ToolPermission (READ/WRITE/EXECUTE/SEND) | 用户手动批准 + 权限模式 |
| **多通道** | CLI + Socket + Email + 飞书 | CLI + IDE 扩展 |
| **隔离执行** | 无 | Worktree 沙箱 (git worktree 隔离) |
| **后台任务** | 无 | `run_in_background` + Cron 调度 |
| **Hook 系统** | 无 | 用户可配置的 hook (事件驱动) |
| **MCP 支持** | 原生 | 原生 |
| **成熟度** | Alpha | Production |

**Haven 优势:** 独立 Planner/Executor 分层、四层记忆持久化、DAG 工作流引擎  
**Haven 劣势:** 无子 Agent、无 Worktree 隔离、无 Hook、无并行工具执行、无后台任务、无 Cron 调度

---

## 12. 与 Devin Runtime 对比

| 维度 | Haven V2 | Devin |
|------|----------|-------|
| **编程语言** | Python 3.14+ | TypeScript/Python (沙箱) |
| **Agent 架构** | PlannerAgent + AgentRuntime | 多 Agent 协作 (Planner + Coder + Reviewer + Shell) |
| **执行环境** | 本地进程 | Docker 容器 / 云沙箱 |
| **规划粒度** | ExecutionPlan (goal + steps + dependencies) | 多层规划 (High-level plan → Task list → Sub-tasks) |
| **代码执行** | CodeExecTool (本地 subprocess) | 隔离沙箱 + 浏览器 + Shell + LSP |
| **上下文管理** | ContextManager (6 源, 优先级) | IDE 全量上下文 + 浏览器 + Terminal + 文件树 |
| **工具系统** | 6 内置 + MCP 扩展 | 丰富内置 (browser, shell, editor, git, GitHub, Slack...) |
| **记忆系统** | 四层记忆 (Working/Episodic/Semantic/Vector) | 会话级 + 知识库 (playbooks) |
| **工作流** | 固定 DAG 模板 | 动态 Playbook + 自学习 |
| **多模态** | **不支持** | 支持 (screenshot, browser) |
| **人机协作** | 无 | Human-in-the-loop (PR Review, Approval) |
| **错误恢复** | 基本 RETRY + try/except | 自动回滚 + 多策略恢复 |
| **成本追踪** | 无 | Token + 时间 + 资源成本可视 |
| **CI/CD 集成** | 无 | GitHub/GitLab PR 集成 |
| **安全** | 无沙箱 | 容器隔离 + 权限边界 |
| **成熟度** | Alpha | Production (企业级) |

**Haven 优势:** 架构清晰、模块化良好、Provider 模式扩展便利  
**Haven 劣势:** 无沙箱、无浏览器、无 LSP、无多模态、无人机协作、无 CI 集成、无安全边界

---

## 13. 架构评分

| 维度 | 评分 | 权值 | 加权 | 评语 |
|------|------|------|------|------|
| **模块化** | 7/10 | 15% | 1.05 | 分层清晰，但 core/memory vs memory/ 边界模糊 |
| **可扩展性** | 8/10 | 15% | 1.20 | Provider + Skill .md + MCP 扩展路径清晰 |
| **可维护性** | 6/10 | 15% | 0.90 | 零测试 = 事实上的维护风险天花板 |
| **状态管理** | 8/10 | 10% | 0.80 | RuntimeState/ExecutionState/WorkflowState 三级分治清晰 |
| **上下文管理** | 8/10 | 10% | 0.80 | ContextManager 6 源收集 + 优先级 + Token 预算，设计良好 |
| **工具系统** | 9/10 | 15% | 1.35 | Provider + ToolResolver 5 级匹配是架构亮点 |
| **工作流引擎** | 8/10 | 10% | 0.80 | DAG 引擎简洁实用，Checkpoint 设计合理 |
| **错误恢复** | 5/10 | 5% | 0.25 | 基本 try/except + RETRY，缺 LLM 重试/超时/取消 |
| **性能** | 5/10 | 5% | 0.25 | 串行工具执行、无流式、无缓存 |
| **综合** | **7.4/10** | 100% | **7.40** | — |

### 雷达图数据 (文本)

```
           模块化 (7)
              ▲
             / \
            /   \
  可维护性(6)   可扩展性(8)
          /       \
         /         \
  错误恢复(5)   工具系统(9)
         \         /
          \       /
  性能(5)       状态管理(8)
            \   /
             \ /
         工作流引擎(8)
```

---

## 附录: 关键指标

| 指标 | 值 |
|------|-----|
| AgentRuntime 行数 | 388 |
| PlannerAgent 行数 | 432 |
| 运行时总行数 (runtime/) | ~1200 |
| 直接组件引用 (AgentRuntime) | 8 |
| 支持 LLM Provider | 2 (DeepSeek, OpenAI 兼容) |
| 工具匹配级别 | 5 |
| 内置工具数 | 6 |
| 预定义工作流 | 3 |
| 记忆层级 | 4 |
| 上下文来源数 | 6 |
| Checkpoint 存储 | SQLite (UPSERT) |
| 最大工具调用迭代 | 20 |
| 最大节点重试 | 3 |
| 并发支持 | asyncio (单 Planner) |
| 测试覆盖 | 0 |
