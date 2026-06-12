# Haven 项目完整架构与执行流程分析

> 分析日期：2026-06-12
> 分析范围：src/haven/ 全量源码
> 分析方法：基于真实源码的调用链追踪，非经验推测

---

## 目录

1. [项目整体架构图](#第一部分项目整体架构图)
2. [项目启动流程](#第二部分项目启动流程)
3. [用户输入流程](#第三部分用户输入流程)
4. [一次完整 Agent 运行流程](#第四部分一次完整-agent-运行流程)
5. [Runtime 职责](#第五部分runtime-职责)
6. [Memory 流程](#第六部分memory-流程)
7. [Planner 流程](#第七部分planner-流程)
8. [Tool 流程](#第八部分tool-流程)
9. [Model 流程](#第九部分model-流程)
10. [Session 流程](#第十部分session-流程)
11. [Config 体系](#第十一部分config-体系)
12. [模块依赖关系](#第十二部分模块依赖关系)
13. [时序图](#第十三部分时序图)
14. [生命周期分析](#第十四部分生命周期分析)
15. [最终总结](#第十五部分最终总结)

---

## 第一部分：项目整体架构图

```
                        ┌──────────────────────┐
                        │       User           │
                        │  (Terminal / Feishu) │
                        └──────────┬───────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
              ▼                    ▼                    ▼
        ┌──────────┐       ┌──────────┐         ┌──────────┐
        │ CLI REPL │       │ Feishu   │         │ Daemon   │
        │ (Rich)   │       │ WebSocket│         │ (TCP)    │
        └────┬─────┘       └────┬─────┘         └────┬─────┘
             │                  │                    │
             └──────────────────┼────────────────────┘
                                │
                     ┌──────────▼──────────┐
                     │    Runtime           │  ← 容器，持有所有组件
                     │  (factory.py:34)     │
                     └──────────┬──────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
          ▼                     ▼                     ▼
   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
   │ Coordinator  │    │  Dispatcher  │    │  BaseAgent×4 │
   │ (规划)       │    │  (调度执行)   │    │ coder        │
   │ plan()       │───▶│  dispatch()  │───▶│ researcher   │
   │              │    │  3条路径     │    │ diagnosis    │
   └──────────────┘    └──────┬───────┘    │ general      │
                              │            └──────┬───────┘
                              │                   │
          ┌───────────────────┼───────────────────┤
          │                   │                   │
          ▼                   ▼                   ▼
   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
   │ ContextBuild │    │  WorkflowReg │    │   LLM        │
   │ (prompt组装) │    │  (DAG引擎)   │    │ (DeepSeek/   │
   │ 5级优先级    │    │  dev/res/diag│    │  OpenAI)     │
   └──────────────┘    └──────────────┘    └──────────────┘
          │                                        │
          ▼                                        ▼
   ┌──────────────┐                        ┌──────────────┐
   │ SkillRegistry│                        │ ToolLoader   │
   │ (领域技能)   │                        │ Builtin+MCP  │
   └──────────────┘                        └──────────────┘
                                                    │
          ┌─────────────────────────────────────────┤
          │                                         │
          ▼                                         ▼
   ┌──────────────┐                        ┌──────────────┐
   │ FactStore    │                        │ ToolRegistry │
   │ (SQLite)     │                        │ (全局注册)   │
   └──────┬───────┘                        └──────────────┘
          │
          ▼
   ┌──────────────┐
   │ MemoryPipeln │
   │ FactExtractor│
   │ (后台异步)   │
   └──────────────┘

   ┌──────────────────────────────────────────────────────┐
   │                   INFRASTRUCTURE                     │
   │  AsyncSqliteSaver (checkpoint.db)                    │
   │  Settings (pydantic-settings)                        │
   │  Config YAML (OmegaConf deep-merge)                  │
   └──────────────────────────────────────────────────────┘
```

**架构总结**：这是一个典型的 **Coordinator + Dispatcher + Multi-Agent** 三层架构。Coordinator 负责一次 LLM 调用完成规划，Dispatcher 根据计划选择三条执行路径之一，BaseAgent 是 LangGraph `create_agent` 的薄封装。所有组件在 `factory.create_runtime()` 中装配，返回一个 `Runtime` 容器。

---

## 第二部分：项目启动流程

### 入口点

**文件**: `src/haven/cli/main.py:11` → `main_cli()`

```
main_cli()
  │
  ├── [1] sys.stdout/stderr 重配置为 UTF-8 (main.py:14-15)
  │
  ├── [2] logging.basicConfig() → stderr, INFO 级别 (main.py:18-22)
  │      格式: "[%(name)s] %(levelname)s: %(message)s"
  │
  ├── [3] 抑制 langgraph 类型注解警告 (main.py:25)
  │
  └── [4] asyncio.run(run_repl())  (main.py:28)
            │
            ▼
         run_repl()  (repl.py:41)
            │
            ├── [5] Console(highlight=False) → Rich 实例 (repl.py:43)
            │
            ├── [6] await create_runtime(channel="cli")  (repl.py:46)
            │       │
            │       ├── 6a. RuntimeState() → session_id="default" (factory.py:167)
            │       ├── 6b. _load_all_skills() → 加载系统人格 + CWD skills/ (factory.py:173)
            │       ├── 6c. create_llm() → 从 models.yaml 读取默认模型 (factory.py:177)
            │       ├── 6d. ToolLoader().load_all() → Builtin + MCP 工具 (factory.py:182)
            │       ├── 6e. AsyncSqliteSaver(checkpoint.db) → 共享 checkpointer (factory.py:188)
            │       ├── 6f. ContextBuilder() + FactStore + MemoryPipeline (factory.py:193)
            │       ├── 6g. BaseAgent×4 → 每个 Agent 持有 LLM + 全部工具 + checkpointer (factory.py:219)
            │       ├── 6h. import workflows → 注册 dev/research/diagnosis 工作流 (factory.py:231)
            │       ├── 6i. Coordinator(llm, WorkflowRegistry) (factory.py:235)
            │       ├── 6j. Dispatcher(agents, ...) (factory.py:241)
            │       └── 6k. Runtime(coordinator, dispatcher, ...) (factory.py:251)
            │
            ├── [7] console.print(_BANNER) → 显示横幅 (repl.py:50)
            ├── [8] console.print(_HELP) → 显示帮助 (repl.py:52)
            │
            └── [9] while True → REPL 循环 (repl.py:54)
                      │
                      ├── 等待用户输入 (repl.py:56)
                      ├── 内建命令处理 (/model, /tools, ...) (repl.py:65)
                      └── runtime.execute_stream(user_input) → 流式对话 (repl.py:89)
```

### 启动流程图

```
[main.py]                    [factory.py]                   [外部资源]
   │                              │                              │
   │  main_cli()                  │                              │
   │  ├─ stdout/stderr UTF-8      │                              │
   │  ├─ logging→stderr           │                              │
   │  └─ run_repl() ─────────────▶│                              │
   │                              │  create_runtime()            │
   │                              │  ├─ RuntimeState()           │
   │                              │  ├─ _load_all_skills() ──────▶ CWD/skills/*.md
   │                              │  ├─ create_llm() ────────────▶ models.yaml
   │                              │  ├─ ToolLoader.load_all() ───▶ builtin/ + mcp.json
   │                              │  ├─ AsyncSqliteSaver() ──────▶ resource/checkpoint.db
   │                              │  ├─ FactStore() ─────────────▶ resource/memory.db
   │                              │  ├─ BaseAgent×4
   │                              │  ├─ Coordinator + Dispatcher
   │                              │  └─ return Runtime ◀─────────
   │                              │
   │  ◀─────── Runtime ───────────│
   │
   │  [REPL 循环开始，等待输入]
```

---

## 第三部分：用户输入流程

以"你好"为例：

```
User 输入 "你好"
    │
    ▼
repl.py:56  _async_input("\n> ")  →  "你好"
    │
    ▼
repl.py:89  runtime.execute_stream("你好")
    │
    ├── factory.py:83  plan = await coordinator.plan("你好")
    │       │
    │       └── coordinator.py:144  _is_trivial("你好")
    │               "你好" ∈ _TRIVIAL → True (快速路径)
    │               ↓
    │           coordinator.py:145  返回 ExecutionPlan(
    │               goal="日常对话",
    │               intent="chat",
    │               agent_type="general",
    │               complexity="simple",
    │               skills=[],
    │               workflow=None,
    │               steps=[]
    │           )
    │
    ├── factory.py:84  yield StreamChunk(kind="plan", content="chat → general (复杂度: simple)")
    │
    └── factory.py:89  dispatcher.dispatch_stream(plan, "你好")
            │
            ├── dispatcher.py:67-68  plan.steps → [] (空)
            ├── dispatcher.py:67-68  plan.workflow → None
            │
            └── 路径3: 直接对话 (dispatcher.py:119-124)
                    │
                    ├── _pick_agent(plan) → agents["general"]
                    │
                    ├── prepare_agent(agent, []) → _build_system_prompt()
                    │       │
                    │       ├── skills=[] → 不加载 Skill prompt
                    │       ├── _use_memory=True → fact_store.get_all_text("user")
                    │       └── context_builder.build()
                    │               ├── ① Personality (haven.md)
                    │               ├── ② Agent prompt (general="" → 跳过)
                    │               ├── ③ Skills (空)
                    │               ├── ④ Project files (≤500 token)
                    │               └── ⑤ History (FactStore 文本)
                    │
                    ├── yield StreamChunk(kind="status", "分发执行: 直接对话")
                    │
                    └── agent.astream("你好", system_prompt=...)
                            │
                            └── base.py:199  agent.astream_events(...)
                                    │
                                    ├── on_chat_model_stream → yield StreamChunk("text", token)
                                    └── 逐 token 流式输出
```

---

## 第四部分：一次完整 Agent 运行流程

以"帮我调研一下 Python 3.14 的新特性"为例：

```
Phase 1: 规划 (Coordinator)
─────────────────────────────────────────────────────────
  factory.py:83   coordinator.plan("帮我调研一下 Python 3.14 的新特性")
      │
      ├── _is_trivial → False (不是问候语/短文本)
      ├── _cache_key → MD5 (检查缓存)
      ├── _llm_plan()
      │       ├── 构建 SystemMessage (含 Skill 菜单 + Workflow 菜单)
      │       ├── LLM Structured Output → ExecutionPlan
      │       └── 异常时 fallback 到 general 默认计划
      │
      ├── SkillRegistry.resolve_dependencies(plan.skills)
      ├── _validate_plan() → 过滤不存在的 skill/workflow
      └── 返回 ExecutionPlan(
              goal="调研 Python 3.14 新特性",
              intent="research",
              agent_type="researcher",
              complexity="medium",
              skills=["web-research"],
              workflow="research",
              steps=[]
          )

Phase 2: 调度 (Dispatcher)
─────────────────────────────────────────────────────────
  dispatcher.dispatch_stream(plan, task)
      │
      ├── plan.workflow="research" → 存在且注册
      │
      └── 路径1: _execute_via_workflow(plan, task)
              │
              ├── WorkflowRegistry.build("research") → CompiledStateGraph
              │       节点: searcher → analyst → (synthesizer / searcher)
              │       │         │            │
              │       │         │    ┌───────┘
              │       │         │    │ 知识缺口 → 回 searcher
              │       │         │    │ 无缺口 → synthesizer → END
              │
              ├── _make_workflow_state("research", task)
              │       包含: task, messages, plan_skills, node_retry_counts 等
              │
              └── compiled_graph.ainvoke(state, config)
                      │
                      ├── searcher 节点:
                      │     run_agent_node() → agent.run(搜索任务)
                      │     Agent 调用 web_search 工具 → 获取搜索结果
                      │     LLM 分析结果 → 写入 raw_findings
                      │
                      ├── analyst 节点:
                      │     run_agent_node() → agent.run(分析任务)
                      │     LLM 分析 raw_findings → 输出 analyzed_insights
                      │
                      ├── research_router:
                      │     检查 "知识缺口" in analyzed_insights
                      │     AND searcher 重试次数 < 3
                      │     → 有缺口: 回 searcher (最多3次)
                      │     → 无缺口: 进 synthesizer
                      │
                      └── synthesizer 节点:
                            run_agent_node() → agent.run(总结任务)
                            LLM 生成 Markdown 格式最终报告
                            → 写入 final_output

Phase 3: 记忆提取 (MemoryPipeline)
─────────────────────────────────────────────────────────
  factory.py:93   _trigger_memory(task, response_text)
      │
      └── asyncio.create_task( pipeline.after_turn(task, response) )
          (后台非阻塞)
              │
              ├── FactExtractor.extract(task, response)
              │       辅助 LLM 从对话中提取语义事实
              │       → [{"content": "用户在调研 Python 3.14", "importance": 0.5}, ...]
              │
              └── FactStore.add(entity_name, content, importance)
                      写入 resource/memory.db (SQLite)
                      精确文本去重后插入

Phase 4: 输出 (CLI)
─────────────────────────────────────────────────────────
  repl.py:89-96   消费 StreamChunk
      ├── kind="plan"   → console.print(粗体青色)  "research → researcher (复杂度: medium)"
      ├── kind="status" → console.print(深色)      "分发执行: 工作流 research"
      └── kind="text"   → sys.stdout.write()       最终报告内容
```

### 完整调用链

```
CLI: repl.py:89    runtime.execute_stream(user_input)
    └─ factory.py:83    coordinator.plan(task)
       └─ coordinator.py:137    plan() → _is_trivial | cache | _llm_plan
          └─ coordinator.py:198    _llm_plan() → LLM structured output
    └─ factory.py:89    dispatcher.dispatch_stream(plan, task)
       └─ dispatcher.py:75    dispatch_stream()
          ├─ dispatcher.py:79    workflow path → _execute_via_workflow()
          │  └─ dispatcher.py:176    WorkflowRegistry.build(wf_name)
          │     └─ _helpers.py:27    run_agent_node() per node
          │        └─ base.py:137    agent.run(task, system_prompt)
          │           └─ base.py:164   agent.ainvoke({"messages": msgs})
          ├─ dispatcher.py:89    multi-step path → _execute_steps()
          │  └─ base.py:137    agent.run() per step
          └─ dispatcher.py:119   direct path → agent.astream()
             └─ base.py:199    agent.astream_events({"messages": msgs})
    └─ factory.py:93    _trigger_memory(task, result)
       └─ pipeline.py:44    after_turn(user_input, agent_response)
          └─ extractor.py:89    extract(user_input, agent_response)
             └─ fact_store.py:75    add(entity, content, importance)
```

---

## 第五部分：Runtime 职责

### 定义

`Runtime` (factory.py:34) 是整个系统的 **容器/命名空间**，不是执行器。它不执行任何业务逻辑——只做两件事：

1. **持有所有组件引用**（coordinator, dispatcher, llm, agents, checkpointer, tool_loader, pipeline）
2. **提供便捷方法**（execute, execute_stream, reset_session, switch_model, close）

### 管理的对象

```python
class Runtime:
    coordinator: Coordinator       # 任务规划器
    dispatcher: Dispatcher         # 执行调度器
    llm: BaseChatModel            # 主 LLM 实例
    tool_loader: ToolLoader       # 工具加载器（管理所有 Provider）
    checkpointer: AsyncSqliteSaver # LangGraph 检查点存储
    state: RuntimeState           # 会话级状态
    agents: dict[str, BaseAgent]  # 4个专业 Agent
    _sqlite_conn: aiosqlite       # 原始 SQLite 连接（用于关闭）
    _pipeline: MemoryPipeline     # 长期记忆管道（可能为 None）
```

### 生命周期

```
创建:  create_runtime()  (factory.py:154)
       └── 仅在 CLI/Channel 启动时调用一次

销毁:  runtime.close()  (factory.py:134)
       └── stop_all() → 断开所有 MCP 连接
       └── close() → 关闭 SQLite 连接

会话重置:  runtime.reset_session()  (factory.py:101)
       └── 清空 LangGraph checkpoint 线程
       └── 重置所有 Agent 的 turn_count
       └── 不销毁 Runtime 本身
```

### 它是否属于核心？

**是核心容器，但不是核心逻辑。** 真正的核心逻辑分散在 Coordinator（规划）和 Dispatcher（调度）中。Runtime 的角色是"装配器"——把工厂方法创建的所有零件组装在一起，对外暴露统一接口。

### 哪些模块依赖 Runtime？

```
CLI (repl.py)      → 通过 create_runtime() 获取 Runtime
Feishu Channel     → 通过 create_runtime() 获取 Runtime
Daemon             → 通过 create_runtime() 获取 Runtime
```

Runtime 本身依赖所有其他模块：

```
Runtime
  ├── Coordinator → SkillRegistry, WorkflowRegistry
  ├── Dispatcher  → ContextBuilder, FactStore, SkillRegistry, BaseAgent
  ├── BaseAgent   → LLM, ToolLoader, AsyncSqliteSaver
  ├── ContextBuilder → settings, haven.md
  ├── FactStore   → SQLite
  └── MemoryPipeline → FactExtractor, FactStore
```

---

## 第六部分：Memory 流程

### 何时读取？

每次 Agent 执行前，在 `Dispatcher._build_system_prompt()` (dispatcher.py:228-259)：

```python
# 读取当前 entity_name 的所有事实
facts_text = fact_store.get_all_text(self.state.entity_name)
# 格式化为 "- 事实内容\n- 事实内容..."
# 作为 history_summary 传给 ContextBuilder
```

ContextBuilder 将其放在 system_prompt 的 **最低优先级位置**（第⑤层），仅消费剩余 token 预算。

### 何时写入？

每次 Agent 执行完成后，`Runtime._trigger_memory()` (factory.py:95-99)：

```python
asyncio.create_task(self._pipeline.after_turn(user_input, agent_response))
```

**关键特征：后台异步，不阻塞主流程。** 写入失败不影响对话响应。

### 何时更新？

- **增量添加**：每次对话后，新事实通过 `FactStore.add()` 追加
- **去重**：精确文本匹配（`(entity_name, content)` 组合唯一），重复内容仅更新 importance
- **过期清理**：`FactStore.expire(days=90)` 按创建时间清理旧事实
- **手动清除**：`/memory-clear` 命令 → `MemoryPipeline.clear()` → `FactStore.clear(entity_name)`

### 数据流

```
用户对话完成后:

  Runtime._trigger_memory(task, result)
      │
      ▼
  MemoryPipeline.after_turn(user_input, agent_response)
      │
      ├── FactExtractor.extract(user_input, agent_response)
      │       │
      │       ├── 构建 prompt: "从以下对话中提取关于用户的关键事实..."
      │       ├── 辅助 LLM (aux_llm) 调用 with_structured_output(ExtractedFacts)
      │       └── 失败返回 []，不抛异常
      │
      └── for each fact:
            FactStore.add(entity_name, content, importance)
                │
                └── SQLite INSERT OR REPLACE (精确文本去重)

下次对话前:

  Dispatcher._build_system_prompt()
      │
      ├── FactStore.get_all_text("user")
      │       │
      │       └── SQLite: SELECT content FROM facts
      │           WHERE entity_name='user'
      │           ORDER BY importance DESC
      │
      └── ContextBuilder.build(history_summary=...)
              │
              └── 追加到 system_prompt 末尾（剩余 token 预算内）
```

### 已知限制

- 仅精确文本去重，无语义去重
- 仅支持 LIKE 关键词搜索，无向量语义检索
- VectorMemory (ChromaDB) 在 CLAUDE.md 中记录但未实现
- 无事实冲突检测，矛盾事实可共存
- RAG 配置字段 (settings.rag_*) 已定义但未在代码中使用

---

## 第七部分：Planner 流程

### 何时执行？

每次 `runtime.execute()` 或 `runtime.execute_stream()` 被调用时，**第一步就是 `coordinator.plan(task)`**。

### 三条路径

```
plan(task)
  │
  ├── 快速路径 (_is_trivial)
  │     条件: task ∈ {"你好","hi","hello",...} 或 len(task)≤2
  │     输出: ExecutionPlan(intent="chat", agent_type="general", ...)
  │     跳过: LLM 调用、缓存
  │
  ├── 缓存路径
  │     条件: MD5(task) 在 _plan_cache 中
  │     输出: 缓存的 ExecutionPlan
  │     容量: 128 条
  │
  └── LLM 路径 (_llm_plan)
         │
         ├── 构建 System Prompt (_PLANNER_SYSTEM_PROMPT)
         │       ├── {skill_menu}  → SkillRegistry.get_domain_skills()
         │       └── {workflow_menu} → WorkflowRegistry.get_selection_context()
         │
         ├── LLM with_structured_output(ExecutionPlan)
         │       ├── DeepSeek 模型: 禁用 thinking 模式
         │       └── 单次调用，不重试
         │
         ├── 异常处理: fallback → ExecutionPlan(agent_type="general", ...)
         │
         └── 后处理:
               ├── SkillRegistry.resolve_dependencies() → 传递闭包
               └── _validate_plan() → 过滤无效 skill/workflow 引用
```

### 输出

`ExecutionPlan` (coordinator.py:47-60)：

| 字段 | 含义 | 来源 |
|------|------|------|
| goal | 用户目标概括 | LLM 生成 |
| intent | 意图分类 | LLM 从 Skill 标签中选择 |
| agent_type | coder/researcher/diagnosis/general | LLM 选择 |
| complexity | simple/medium/complex | LLM 判断 |
| skills | 需要激活的 Skill 名列表 | LLM 从菜单选择 |
| workflow | 预定义工作流名 | LLM 从菜单选择 |
| steps | 执行步骤列表 (PlanStep[]) | LLM 生成 |
| reasoning | 规划理由 | LLM 生成 |

### 是否参与 Tool 选择？

**不参与。** Planner 只选择 Skill 和 Workflow。Tool 选择由 LLM Function Calling 在 Agent 执行时动态决定。这是 LangChain `create_agent` 的标准行为。

### 如何影响 Model？

Planner 的输出（agent_type）决定使用哪个 Agent。每个 Agent 有特定的 system_prompt 和 personality。但所有 Agent **共享同一套工具**——工具不在 Planner 层面过滤。

---

## 第八部分：Tool 流程

### 注册

```
ToolLoader.load_all()  (loader.py:44)
  │
  ├── [1] BuiltinProvider.start()
  │       │
  │       ├── 扫描 src/haven/tools/builtin/ 目录
  │       └── 发现工具模块 (web_search.py, file_ops.py 等)
  │           → 每个模块的 tool 函数作为 BaseTool 注册
  │
  ├── [2] for each MCP server in mcp.json:
  │       │
  │       └── MCPProvider(cfg).start()
  │               │
  │               ├── 连接 stdio/HTTP/WebSocket MCP 服务器
  │               ├── 获取远程工具列表
  │               └── 以 "{server_name}__{tool_name}" 命名注册
  │
  └── [3] 所有工具 → ToolRegistry.register(tool, provider=provider_name)
```

### 发现

- **Builtin**：启动时自动扫描 `builtin/` 目录下的 Python 模块
- **MCP**：从 CWD 的 `mcp.json` 解析 `mcpServers` 配置，逐个连接
- 过滤：`enabled: false` 的 MCP 服务器跳过

### 调用

工具调用发生在 **Agent 执行时**，由 LangGraph `create_agent` 自动处理：

```
BaseAgent.run(task)  (base.py:137)
  │
  └── agent.ainvoke({"messages": msgs})
        │
        └── LangGraph ReAct 循环:
              ├── LLM 决策是否需要调用工具
              ├── 如需 → 生成 tool_call (含参数)
              ├── LangGraph 调用对应 BaseTool.invoke()
              ├── Tool 执行 → 返回结果
              └── 结果注入 messages，继续 ReAct
```

**关键：Tool 选择由 LLM Function Calling 自动完成，项目代码不参与选择逻辑。**

### 返回

- Tool 执行结果作为 `ToolMessage` 追加到 messages 列表
- LLM 基于 Tool 结果继续生成最终回复
- 整个过程中间状态通过 `AsyncSqliteSaver` 持久化到 checkpoint

### Runtime 接收结果

Runtime **不直接接收** Tool 结果。Tool 结果在 LangGraph ReAct 循环内部流转。Runtime 最终拿到的是 Agent 的完整文本响应。

### Provider 状态机

```
UNINITIALIZED → CONNECTING → CONNECTED / DEGRADED / ERROR → DISCONNECTED
```

### MCP 传输支持

- **stdio**：子进程通信，command + args
- **HTTP SSE**：Server-Sent Events
- **WebSocket**：双向通信

---

## 第九部分：Model 流程

### Prompt 构建

`ContextBuilder.build()` (context.py:61-120) 按 **5 级优先级** 组装 system_prompt：

```
优先级 (高→低)    来源                   token 预算分配
─────────────────────────────────────────────────────
① Personality     haven.md (系统人格)     固定，全部纳入
② Agent prompt    haven.yaml agents.     固定，全部纳入
                  {name}.prompt
③ Skills prompt   激活的 Skill .md 文件    剩余预算的 60%
④ Project files   当前工作目录文件列表     ≤500 token
⑤ History         FactStore 长期记忆      剩余预算的最后
```

Token 估算规则：`len(text) // 3` (context.py:166)

### Message 组织

`BaseAgent.run()` (base.py:158-161)：

```python
msgs = []
if system_prompt:
    msgs.append(SystemMessage(content=system_prompt))
msgs.append(HumanMessage(content=task))

# 多轮对话时，LangGraph checkpointer 自动从 checkpoint 恢复历史 messages
```

### LLM 调用时机

| 场景 | LLM 实例 | 调用方法 |
|------|---------|---------|
| 规划 | 主 LLM (DeepSeek 禁用 thinking) | `structured_llm.ainvoke()` |
| Agent 执行 | 主 LLM (保留 thinking) | `agent.ainvoke()` / `agent.astream_events()` |
| 事实提取 | 辅助 LLM | `self._llm.ainvoke()` |
| 工作流节点 | 主 LLM | `agent.run()` |

### 模型支持

```python
# src/haven/core/llm.py
provider == "deepseek"  → ChatDeepSeek(model, api_key, api_base, temperature, max_tokens)
provider == "openai"    → ChatOpenAI(model, api_key, base_url, temperature, max_tokens)
provider == "aliyun"    → ChatOpenAI(model, api_key, base_url, temperature, max_tokens)
```

API Key 通过 `models.yaml` 的 `api_key_env` 字段声明环境变量名，`loader.py:get_model_config()` 从 `os.environ` 动态读取——**Key 不硬编码**。

### Streaming 处理

```
BaseAgent.astream()  (base.py:179-221)
  │
  └── agent.astream_events({"messages": msgs}, config=config)
        │
        ├── event: "on_chat_model_stream"
        │     → chunk.content (token 文本)
        │     → 经 _sanitize() 处理非法 surrogate 字符
        │     → yield StreamChunk(kind="text", content=token)
        │
        ├── event: "on_tool_start"
        │     → yield StreamChunk(kind="status", content="调用工具: {name}")
        │
        └── event: "on_tool_end"
              → yield StreamChunk(kind="status", content="工具完成: {name}")
```

向上游传递：
```
Agent → Dispatcher → Runtime → CLI
  StreamChunk 逐级 yield，每层可能添加额外的 status/plan chunk
```

---

## 第十部分：Session 流程

### 创建

Session 在 `create_runtime()` 时隐式创建：

```python
state = RuntimeState()
state.session_id = session_id  # 默认 "default"
state.entity_name = entity_name  # 默认 "user"
state.channel = channel  # "cli" / "feishu" / "tcp"
```

`session_id` 用作 LangGraph checkpointer 的 `thread_id`——这意味着**同一 session 内的所有 Agent 调用共享同一个对话线程**。

### 维护上下文

```
Agent 每次 run()/astream():
  ├── config["configurable"]["thread_id"] = state.session_id
  ├── LangGraph SqliteSaver 根据 thread_id 自动恢复历史 messages
  ├── 新消息追加到同一 thread
  └── SqliteSaver 自动持久化

工作流节点:
  ├── 每个节点使用独立的 thread_id = uuid4()
  └── 防止节点间的 ReAct 历史互相污染
```

### 结束

```
runtime.reset_session()  (factory.py:101):
  ├── state.reset_turn()  (清零 turn_count)
  ├── agent.reset()  (清零 turn_count)
  └── checkpointer.adelete_thread(session_id)
        └── 删除该 session 的全部对话历史

/clear 命令 → runtime.reset_session()
/exit 命令 → 退出 REPL → runtime.close()
```

### 关联 Memory

Session 通过 `entity_name` 字段关联长期记忆。同一 entity 的所有 session 共享同一个 FactStore 的事实集合。`entity_name` 默认是 `"user"`，可以在 `create_runtime()` 时指定（如不同的用户 ID）。

---

## 第十一部分：Config 体系

### 配置来源（优先级由低到高）

```
1. src/haven/config/haven.yaml     ← 框架内置默认值
2. CWD/haven.yaml                   ← 用户覆盖 (OmegaConf deep-merge)
3. 环境变量                         ← 最高优先级 (pydantic-settings Field alias)
```

### 配置清单

| 配置域 | 文件 | 加载方式 |
|--------|------|---------|
| Agent 参数 | haven.yaml `agent:` | pydantic-settings |
| 4个专业 Agent 的 prompt | haven.yaml `agents:` | OmegaConf → factory.py |
| Context token 预算 | haven.yaml `context:` | pydantic-settings |
| Web Search 引擎 | haven.yaml `web_search:` | pydantic-settings |
| RAG 参数 | haven.yaml `rag:` | pydantic-settings (但未被代码使用) |
| MCP 开关 | haven.yaml `mcp:` | pydantic-settings |
| 守护进程配置 | haven.yaml `daemon:` | pydantic-settings |
| Memory 开关/路径 | haven.yaml `memory:` | pydantic-settings |
| Skill 目录 | haven.yaml `skill:` | pydantic-settings |
| **模型定义** | models.yaml | loader.py 动态读取 env 变量 |
| **MCP 服务器** | CWD/mcp.json | mcp.py 手动解析 |
| **系统人格** | src/haven/config/haven.md | context.py 手动读取 |
| **用户 Skill** | CWD/skills/*.md | SkillLoader 手动加载 |

### 配置传递路径

```
settings (全局单例)
  │
  ├── factory.py:    创建 Runtime 时直接读取 settings.xxx
  ├── base.py:       Agent 读取 settings.agent_max_iterations / agent_max_execution_time
  ├── context.py:    ContextBuilder 读取 settings.context_window_tokens
  ├── loader.py:     ToolLoader 读取 settings.mcp_enabled
  └── mcp.py:        get_mcp_config() 桥接函数，解耦 settings 与 mcp 子模块
```

### 模型配置特殊处理

`models.yaml` 定义模型的 `api_key_env` 字段，`loader.py:get_model_config()` 从 `os.environ` 动态读取 API Key。**Key 不硬编码在配置文件中**，仅声明环境变量名。

---

## 第十二部分：模块依赖关系

```
                            ┌─────────────────┐
                            │   CLI / Channel  │
                            │  (repl, feishu)  │
                            └────────┬────────┘
                                     │ 依赖
                            ┌────────▼────────┐
                            │    Runtime       │
                            │   (factory.py)   │
                            └────────┬────────┘
                                     │ 依赖
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
     ┌────────▼────────┐   ┌────────▼────────┐   ┌────────▼────────┐
     │   Coordinator   │   │   Dispatcher    │   │   BaseAgent×4   │
     │   (coordinator) │   │   (dispatcher)  │   │   (agents/base) │
     └────────┬────────┘   └────────┬────────┘   └────────┬────────┘
              │                      │                      │
              │              ┌───────┼───────┐              │
              │              │       │       │              │
              │      ┌───────▼──┐ ┌──▼───┐ ┌─▼────────┐   │
              │      │ Context  │ │Skill │ │ Workflow │   │
              │      │ Builder  │ │Regis.│ │ Registry │   │
              │      └──────────┘ └──┬───┘ └──────────┘   │
              │                     │                      │
              │              ┌──────▼──────┐               │
              │              │  FactStore  │               │
              │              └─────────────┘               │
              │                                           │
              │                          ┌────────────────▼────────┐
              └──────────────────────────┤      ToolLoader          │
                                         │  (Builtin + MCP + Reg.)  │
                                         └────────────────┬─────────┘
                                                          │
                                                   ┌──────▼──────┐
                                                   │    LLM      │
                                                   │ (DeepSeek/  │
                                                   │  OpenAI)    │
                                                   └─────────────┘

                            基础设施层 (被所有模块依赖)
                   ┌────────────────────────────────────┐
                   │  Settings  │  Config YAML  │  State │
                   │  Core Reg. │  StreamChunk  │  日志  │
                   └────────────────────────────────────┘
```

**依赖规则**：
- 所有模块都依赖 `config/` (settings)
- `runtime/` 依赖 `skills/`、`memory/`、`tools/`、`core/`
- `cli/` 依赖 `runtime/`
- `skills/` 独立，仅依赖 `core/registry.py`
- `memory/` 独立，仅依赖 `core/` 和外部 LLM
- **无循环依赖**

---

## 第十三部分：时序图

```
User          CLI/REPL        Runtime         Coordinator       Dispatcher        Agent/LLM       MemoryPipeline
 │               │               │                 │                 │                │                │
 │ "调研..."     │               │                 │                 │                │                │
 │──────────────▶│               │                 │                 │                │                │
 │               │ execute_      │                 │                 │                │                │
 │               │ stream(task)  │                 │                 │                │                │
 │               │──────────────▶│                 │                 │                │                │
 │               │               │ plan(task)      │                 │                │                │
 │               │               │────────────────▶│                 │                │                │
 │               │               │                 │ _is_trivial → F│                │                │
 │               │               │                 │ _llm_plan()    │                │                │
 │               │               │                 │ LLM(structured)│                │                │
 │               │               │                 │───────────────▶│ (LLM call)     │                │
 │               │               │                 │◀───────────────│                │                │
 │               │               │                 │ resolve_deps() │                │                │
 │               │               │                 │ _validate()    │                │                │
 │               │               │◀────────────────│                │                │                │
 │               │               │ ExecutionPlan   │                │                │                │
 │               │               │                 │                │                │                │
 │               │ yield plan    │                 │                │                │                │
 │               │◀──────────────│                 │                │                │                │
 │  [plan展示]   │               │                 │                │                │                │
 │◀──────────────│               │                 │                │                │                │
 │               │               │ dispatch_stream(│plan, task)     │                │                │
 │               │               │────────────────────────────────▶│                │                │
 │               │               │                 │                │ 路径选择       │                │
 │               │               │                 │                │ (workflow)     │                │
 │               │               │                 │                │                │                │
 │               │               │                 │                │ build_graph()  │                │
 │               │               │                 │                │ ainvoke(state) │                │
 │               │               │                 │                │───────────────▶│                │
 │               │               │                 │                │                │                │
 │               │               │                 │                │                │ [工作流执行]   │
 │               │               │                 │                │                │ searcher →     │
 │               │               │                 │                │                │ analyst →      │
 │               │               │                 │                │                │ synthesizer    │
 │               │               │                 │                │                │                │
 │               │               │                 │                │ yield text     │                │
 │               │               │◀────────────────────────────────│◀───────────────│                │
 │               │ yield text    │                 │                │                │                │
 │               │◀──────────────│                 │                │                │                │
 │  [流式输出]   │               │                 │                │                │                │
 │◀──────────────│               │                 │                │                │                │
 │               │               │                 │                │                │                │
 │               │               │ _trigger_memory(│task, result)   │                │                │
 │               │               │──────────────────────────────────────────────────────────────────▶│
 │               │               │                 │                │                │  after_turn()  │
 │               │               │                 │                │                │  (后台异步)    │
```

---

## 第十四部分：生命周期分析

### 全局唯一 (Process 级)

| 对象 | 创建位置 | 销毁 | 说明 |
|------|---------|------|------|
| `settings` | settings.py:125 (模块导入时) | 进程结束 | pydantic-settings 单例 |
| `SkillRegistry._items` | Registry 基类 (类变量) | 进程结束 | 所有 Skill 的注册表 |
| `WorkflowRegistry._items` | Registry 基类 (类变量) | 进程结束 | 所有 Workflow 的注册表 |
| `ToolRegistry` | ToolLoader.__init__() | 进程结束 | 全局工具注册表 |
| `logging` root | main.py:18 | 进程结束 | Python 内建日志系统 |

### Session 级

| 对象 | 生命周期 | 说明 |
|------|---------|------|
| `Runtime` | 进程存活期间 | 单例容器 |
| `RuntimeState` | 与 Runtime 同生命 | session_id/entity_name 固定，turn_count 累计 |
| `Coordinator` | 与 Runtime 同生命 | `_plan_cache` 跨对话轮次共享 (128 条) |
| `Dispatcher` | 与 Runtime 同生命 | 持有 agents 引用 |
| `BaseAgent ×4` | 与 Runtime 同生命 | 内部 LangGraph Agent 可重建 (模型切换时) |
| `AsyncSqliteSaver` | 与 Runtime 同生命 | checkpoint.db 持久化，进程重启后仍可用 |
| `FactStore` | 与 Runtime 同生命 | memory.db 持久化，跨进程存活 |
| `ToolLoader` | 与 Runtime 同生命 | MCP 连接保持 |

### Request 级 (每次对话)

| 对象 | 创建 | 销毁 | 说明 |
|------|------|------|------|
| `ExecutionPlan` | `coordinator.plan()` | GC | 可能被缓存复用 |
| `BuildResult` | `context_builder.build()` | GC | system_prompt + token 统计 |
| `system_prompt` (str) | Dispatcher 构建 | GC | 作为 SystemMessage 注入 |
| 工作流 state dict | `_make_workflow_state()` | GC | 工作流执行期间的临时状态 |
| 工作流节点 `thread_id` | `uuid.uuid4()` | checkpoint 中 | 每个工作流节点独立 |

### 临时对象

| 对象 | 说明 |
|------|------|
| `StreamChunk` | 流式输出的单次数据，用完即弃 |
| `HumanMessage` / `SystemMessage` | 每轮对话创建新实例 |
| LangGraph agent events | `astream_events` 的迭代器产物 |
| 工作流内部消息列表 | 各节点的 `messages` 字段 |

---

## 第十五部分：最终总结

### ① 项目总体架构图

```
┌─────────────────────────────────────────────────────────┐
│                     INTERFACE                           │
│     CLI REPL (Rich)  │  Feishu WS  │  Daemon (TCP)     │
└─────────────────────────┬───────────────────────────────┘
                          │ execute() / execute_stream()
┌─────────────────────────▼───────────────────────────────┐
│                      RUNTIME                            │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────────┐  │
│  │ Coordinator │  │ Dispatcher  │  │  BaseAgent ×4  │  │
│  │  plan(task) │─▶│dispatch(plan│─▶│  run/astream   │  │
│  │  → Plan     │  │  3路径      │  │  → LLM+Tools   │  │
│  └─────────────┘  └──────┬──────┘  └───────┬────────┘  │
│                          │                  │           │
│         ┌────────────────┼──────────────────┤           │
│         ▼                ▼                  ▼           │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────┐  │
│  │ContextBuild│  │WorkflowReg │  │   ToolLoader     │  │
│  │5级优先级   │  │dev/res/diag│  │ Builtin + MCP    │  │
│  └─────┬──────┘  └────────────┘  └──────────────────┘  │
│        │                                                │
└────────┼────────────────────────────────────────────────┘
         │
┌────────▼────────────────────────────────────────────────┐
│                     MEMORY                              │
│  MemoryPipeline → FactExtractor(辅助LLM) → FactStore    │
│                          (后台异步)         (SQLite)     │
└─────────────────────────────────────────────────────────┘
```

### ② 项目运行流程图

```
用户输入
    │
    ▼
create_runtime()  ← 启动时执行一次
    │
    ├─ 加载 Skills (haven.md + CWD/skills/*.md)
    ├─ 加载 LLM (models.yaml → ChatDeepSeek/ChatOpenAI)
    ├─ 加载 Tools (BuiltinProvider + MCPProvider)
    ├─ 创建 AsyncSqliteSaver (checkpoint.db)
    ├─ 创建 ContextBuilder + FactStore + MemoryPipeline
    ├─ 创建 BaseAgent×4 (coder/researcher/diagnosis/general)
    ├─ 注册 Workflow×3 (dev/research/diagnosis)
    ├─ 创建 Coordinator + Dispatcher
    └─ 返回 Runtime
            │
            ▼
    [REPL 循环]
            │
    用户输入 "任务"
            │
            ▼
    Coordinator.plan("任务")
            │
            ├─ 快速路径 (问候语) → 跳过 LLM
            ├─ 缓存命中 → 复用计划
            └─ LLM 规划 → ExecutionPlan
            │
            ▼
    Dispatcher.dispatch(plan, task)
            │
            ├─ Path 1: Workflow → WorkflowRegistry.build() → DAG 执行
            ├─ Path 2: Multi-step → 拓扑排序 → 逐步 agent.run()
            └─ Path 3: Direct → agent.run() → LLM + Tools
            │
            ▼
    BaseAgent.run() / astream()
            │
            ├─ _repair_checkpoint() → 修复孤儿 tool_call
            ├─ 构建 messages [SystemMessage, HumanMessage]
            └─ agent.ainvoke() → LangGraph ReAct 循环
                    │
                    ├─ LLM 推理 → 决定是否调 Tool
                    ├─ 调 Tool → BaseTool.invoke() → 结果回注
                    ├─ LLM 继续推理 → 生成最终回复
                    └─ 超时 (300s) → 终止并返回错误
            │
            ▼
    响应返回给用户
            │
            ▼
    _trigger_memory() → MemoryPipeline (后台异步)
```

### ③ 模块职责说明

| 模块 | 目录 | 核心职责 |
|------|------|---------|
| **Config** | `config/` | YAML 加载、pydantic-settings、MCP 配置解析 |
| **Core** | `core/` | RuntimeState 状态容器、Registry 基类、LLM 工厂 |
| **Skills** | `skills/` | .md 文件加载、SkillRegistry 注册/查询/依赖解析 |
| **Tools** | `tools/` | ToolLoader + Provider 架构 (Builtin/MCP)、ToolRegistry |
| **Memory** | `memory/` | FactStore (SQLite)、FactExtractor (辅助LLM)、MemoryPipeline |
| **Runtime** | `runtime/` | Coordinator (规划)、Dispatcher (调度)、BaseAgent (执行)、ContextBuilder、WorkflowRegistry、StreamChunk |
| **CLI** | `cli/` | main 入口、REPL 循环、Rich 终端展示 |
| **Services** | `channels/` | 守护进程、飞书 WebSocket 通道 |

### ④ 数据流图

```
user_input (str)
    │
    ├──▶ Coordinator.plan()
    │       │
    │       ├── input:  task (str)
    │       ├── context: Skill菜单 + Workflow菜单
    │       └── output: ExecutionPlan (结构化)
    │
    ├──▶ Dispatcher.dispatch()
    │       │
    │       ├── input:  ExecutionPlan + task
    │       ├── context: Entity facts (FactStore) → skills prompt → system_prompt
    │       └── output: response (str)
    │
    └──▶ MemoryPipeline.after_turn()  [后台异步]
            │
            ├── input:  user_input + agent_response
            ├── process: 辅助LLM提取事实
            └── output: facts → SQLite (memory.db)

流式数据:
    Agent.astream()
        │
        └── StreamChunk(kind="text")     → LLM token
            StreamChunk(kind="status")   → Tool 调用/完成
            StreamChunk(kind="plan")     → 规划摘要
```

### ⑤ 调用链

```
CLI: repl.py:89    runtime.execute_stream(user_input)
    └─ factory.py:83    coordinator.plan(task)
       └─ coordinator.py:137    plan() → _is_trivial | cache | _llm_plan
          └─ coordinator.py:198    _llm_plan() → LLM structured output
    └─ factory.py:89    dispatcher.dispatch_stream(plan, task)
       └─ dispatcher.py:75    dispatch_stream()
          ├─ dispatcher.py:79    workflow path → _execute_via_workflow()
          │  └─ dispatcher.py:176    WorkflowRegistry.build(wf_name)
          │     └─ _helpers.py:27    run_agent_node() per node
          │        └─ base.py:137    agent.run(task, system_prompt)
          │           └─ base.py:164   agent.ainvoke({"messages": msgs})
          ├─ dispatcher.py:89    multi-step path → _execute_steps()
          │  └─ base.py:137    agent.run() per step
          └─ dispatcher.py:119   direct path → agent.astream()
             └─ base.py:199    agent.astream_events({"messages": msgs})
    └─ factory.py:93    _trigger_memory(task, result)
       └─ pipeline.py:44    after_turn(user_input, agent_response)
          └─ extractor.py:89    extract(user_input, agent_response)
             └─ fact_store.py:75    add(entity, content, importance)
```

### ⑥ 时序图

已在第十三部分详细绘制。

### ⑦ 当前架构优点

1. **清晰的三层分离**：Coordinator (规划) → Dispatcher (调度) → BaseAgent (执行)，职责边界明确
2. **组件化装配**：`factory.create_runtime()` 是经典的依赖注入模式，所有依赖显式组装
3. **Skill 零代码扩展**：拖入 .md 文件即可增加领域能力，YAML frontmatter 声明元信息
4. **工具 Provider 架构**：Builtin + MCP 双通道，MCP 支持 stdio/HTTP/WebSocket 三种传输
5. **LangGraph 原生机制复用**：checkpointer (持久化对话)、pre_model_hook (消息裁剪)、astream_events (流式)
6. **配置优先级设计**：内置 YAML < 用户 YAML < 环境变量，符合 12-factor app 原则
7. **后台记忆提取**：长期记忆提取不阻塞主对话流程
8. **孤儿 tool_call 修复**：`_repair_checkpoint()` 处理中断恢复，是务实的健壮性措施
9. **规划缓存**：MD5 缓存计划结果，避免相同输入重复调用 LLM
10. **流式与非流式双模式**：CLI 用流式，Feishu 用非流式，各取所需

### ⑧ 当前架构存在的问题（仅分析，不修改）

1. **StreamChunk 耦合 Runtime 与 UI**：Agent 硬编码中文状态文本 (`"调用工具: {name}"`)，Runtime 决定展示格式，换语言/渠道需改 Runtime 代码
2. **无事件系统**：没有统一的 `AgentEvent` 抽象。Logger、Renderer、Tracer 应该是三个独立消费者，但当前它们无从订阅
3. **工作流不支持流式输出**：`_execute_via_workflow()` 整个执行完才返回结果 (dispatcher.py:82)，LLM token 无法实时输出给用户
4. **多步执行无错误隔离**：`_execute_steps()` 中如果某步 `agent.run()` 抛异常，异常直接传播，前面步骤的输出丢失 (dispatcher.py:220)
5. **工作流使用 MemorySaver**：进程崩溃后工作流状态全部丢失 (workflows/__init__.py:12)，不像 Agent 层有 SQLite 持久化
6. **无连续失败检测**：Coordinator 每次独立规划，不知道"上次也失败了"，无法触发降级策略
7. **FactStore 仅精确文本去重**："用户喜欢 Python" 和 "用户偏好 Python" 会作为两条记录共存
8. **FactStore 仅 LIKE 搜索**：无语义检索，无向量存储（VectorMemory 在 CLAUDE.md 中记录但未实现）
9. **事实无冲突检测**：矛盾事实可以并存（"用户喜欢 Python" vs "用户讨厌 Python"）
10. **RAG 配置未使用**：`settings.rag_*` 字段定义了但无任何 Python 代码读取
11. **WebSearch 引擎配置不一致**：`haven.yaml` 写 `engine: bing`，实际用 DuckDuckGo
12. **无 execution trace**：无法回放一次完整执行过程，无法做性能分析
13. **日志与展示未完全分离**：logger 记录调试信息，但与终端展示无结构化关联（没有统一的 trace_id / span_id）
14. **测试全部损坏**：`tests/` 下 3 个测试文件导入的 V1 模块在 V2 中不存在
15. **无 CI/CD**：无 `.github/` 目录，无 linting 或 pre-commit 配置
16. **版本号不一致**：`pyproject.toml` 声明 `0.1.0`，但代码中硬编码 `"2.0.0"`
17. **无 Web UI 接入能力**：虽然架构上可以通过 Runtime 对接 Web，但 `StreamChunk` 的三固定类型远不足以支撑 Web UI 的展示需求
18. **工具全量绑定**：所有 Agent 共享全部工具，没有按 Agent 类型裁剪工具集（虽然 CLAUDE.md 提到 `app.yaml` 的 `agents.<name>.tools` 配置，但代码中没有实现）

---

## 附录：关键文件索引

| 文件 | 内容 |
|------|------|
| `src/haven/cli/main.py` | 入口，配置 logging，启动 REPL |
| `src/haven/cli/repl.py` | REPL 循环，Rich 终端展示 |
| `src/haven/runtime/factory.py` | `create_runtime()` 工厂，组装所有组件 |
| `src/haven/runtime/coordinator.py` | `Coordinator.plan()`，规划 + 缓存 + 快速路径 |
| `src/haven/runtime/dispatcher.py` | `Dispatcher.dispatch()`，3 条执行路径 |
| `src/haven/runtime/agents/base.py` | `BaseAgent.run()/astream()`，LangGraph 封装 |
| `src/haven/runtime/context.py` | `ContextBuilder.build()`，5 级优先级 prompt 组装 |
| `src/haven/runtime/stream.py` | `StreamChunk` 数据类定义 |
| `src/haven/runtime/registry.py` | `WorkflowRegistry`，工作流注册与构建 |
| `src/haven/runtime/workflows/` | dev/research/diagnosis 三个 DAG 工作流 |
| `src/haven/runtime/workflows/_helpers.py` | `run_agent_node()` 工作流节点执行器 |
| `src/haven/core/state.py` | `RuntimeState` 会话状态 |
| `src/haven/core/registry.py` | `Registry` 基类 |
| `src/haven/core/llm.py` | `create_llm()` LLM 工厂 |
| `src/haven/config/settings.py` | pydantic-settings 全局单例 |
| `src/haven/config/haven.yaml` | 框架内置默认配置 |
| `src/haven/config/mcp.py` | MCP 服务器配置解析 |
| `src/haven/memory/fact_store.py` | `FactStore` SQLite 语义事实存储 |
| `src/haven/memory/extractor.py` | `FactExtractor` 辅助 LLM 事实提取 |
| `src/haven/memory/pipeline.py` | `MemoryPipeline` 记忆提取编排 |
| `src/haven/skills/registry.py` | `SkillRegistry` 注册/查询/依赖解析 |
| `src/haven/skills/base_skill.py` | `BaseSkill` 数据类 |
| `src/haven/tools/loader.py` | `ToolLoader` 工具加载编排 |
| `src/haven/tools/registry.py` | `ToolRegistry` 工具注册表 |
| `src/haven/tools/providers/builtin.py` | `BuiltinProvider` 内置工具扫描 |
| `src/haven/tools/providers/mcp.py` | `MCPProvider` MCP 工具连接 |
| `src/haven/channels/daemon.py` | 守护进程管理 |
| `src/haven/channels/feishu_channel.py` | 飞书 WebSocket 通道 |
