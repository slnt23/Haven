# Haven V3 运行时架构

## 总览

```
╔══════════════════════════════════════════════════════════════════════════╗
║                         HAVEN V3  运行时架构                            ║
╚══════════════════════════════════════════════════════════════════════════╝

                        ┌──────────────┐
                        │   CLI 入口    │  main.py / REPL / --task / serve
                        └──────┬───────┘
                               │
                        ┌──────▼───────┐
                        │ RuntimeService│  CLI ↔ Runtime 唯一桥梁
                        └──────┬───────┘
                               │
                        ┌──────▼───────┐
                        │   factory     │  create_agent()
                        │  系统装配     │
                        └──────┬───────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
   ┌──────▼──────┐   ┌────────▼────────┐   ┌───────▼───────┐
   │   Skills    │   │     Tools        │   │  Middleware   │
   │  .md → Reg  │   │  MCP + Builtin   │   │   Pipeline    │
   └─────────────┘   └─────────────────┘   └───────┬───────┘
                                                   │
                                          ┌────────▼────────┐
                                          │  Personality    │  注入人格 prompt
                                          │  Summarization  │  长对话摘要(预留)
                                          │  Filesystem     │  扫描项目文件
                                          │  Skills         │  注入技能 prompt
                                          └─────────────────┘
                               │
                        ┌──────▼───────┐
                        │ PlannerAgent │  一次 LLM 调用 → ExecutionPlan
                        │  .plan()     │  (intent / skills / workflow / steps)
                        └──────┬───────┘
                               │
               ┌───────────────┼───────────────┐
               │               │               │
        ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────────┐
        │ 路径 1      │ │ 路径 2      │ │ 路径 3           │
        │ 简单对话     │ │ 多步任务     │ │ 匹配工作流        │
        │             │ │             │ │                  │
        │ Runtime     │ │ 拓扑排序     │ │ WorkflowRegistry │
        │ .run() 直通  │ │ 顺序执行     │ │ .build(name)     │
        └──────┬──────┘ └──────┬──────┘ └──────┬──────────┘
               │               │               │
               │               │    ┌──────────▼──────────┐
               │               │    │  StateGraph (DAG)   │
               │               │    │  planner→architect  │
               │               │    │  →coder→reviewer    │
               │               │    │  →tester            │
               │               │    └──────────┬──────────┘
               │               │               │
               └───────────────┼───────────────┘
                               │
                        ┌──────▼───────┐
                        │ AgentRuntime │  执行引擎
                        │              │
                        │ checkpointer │  SqliteSaver ──► checkpoint.db
                        │ pre_model_   │  trim_messages()
                        │   hook       │  ──► 裁剪消息防溢出
                        └──────┬───────┘
                               │
                        ┌──────▼───────┐
                        │  LangGraph   │  create_react_agent()
                        │  ReAct Agent │  LLM ←→ Tool Calling loop
                        └──────┬───────┘
                               │
                        ┌──────▼───────┐
                        │  LLM 响应     │
                        │  checkpointer │  自动持久化本轮消息
                        │  自动保存     │
                        └──────────────┘
```

## 启动时序

```
  main.py
    │
    ├─ REPL 模式          →  RuntimeService.start()
    ├─ --task 模式        →  RuntimeService.run_task()
    └─ serve 模式         →  HavenDaemon.run_forever()
                                 │
                          factory.create_agent()
                            │
                            ├─ ① SkillLoader.load_from_dir()
                            │      └─► SkillRegistry 注册所有 .md skill
                            │
                            ├─ ② AgentRuntime + init_llm()
                            │      ├─ create_llm(model)       → 主 LLM
                            │      └─ create_llm(aux_model)   → 辅助 LLM
                            │
                            ├─ ③ _init_tools(runtime, load_mcp)
                            │      ├─ ToolManager 创建
                            │      ├─ BuiltinProvider 扫描内置工具 (6模块)
                            │      └─ MCPProvider 加载 mcp.json → 连接外部服务
                            │
                            ├─ ④ SqliteSaver(conn)
                            │      └─ .setup() → checkpoint.db 建表
                            │
                            ├─ ⑤ WorkflowRegistry (懒加载)
                            │      └─ graphs/dev|research|diagnosis.py 自注册
                            │
                            ├─ ⑥ MiddlewarePipeline([
                            │        PersonalityMiddleware,
                            │        SummarizationMiddleware,
                            │        FilesystemMiddleware,
                            │        SkillsMiddleware,
                            │      ])
                            │
                            └─ ⑦ PlannerAgent(runtime, workflow_registry)
                                   └─► 返回就绪的 agent
```

## 请求处理时序

以 `"帮我写一个排序算法"` 为例，触发 dev_flow：

