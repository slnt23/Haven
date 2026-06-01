# Haven V2 UML 参考

> 自动生成于 2026-06-01

---

## 1. 包图

```mermaid
graph TB
    subgraph CLI["cli/"]
        main["main.py<br/>Typer 入口"]
        commands["commands/<br/>chat run doctor<br/>skill tool workflow"]
        ui["ui/<br/>banner console progress"]
    end

    subgraph Runtime["runtime/"]
        factory["factory.py<br/>create_agent()"]
        planner["planner.py<br/>PlannerAgent"]
        agent["runtime.py<br/>AgentRuntime"]
        exec["execution.py<br/>ExecutionState"]
    end

    subgraph Core["core/"]
        context["context.py<br/>ContextManager"]
        prompt["prompt.py<br/>PromptBuilder"]
        llm["llm.py<br/>create_llm bind_tools"]
        state["state.py<br/>RuntimeState"]
        memory_facade["memory.py<br/>AgentMemory"]
        registry["registry.py<br/>Registry"]
    end

    subgraph Memory["memory/"]
        mem_mgr["manager.py<br/>MemoryManager"]
        working["working.py"]
        episodic["episodic.py"]
        semantic["semantic.py"]
        vector["vector.py"]
        mem_base["base.py"]
    end

    subgraph Tools["tools/"]
        tool_mgr["manager.py<br/>ToolManager"]
        resolver["resolver.py<br/>ToolResolver"]
        tool_base["base.py<br/>HavenTool"]
        providers["providers/<br/>BuiltinProvider<br/>MCPProvider"]
    end

    subgraph Skills["skills/"]
        skill_base["base_skill.py<br/>BaseSkill"]
        skill_loader["loader.py<br/>SkillLoader"]
        skill_reg["registry.py<br/>SkillRegistry"]
    end

    subgraph Workflows["workflows/"]
        wf_graph["graph.py<br/>WorkflowGraph"]
        wf_state["state.py<br/>WorkflowState"]
        wf_nodes["nodes.py<br/>WorkflowNode"]
        wf_edges["edges.py<br/>Edge"]
        wf_check["checkpoint.py<br/>Checkpointer"]
        wf_reg["registry.py<br/>WorkflowRegistry"]
        wf_graphs["graphs/<br/>dev research diagnosis"]
    end

    subgraph Services["services/"]
        daemon["daemon.py<br/>HavenDaemon"]
        channels["socket email feishu"]
    end

    subgraph Config["config/"]
        settings["settings.py<br/>Settings"]
        app_yaml["app.yaml<br/>models.yaml"]
    end

    %% CLI → Runtime
    main --> factory
    main --> commands
    commands --> planner

    %% Runtime → Core
    factory --> agent
    factory --> skill_loader
    planner --> agent
    planner --> skill_reg
    planner --> wf_reg
    agent --> context
    agent --> prompt
    agent --> llm
    agent --> memory_facade
    agent --> state
    agent --> tool_mgr
    agent --> resolver
    exec --> state

    %% Core → Memory
    memory_facade --> mem_mgr
    context --> memory_facade
    mem_mgr --> working
    mem_mgr --> episodic
    mem_mgr --> semantic
    mem_mgr --> vector

    %% Tools
    tool_mgr --> providers
    tool_mgr --> tool_base
    resolver --> tool_mgr
    resolver --> skill_reg

    %% Skills
    skill_reg --> registry
    skill_reg --> skill_base
    skill_loader --> skill_base

    %% Workflows
    wf_graph --> wf_state
    wf_graph --> wf_nodes
    wf_graph --> wf_edges
    wf_graph --> wf_check
    wf_state --> exec
    wf_nodes --> skill_reg
    wf_reg --> registry
    wf_graphs --> wf_graph

    %% Services
    daemon --> factory
    daemon --> channels

    %% Config
    settings --> app_yaml
    main --> settings
    agent --> settings

    style CLI fill:#1a1a2e,stroke:#e94560,color:#eee
    style Runtime fill:#1a1a2e,stroke:#e94560,color:#eee
    style Core fill:#16213e,stroke:#0f3460,color:#eee
    style Memory fill:#16213e,stroke:#0f3460,color:#eee
    style Tools fill:#16213e,stroke:#0f3460,color:#eee
    style Skills fill:#16213e,stroke:#0f3460,color:#eee
    style Workflows fill:#16213e,stroke:#0f3460,color:#eee
    style Services fill:#0f3460,stroke:#533483,color:#eee
    style Config fill:#0f3460,stroke:#533483,color:#eee
```