```
  用户输入
    │
    ▼
  PlannerAgent.plan(task)
    │
    ├─ _is_trivial() → 否 → 走主路径
    │
    └─ _llm_plan(task)
         ├─ prompt: skill_menu + workflow_menu + task
         ├─ LLM structured_output(ExecutionPlan)
         └─ 返回 { goal, intent, skills, workflow: "dev_flow", steps }
    │
    ▼
  PlannerAgent.execute(task)
    │
    ├─ workflow="dev_flow" → 路径 3
    │     │
    │     ├─ WorkflowRegistry.build("dev_flow")
    │     │     └─► 编译后的 StateGraph (5 节点 DAG)
    │     │
    │     └─ graph.ainvoke(state, config)
    │           ├─ [planner]   → AgentRuntime.run("需求分析...")
    │           ├─ [architect] → AgentRuntime.run("架构设计...")
    │           ├─ [coder]     → AgentRuntime.run("编写代码...")
    │           ├─ [reviewer]  → AgentRuntime.run("代码审查...")
    │           └─ [tester]    → AgentRuntime.run("测试验证...")
    │                              │
    │                    失败? ────┘ (重试 ≤3 次回 coder)
    │
    └─ 返回最终响应
```

## AgentRuntime.run() 内部流程

```
  AgentRuntime.run(task, active_skills, active_tools)
    │
    ├─ ① 初始消息 [HumanMessage(task)]
    │
    ├─ ② 中间件管道 .before(state)
    │      ├─ PersonalityMiddleware  → system_prompt += 人格设定
    │      ├─ SummarizationMiddleware→ (预留)
    │      ├─ FilesystemMiddleware   → system_prompt += 项目文件列表
    │      └─ SkillsMiddleware      → system_prompt += 技能指令
    │
    ├─ ③ 构建 config
    │      { configurable: { thread_id, system_prompt }, recursion_limit }
    │
    ├─ ④ agent.ainvoke({"messages": [HumanMessage(task)]}, config)
    │      │
    │      ├─ checkpointer 加载历史消息 (by thread_id)
    │      │
    │      ├─ pre_model_hook(state, config)
    │      │     ├─ 取 config 中 system_prompt → 前置 SystemMessage
    │      │     └─ trim_messages(messages, max_tokens=8000)
    │      │
    │      └─ ReAct Agent 循环 (最多 max_iterations 轮)
    │            ├─ LLM 推理 → 调用工具 or 回复
    │            └─ 工具结果追加到消息 → 继续循环
    │
    ├─ ⑤ 提取 output = result["messages"][-1].content
    │
    ├─ ⑥ state.turn_count += 1
    │
    └─ ⑦ checkpointer 自动持久化本轮消息 → checkpoint.db
```

## 预定义工作流

### dev_flow — 软件开发

```
  planner → architect → coder → reviewer → tester
                              ▲              │
                              │    fail      │
                              └──────────────┘ (retry ≤ 3)
```

### research_flow — 调研

```
  searcher → analyst ─┬→ synthesizer → END
                 ▲     │
                 │缺口 │
                 └─────┘ (retry ≤ 3)
```

### diagnosis_flow — 诊断

```
  collector → analyzer → adviser → END
```

## 数据存储

```
.data/
├── checkpoint.db    ← SqliteSaver (LangGraph 自动)
│   ├── checkpoints   (按 thread_id 存每轮消息状态)
│   └── writes        (写入记录)
│
├── memory.db        ← FactStore (可选, 按需使用)
│   └── semantic_facts (entity_name, fact_text, importance)
│
├── chroma/          ← VectorMemory (可选, 默认关闭)
│   └── ChromaDB 集合
│
└── haven.pid        ← 守护进程 PID
```

## 模块依赖

```
haven
├── config/      ← OmegaConf YAML + pydantic-settings
├── core/        ← RuntimeState, Registry, create_llm
├── memory/      ← FactStore, VectorMemory, MemoryItem
├── skills/      ← SkillLoader (.md), SkillRegistry
├── tools/       ← ToolManager, BuiltinProvider, MCPProvider
├── middleware/  ← Pipeline, Personality, Summarization, Filesystem, Skills
├── runtime/     ← AgentRuntime, PlannerAgent, factory, graphs/*, WorkflowRegistry
├── cli/         ← main, REPL, RuntimeService
└── services/    ← HavenDaemon, FeishuChannel, TCP, Mail
```

**依赖方向（自上向下）：**

- `cli / services` → `runtime` → `{ skills, tools, middleware, memory, core, config }`
- `graphs/*` → `runtime` (AgentRuntime)
- `memory` → `core` (无循环依赖)