---

## 2. Runtime 类图

```mermaid
classDiagram
    direction TB

    class AgentRuntime {
        -name: str
        -llm: BaseChatModel | None
        -_tools: dict[str, BaseTool]
        -_active_tools: list[BaseTool]
        -memory: AgentMemory
        -state: RuntimeState
        -prompt_builder: PromptBuilder
        -context_manager: ContextManager
        -max_iterations: int
        -_tool_manager: ToolManager
        -_tool_resolver: ToolResolver
        +init_llm(model_name?) BaseChatModel
        +switch_model(model_name) str
        +register_tool(tool) None
        +register_tools(dict) None
        +activate_tools(names) None
        +activate_all_tools() None
        +bind_tools_to_llm() None
        +resolve_tools(skills, permissions) list
        +build_system_prompt(...) str
        +build_messages(task, system_prompt, history) list
        +run(task, **kwargs) str
        -_invoke_direct(llm, messages) str
        -_invoke_with_tool_loop(llm, messages) str
        -_execute_tool(name, args) str
        +save_turn(user, response) None
        +reset() None
    }

    class RuntimeState {
        +session_id: str
        +entity_name: str
        +channel: str
        +active_skills: list[str]
        +active_tools: list[str]
        +turn_count: int
        +current_node: str
        +context: dict[str, str]
        +last_plan: dict | None
        +reset_turn() None
        +snapshot() dict
    }

    class ExecutionState {
        +task_id: str
        +goal: str
        +current_step: str
        +completed_steps: list[str]
        +failed_steps: list[str]
        +step_outputs: dict[str, str]
        +retry_count: int
        +max_retries: int
        +node_retry_counts: dict[str, int]
        +status: str
        +final_output: str
        +errors: list[str]
        +created_at: float
        +updated_at: float
        +start() None
        +complete_step(name, output) None
        +fail_step(name, error) None
        +finish(output) None
        +fail(error) None
        +pause() None
        +resume() None
        +snapshot() dict
        +is_terminal() bool
        +is_running() bool
        +total_steps() int
    }

    class ContextManager {
        -_memory: AgentMemory
        -_assembler: ContextAssembler
        -_extra_collectors: dict
        +build(**kw) ContextBundle
        +collect(**kw) list~ContextItem~
        +assemble(items) str
        +register_collector(source, collector) None
        -_collect_skills(skills, source) list
        -_collect_memory() list
        -_collect_workflow(state) list
        -_collect_tool_results(results) list
        -_collect_rag(rag_context) list
    }

    class ContextAssembler {
        -_budget: TokenBudget
        +assemble(items) str
    }

    class TokenBudget {
        +max_tokens: int
        +estimate(text) int
        +fits(text) bool
    }

    class ContextItem {
        +content: str
        +source: ContextSource
        +priority: int
        +metadata: dict
    }

    class ContextBundle {
        +system_prompt: str
        +items: list~ContextItem~
        +token_usage: int
    }

    class PromptBuilder {
        -_budget: TokenBudget
        +build(context: ContextBundle|str) str
    }

    class AgentMemory {
        +messages: deque~BaseMessage~
        +session_id: str
        +entity_name: str
        +channel: str
        -_manager: MemoryManager
        +manager: MemoryManager
        +add_message(msg) None
        +get_history() list
        +save_message(role, content) None
        +get_long_term_context() str
        +extract_facts(llm) None
        +clear() None
    }

    class BaseChatModel {
        <<LangChain>>
        +ainvoke(messages) Response
        +bind_tools(tools) BaseChatModel
        +with_structured_output(schema) BaseChatModel
    }

    class ToolResolver {
        -_tm: ToolManager
        -_name_index: dict
        -_tag_index: dict
        -_category_index: dict
        +resolve(skills, channel, permissions) ResolveResult
        +invalidate_cache() None
        -_build_index() None
        -_match_one(req) HavenTool
        -_apply_filters(tools) list
    }

    AgentRuntime "1" --> "1" RuntimeState
    AgentRuntime "1" --> "1" AgentMemory
    AgentRuntime "1" --> "1" PromptBuilder
    AgentRuntime "1" --> "1" ContextManager
    AgentRuntime "1" --> "1" BaseChatModel : llm
    AgentRuntime "1" --> "1" ToolResolver : _tool_resolver
    ContextManager "1" --> "1" ContextAssembler
    ContextManager "1" --> "1" AgentMemory : _memory
    ContextAssembler "1" --> "1" TokenBudget
    ContextManager ..> ContextItem : creates
    ContextManager ..> ContextBundle : returns
    PromptBuilder ..> ContextBundle : receives
    PromptBuilder "1" --> "1" TokenBudget
    AgentMemory "1" --> "1" MemoryManager : _manager (lazy)
    WorkflowState "1" --> "1" ExecutionState : execution
```

---

## 3. Planner 类图

```mermaid
classDiagram
    direction TB

    class PlannerAgent {
        -runtime: AgentRuntime
        -_workflow_registry: WorkflowRegistry
        -_plan_cache: dict
        +llm: BaseChatModel
        +plan(task) ExecutionPlan
        +execute(task) str
        -_is_trivial(task) bool
        -_llm_plan(task) ExecutionPlan
        -_validate_plan(plan) ExecutionPlan
        -_execute_via_workflow(plan, task) str
        -_execute_steps(plan, task) str
        -_make_state(wf_name, task) WorkflowState
        -_topological_sort(steps) list
    }

    class ExecutionPlan {
        +goal: str
        +intent: str
        +complexity: str
        +skills: list[str]
        +workflow: str | None
        +steps: list[PlanStep]
        +reasoning: str
    }

    class PlanStep {
        +order: int
        +description: str
        +skill: str | None
        +depends_on: list[int]
        +expected_output: str
    }

    class AgentRuntime {
        +run(task, **kwargs) str
        +init_llm() BaseChatModel
        +build_system_prompt(...) str
        +resolve_tools(skills) list
        +state: RuntimeState
        +memory: AgentMemory
    }

    class SkillRegistry {
        <<Registry>>
        +get(name) BaseSkill
        +list_all() dict
        +get_defaults() dict
        +get_domain_skills() dict
        +resolve_dependencies(selected) list
        +get_selection_context() str
    }

    class WorkflowRegistry {
        <<Registry>>
        +build(name) WorkflowGraph
        +get_selection_context() str
    }

    class WorkflowGraph {
        +run(state, runtime) WorkflowState
        +set_entry_point(name) WorkflowGraph
    }

    class BaseChatModel {
        <<LangChain>>
        +with_structured_output(schema) Runnable
        +ainvoke(messages) Response
    }

    class WorkflowState {
        +task: str
        +session_id: str
        +execution: ExecutionState
    }

    PlannerAgent "1" --> "1" AgentRuntime : runtime
    PlannerAgent "1" --> "1" WorkflowRegistry : _workflow_registry
    PlannerAgent ..> ExecutionPlan : produces
    ExecutionPlan "1" --> "*" PlanStep : steps
    PlannerAgent ..> SkillRegistry : uses
    PlannerAgent ..> WorkflowGraph : executes
    PlannerAgent ..> BaseChatModel : llm
    PlannerAgent ..> WorkflowState : creates
    WorkflowGraph ..> WorkflowState : executes on
```

---

## 4. Tool 类图

```mermaid
classDiagram
    direction TB

    class ToolManager {
        -_providers: dict[str, ToolProvider]
        -_tools: dict[str, HavenTool]
        -_tool_to_provider: dict[str, str]
        -_started: bool
        +add_provider(provider) ToolManager
        +remove_provider(name) None
        +start_all() None
        +stop_all() None
        +refresh_all() None
        +get_tool(name) HavenTool
        +get_tools_for_skills(names) list
        +get_tools_by_names(names) list
        +get_tools_by_tags(tags) list
        +get_tools_by_categories(cats) list
        +get_tools_by_provider(name) list
        +filter_tools(kwargs) list
        +list_all() list
        +list_names() list
        +get_status() dict
        +format_status() str
    }

    class ToolResolver {
        -_tm: ToolManager
        -_cache: dict
        -_name_index: dict
        -_tag_index: dict
        -_category_index: dict
        +resolve(skills, channel, permissions, only_available, use_cache) ResolveResult
        +invalidate_cache() None
        -_build_index() None
        -_collect_requirements(skills) list
        -_match_all(reqs) ResolveResult
        -_match_one(req) HavenTool
        -_pick_best(candidates, req) HavenTool
        -_apply_filters(tools, ...) list
        -_is_available(tool) bool
        -_has_permission(tool, granted) bool
    }

    class ToolProvider {
        <<abstract>>
        +info: ProviderInfo
        -_tools: dict
        +start() None
        +stop() None
        +refresh() None
        +discover()* list~HavenTool~
        +health_check()* bool
        +list_tools() list
        +filter_tools(...) list
    }

    class BuiltinProvider {
        +discover() list~HavenTool~
        +health_check() bool
    }

    class MCPProvider {
        -_config: MCPServerConfig
        -_session: ClientSession
        +discover() list~HavenTool~
        +health_check() bool
    }

    class HavenTool {
        <<LangChain BaseTool>>
        +metadata: ToolMetadata
        +name: str
        +description: str
        +return_direct: bool
        +health_check() bool
        +_run(*args, **kwargs) Any
    }

    class ToolMetadata {
        +provider: str
        +category: ToolCategory
        +permissions: list[ToolPermission]
        +requires_confirmation: bool
        +rate_limit_per_minute: int
        +cost_estimate: str
        +timeout_seconds: int
        +tags: list[str]
        +version: str
    }

    class ToolCategory {
        <<enum>>
        CODE
        FILE
        SEARCH
        KNOWLEDGE
        COMMUNICATION
        SYSTEM
        CUSTOM
    }

    class ToolPermission {
        <<enum>>
        READ
        WRITE
        EXECUTE
        SEND
    }

    class ProviderInfo {
        +name: str
        +type: str
        +description: str
        +version: str
        +tool_count: int
        +status: ProviderStatus
        +last_error: str
    }

    class ProviderStatus {
        <<enum>>
        UNINITIALIZED
        CONNECTING
        CONNECTED
        DEGRADED
        DISCONNECTED
        ERROR
    }

    class ResolveResult {
        +tools: list[HavenTool]
        +unresolved: list[ToolRequirement]
        +warnings: list[str]
        +source_map: dict
        +all_resolved: bool
        +tool_names: list[str]
    }

    class ToolRequirement {
        +raw: str
        +skill_name: str
        +matched: bool
        +resolved_to: str
    }

    class SkillRegistry {
        <<Registry>>
        +get(name) BaseSkill
        +list_all() dict
    }

    ToolManager "1" --> "*" ToolProvider : _providers
    ToolManager "1" --> "*" HavenTool : _tools
    ToolResolver "1" --> "1" ToolManager : _tm
    ToolResolver ..> SkillRegistry : reads skills
    ToolResolver ..> ResolveResult : returns
    ResolveResult "1" --> "*" HavenTool : tools
    ResolveResult "1" --> "*" ToolRequirement : unresolved
    ToolProvider <|-- BuiltinProvider
    ToolProvider <|-- MCPProvider
    BuiltinProvider ..> HavenTool : creates
    MCPProvider ..> HavenTool : creates
    HavenTool "1" --> "1" ToolMetadata : metadata
    ToolMetadata "1" --> "1" ToolCategory : category
    ToolMetadata "1" --> "*" ToolPermission : permissions
    ToolProvider "1" --> "1" ProviderInfo : info
    ProviderInfo "1" --> "1" ProviderStatus : status
```

---

## 5. Memory 类图

```mermaid
classDiagram
    direction TB

    class AgentMemory {
        +messages: deque~BaseMessage~
        +session_id: str
        +entity_name: str
        +channel: str
        -_manager: MemoryManager
        +manager: MemoryManager (lazy)
        +add_message(msg) None
        +get_history() list~BaseMessage~
        +save_message(role, content) None
        +get_long_term_context() str
        +extract_facts(llm) None
        +clear() None
    }

    class MemoryManager {
        +session_id: str
        +entity_name: str
        +channel: str
        +turn_count: int
        +working: WorkingMemory
        +episodic: EpisodicMemory
        +semantic: SemanticMemory
        +vector: VectorMemory | None
        +set_llm(llm) None
        +record_turn(user, assistant) None
        +retrieve(task, top_k) MemoryContext
        +consolidate(llm) dict
        +get_working_messages() list
        +get_working_summary() str
        +get_entity_profile(entity) list
        -_extract_facts(user, assistant) None
        -_estimate_importance(user, assistant) float
    }

    class WorkingMemory {
        +messages: list~BaseMessage~
        +summary: str
        +max_messages: int
        +add_message(msg) None
        +get_messages() list
        +needs_summarization() bool
        +summarize(llm) None
        +retrieve(query, top_k) list~MemoryItem~
        +clear() None
    }

    class EpisodicMemory {
        +_conn: sqlite3.Connection
        +store_turn(session_id, turn, user, assistant, importance) None
        +retrieve(query, top_k, time_range, min_importance, search_mode) list~MemoryItem~
        +consolidate(llm) int
    }

    class SemanticMemory {
        +_conn: sqlite3.Connection
        +store(items) None
        +retrieve(query, top_k, entity_name, min_confidence) list~MemoryItem~
        +retrieve_entity_facts(entity_name) list~MemoryItem~
        +consolidate(llm) int
    }

    class VectorMemory {
        +_collection: ChromaCollection
        +store(items) None
        +retrieve(query, top_k, min_importance) list~MemoryItem~
        +consolidate(llm) int
    }

    class BaseMemory {
        <<abstract>>
        +store(items) None
        +retrieve(query, top_k) list~MemoryItem~
        +consolidate(llm) int
    }

    class MemoryItem {
        +id: str
        +content: str
        +memory_type: str
        +importance: float
        +metadata: dict
    }

    class MemoryContext {
        +working: list~MemoryItem~
        +episodic: list~MemoryItem~
        +semantic: list~MemoryItem~
        +vector: list~MemoryItem~
        +format_for_prompt() str
    }

    AgentMemory "1" --> "1" MemoryManager : _manager
    MemoryManager "1" --> "1" WorkingMemory : working
    MemoryManager "1" --> "1" EpisodicMemory : episodic
    MemoryManager "1" --> "1" SemanticMemory : semantic
    MemoryManager "1" --> "0..1" VectorMemory : vector
    WorkingMemory --|> BaseMemory
    EpisodicMemory --|> BaseMemory
    SemanticMemory --|> BaseMemory
    VectorMemory --|> BaseMemory
    MemoryManager ..> MemoryContext : returns
    MemoryContext "1" --> "*" MemoryItem
    MemoryManager ..> MemoryItem : creates
```

---

## 6. Workflow 类图

```mermaid
classDiagram
    direction TB

    class WorkflowGraph {
        -_state_cls: type[WorkflowState]
        -_nodes: dict[str, Any]
        -_edges: dict[str, Edge|ConditionalEdge]
        -_entry_point: str
        -_checkpointer: Checkpointer
        -_max_iterations: int
        +END: str
        +add_node(name, node) WorkflowGraph
        +add_edge(source, target) WorkflowGraph
        +add_conditional_edge(source, router, route_map) WorkflowGraph
        +set_entry_point(name) WorkflowGraph
        +set_checkpointer(cp) WorkflowGraph
        +run(state, runtime, resume_from) WorkflowState
        -_apply_updates(state, updates) None
        -_final_output(state) str
    }

    class WorkflowState {
        +task: str
        +session_id: str
        +messages: list~BaseMessage~
        +current_node: str
        +node_outputs: dict[str, str]
        +node_retry_counts: dict[str, int]
        +max_retries_per_node: int
        +status: str
        +final_output: str
        +errors: list[str]
        +started_at: float
        +execution: ExecutionState
        -_runtime: AgentRuntime
    }

    class DevWorkflowState {
        +architecture_doc: str
        +source_code: str
        +code_language: str
        +review_feedback: str
        +review_score: float
        +review_blockers: list[str]
        +test_report: str
        +test_passed: bool
        +test_failures: list[str]
    }

    class ResearchWorkflowState {
        +research_topic: str
        +raw_findings: list[str]
        +analyzed_insights: str
        +final_report: str
        +sources: list[str]
    }

    class DiagnosisWorkflowState {
        +symptoms: str
        +collected_info: str
        +possible_causes: str
        +diagnosis: str
        +recommendations: str
    }

    class WorkflowNode {
        <<abstract>>
        +name: str
        +skill_name: str | None
        +max_retries: int
        +__call__(state) dict
        +_build_prompt(state)* str
        +_process_output(output, state) dict
        +_resolve_skills(state, names) list
        +_handle_error(state, exc) dict
    }

    class Edge {
        +source: str
        +target: str
    }

    class ConditionalEdge {
        +source: str
        +router: RouterFunc
        +route_map: dict
        +END: str
        +RETRY: str
        +resolve(state) str
    }

    class Checkpointer {
        <<abstract>>
        +save(session_id, node, state) None
        +load(session_id) dict
    }

    class SQLiteCheckpointer {
        -_conn: sqlite3.Connection
        +save(session_id, node, state) None
        +load(session_id) dict
    }

    class WorkflowRegistry {
        <<Registry>>
        +build(name) WorkflowGraph
        +get_selection_context() str
    }

    WorkflowGraph "1" --> "1" WorkflowState : _state_cls
    WorkflowGraph "1" --> "*" WorkflowNode : _nodes
    WorkflowGraph "1" --> "*" Edge : _edges
    WorkflowGraph "1" --> "0..1" Checkpointer : _checkpointer
    WorkflowState <|-- DevWorkflowState
    WorkflowState <|-- ResearchWorkflowState
    WorkflowState <|-- DiagnosisWorkflowState
    WorkflowState "1" --> "1" ExecutionState : execution
    WorkflowNode ..> WorkflowState : operates on
    WorkflowNode ..> SkillRegistry : _resolve_skills
    Edge <|-- ConditionalEdge
    Checkpointer <|-- SQLiteCheckpointer
    WorkflowRegistry ..> WorkflowGraph : builds

    %% 内置节点
    class PlannerNode {
        +name = "planner"
        +skill_name = "coder"
        +_build_prompt(state) str
    }
    class ArchitectNode {
        +name = "architect"
        +skill_name = "coder"
        +_build_prompt(state) str
        +_process_output(output, state) dict
    }
    class CoderNode {
        +name = "coder"
        +skill_name = "coder"
        +max_retries = 3
        +_build_prompt(state) str
        +_process_output(output, state) dict
    }
    class ReviewerNode {
        +name = "reviewer"
        +skill_name = "code_review"
        +_build_prompt(state) str
        +_process_output(output, state) dict
    }
    class TesterNode {
        +name = "tester"
        +skill_name = "coder"
        +_build_prompt(state) str
        +_process_output(output, state) dict
    }
    class SearcherNode {
        +name = "searcher"
        +skill_name = null
        +_build_prompt(state) str
    }
    class AnalystNode {
        +name = "analyst"
        +skill_name = "data_analysis"
        +_build_prompt(state) str
    }
    class SynthesizerNode {
        +name = "synthesizer"
        +skill_name = "summarization"
        +_build_prompt(state) str
    }
    class CollectorNode {
        +name = "collector"
        +skill_name = "medical"
        +_build_prompt(state) str
    }
    class AnalyzerNode {
        +name = "analyzer"
        +skill_name = "medical"
        +_build_prompt(state) str
    }
    class AdviserNode {
        +name = "adviser"
        +skill_name = "medical"
        +_build_prompt(state) str
    }

    WorkflowNode <|-- PlannerNode
    WorkflowNode <|-- ArchitectNode
    WorkflowNode <|-- CoderNode
    WorkflowNode <|-- ReviewerNode
    WorkflowNode <|-- TesterNode
    WorkflowNode <|-- SearcherNode
    WorkflowNode <|-- AnalystNode
    WorkflowNode <|-- SynthesizerNode
    WorkflowNode <|-- CollectorNode
    WorkflowNode <|-- AnalyzerNode
    WorkflowNode <|-- AdviserNode
```

---

## 7. 系统时序图

```mermaid
sequenceDiagram
    actor User
    participant CLI as CLI<br/>(main.py)
    participant Factory as Factory<br/>(create_agent)
    participant Planner as PlannerAgent
    participant Runtime as AgentRuntime
    participant CtxMgr as ContextManager
    participant Resolver as ToolResolver
    participant ToolMgr as ToolManager
    participant LLM as BaseChatModel<br/>(DeepSeek / OpenAI)
    participant Memory as AgentMemory<br/>→ MemoryManager
    participant WfGraph as WorkflowGraph

    Note over User,WfGraph: ── 初始化阶段 ──

    CLI->>Factory: create_agent(session_id, channel)
    Factory->>Runtime: AgentRuntime()
    Factory->>Memory: session_id / entity_name / channel
    Factory->>Factory: _load_all_skills(runtime) → SkillRegistry
    Factory->>Runtime: init_llm()
    Runtime->>LLM: create_llm(model_name)
    Factory->>ToolMgr: add_provider(BuiltinProvider)
    Factory->>ToolMgr: add_provider(MCPProvider(cfg))
    Factory->>ToolMgr: start_all()
    ToolMgr-->>Factory: tools synced
    Factory->>Runtime: _tool_resolver = ToolResolver(tm)
    Factory->>Runtime: bind_tools_to_llm()
    Factory->>Planner: PlannerAgent(runtime, workflow_registry)
    Factory-->>CLI: planner

    Note over User,WfGraph: ── 执行阶段 ──

    User->>CLI: task input
    CLI->>Planner: planner.execute(task)

    rect rgb(45, 55, 65)
        Note over Planner: Phase 1 — 规划
        Planner->>Planner: _is_trivial(task)?

        alt 非 trivial
            Planner->>LLM: with_structured_output(ExecutionPlan)
            LLM-->>Planner: ExecutionPlan {goal, intent, skills, steps, workflow}
            Planner->>Planner: SkillRegistry.resolve_dependencies(skills)
            Planner->>Planner: _validate_plan(plan)
        else trivial
            Planner->>Planner: fast-path ExecutionPlan
        end
    end

    alt Path 1: 简单对话
        Planner->>Runtime: runtime.run(task, use_memory=True)
        Runtime->>CtxMgr: build(personality_skills=[haven], use_memory=True)
        CtxMgr->>Memory: get_long_term_context()
        Memory-->>CtxMgr: formatted facts
        CtxMgr-->>Runtime: ContextBundle(system_prompt)
        Runtime->>Runtime: build_messages(task, system_prompt)
        Runtime->>LLM: ainvoke([SystemMessage, History, HumanMessage])
        LLM-->>Runtime: response
        Runtime-->>Planner: result
    else Path 2: 多步编排
        Planner->>Planner: _topological_sort(steps)
        loop each step
            Planner->>Resolver: resolve_tools([step.skill], channel)
            Resolver->>ToolMgr: get_tools_by_names/tags/categories
            ToolMgr-->>Resolver: HavenTool list
            Resolver-->>Planner: ResolveResult(tools)
            Planner->>Runtime: runtime.run(step_task, active_skills, tool_results)
            Runtime->>CtxMgr: build(personality, domain, tool_results)
            CtxMgr->>Memory: get_long_term_context()
            CtxMgr-->>Runtime: ContextBundle
            Runtime->>LLM: ainvoke(messages + tool loop)
            LLM-->>Runtime: response
            Runtime-->>Planner: step_output
        end
    else Path 3: 工作流
        Planner->>Planner: WorkflowRegistry.build(wf_name)
        Planner->>Planner: _make_state(wf_name, task)
        Planner->>WfGraph: graph.run(state, runtime)

        rect rgb(65, 45, 55)
            Note over WfGraph: DAG 执行循环
            loop while current != END
                WfGraph->>WfGraph: 获取 node
                WfGraph->>Runtime: node(state) → runtime.run(prompt, skills)
                Runtime->>CtxMgr: build(...)
                Runtime->>LLM: ainvoke()
                LLM-->>Runtime: response
                Runtime-->>WfGraph: output
                WfGraph->>WfGraph: _apply_updates(state, updates)
                WfGraph->>WfGraph: checkpoint.save(state) → SQLite
                WfGraph->>WfGraph: edge.resolve(state) → next_node
            end
        end

        WfGraph-->>Planner: final WorkflowState
    end

    Planner-->>CLI: response text
    CLI-->>User: display result
```

---

## 8. Agent 执行流程图

```mermaid
flowchart TD
    START([用户输入 task]) --> FACTORY[Factory.create_agent<br/>装配 Runtime + Skills + Tools + Planner]

    FACTORY --> INPUT{CLI 命令?}

    INPUT -->|chat| REPL[REPL 循环]
    INPUT -->|run| SINGLE[单任务]
    INPUT -->|serve| DAEMON[守护进程<br/>多通道监听]

    REPL --> PLAN
    SINGLE --> PLAN
    DAEMON --> PLAN

    PLAN[PlannerAgent.plan<br/>LLM Structured Output] --> TRIVIAL{_is_trivial?}

    TRIVIAL -->|Yes| FAST[快速路径<br/>intent=chat, skills=[]]
    TRIVIAL -->|No| LLM_PLAN[LLM 生成 ExecutionPlan<br/>goal + intent + skills + steps + workflow]

    LLM_PLAN --> VALIDATE[_validate_plan<br/>过滤无效 skill<br/>SkillRegistry.resolve_dependencies]

    FAST --> DISPATCH
    VALIDATE --> DISPATCH{分派路径}

    DISPATCH -->|steps=[]<br/>简单对话| PATH1[路径 1: Runtime 直通]
    DISPATCH -->|steps>0<br/>workflow=null| PATH2[路径 2: 多步编排]
    DISPATCH -->|workflow!=null| PATH3[路径 3: Workflow DAG]

    subgraph Runtime_Execution["AgentRuntime.run()"]
        direction TB

        BUILD_CTX[ContextManager.build<br/>收集 6 源上下文] --> ASSEMBLE[ContextAssembler.assemble<br/>按优先级 + token 预算裁剪]
        ASSEMBLE --> BUILD_MSG[build_messages<br/>SystemPrompt + History + HumanMessage]
        BUILD_MSG --> HAS_TOOLS{active_tools > 0?}

        HAS_TOOLS -->|No| DIRECT[_invoke_direct<br/>LLM.ainvoke → 直接返回]
        HAS_TOOLS -->|Yes| TOOL_LOOP[_invoke_with_tool_loop]

        subgraph Tool_Loop["工具调用循环 (≤ max_iterations)"]
            LLM_CALL[LLM.ainvoke] --> CHECK_TC{tool_calls?}
            CHECK_TC -->|No| RETURN[返回最终文本]
            CHECK_TC -->|Yes| EXEC_TOOLS[_execute_tool<br/>按名查找 + ainvoke]
            EXEC_TOOLS --> APPEND[追加 ToolMessage]
            APPEND --> INCR{iteration < max?}
            INCR -->|Yes| LLM_CALL
            INCR -->|No| RETURN
        end

        DIRECT --> SAVE[memory.record_turn]
        RETURN --> SAVE
    end

    PATH1 --> BUILD_CTX

    PATH2 --> SORT[_topological_sort<br/>按依赖拓扑排序]
    SORT --> STEP_LOOP{遍历每个 step}
    STEP_LOOP --> RESOLVE[ToolResolver.resolve<br/>5 级工具匹配]
    RESOLVE --> BUILD_CTX
    SAVE --> STEP_LOOP
    STEP_LOOP -->|完成| DONE

    PATH3 --> MAKE_STATE[_make_state<br/>DevWorkflowState / ResearchWorkflowState / ...]

    subgraph DAG_Engine["WorkflowGraph.run()"]
        direction TB
        WF_START[es.start()] --> WF_LOOP{current ≠ END?}

        WF_LOOP -->|Yes| GET_NODE[node = _nodes[current]]
        GET_NODE --> EXEC_NODE[node(state) → runtime.run()]
        EXEC_NODE --> APPLY[_apply_updates<br/>execution.* + state.*]
        APPLY --> CKPT[checkpoint.save<br/>state + execution_json]
        CKPT --> GET_EDGE[edge = _edges[current]]
        GET_EDGE --> EDGE_TYPE{edge type?}

        EDGE_TYPE -->|Edge| NEXT[target]
        EDGE_TYPE -->|ConditionalEdge| ROUTER[router(state)]

        ROUTER -->|RETRY| RETRY_CHECK{retries < max?}
        RETRY_CHECK -->|Yes| EXEC_NODE
        RETRY_CHECK -->|No| WF_FAIL[es.fail()]

        ROUTER -->|END| WF_END[es.finish()]
        ROUTER -->|node| NEXT

        NEXT --> WF_LOOP
        WF_LOOP -->|No| WF_END

        WF_FAIL --> WF_DONE[return state]
        WF_END --> WF_DONE
    end

    MAKE_STATE --> WF_START
    WF_DONE --> DONE

    DONE[最终结果] --> RESPONSE([返回用户])
```

---

## 附录: 关键状态机

### Provider 状态机

```mermaid
stateDiagram-v2
    [*] --> UNINITIALIZED
    UNINITIALIZED --> CONNECTING : start()
    CONNECTING --> CONNECTED : discover() 成功
    CONNECTING --> ERROR : 异常
    CONNECTED --> DEGRADED : refresh() 失败
    CONNECTED --> DISCONNECTED : stop()
    DEGRADED --> CONNECTED : refresh() 成功
    DEGRADED --> ERROR : 持续失败
    ERROR --> CONNECTING : retry
    ERROR --> DISCONNECTED : stop()
    DISCONNECTED --> [*]
```

### ExecutionState 状态机

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> running : start()
    running --> completed : finish()
    running --> failed : fail()
    running --> paused : pause()
    paused --> running : resume()
    completed --> [*]
    failed --> [*]
```

### ToolResolver 5 级匹配

```mermaid
flowchart LR
    REQ[Skill.tools 声明] --> L1{Level 1<br/>精确名称匹配}
    L1 -->|命中| DONE[返回 HavenTool]
    L1 -->|未命中| L2{Level 2<br/>MCP 命名空间<br/>provider__tool}
    L2 -->|命中| DONE
    L2 -->|未命中| L3{Level 3<br/>标签匹配<br/>tool.metadata.tags}
    L3 -->|命中| PICK[_pick_best<br/>builtin 优先]
    L3 -->|未命中| L4{Level 4<br/>类别匹配<br/>ToolCategory 值}
    L4 -->|命中| PICK
    L4 -->|未命中| L5{Level 5<br/>能力关键词<br/>code→CODE, file→FILE...}
    L5 -->|命中| PICK
    L5 -->|未命中| UNRES[记入 unresolved]

    PICK --> FILTER[_apply_filters<br/>availability + permissions + channel]
    FILTER --> DONE
```
