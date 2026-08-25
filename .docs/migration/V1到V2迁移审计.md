# V1 → V2 迁移审计报告

> 日期: 2026-06-13
> 状态: 仅分析，不修改代码

---

## 第一部分：文件清单与分类

### agent/

| 文件 | 作用 | 类别 |
|------|------|------|
| `agent/__init__.py` | 导出 Agent / AgentFactory / AgentRegistry | **V2** |
| `agent/base.py` | LangChain `create_agent` 封装 | **V2** |
| `agent/factory.py` | AgentFactory + AgentRegistry | **V2** |

### capability/

| 文件 | 作用 | 类别 |
|------|------|------|
| `capability/__init__.py` | 导出 CapabilityRegistry / CapabilityLoader 等 | **V2** |
| `capability/models.py` | Capability ABC + Tool + Skill | **V2** |
| `capability/registry.py` | 统一 CapabilityRegistry | **V2** |
| `capability/resolver.py` | DependencyResolver | **V2** |
| `capability/loader.py` | CapabilityLoader + SkillLoader | **V2** |
| `capability/skills/__init__.py` | 空包标记 | **V2** |
| `capability/tools/__init__.py` | 空包标记 | **V2** |
| `capability/tools/builtin/__init__.py` | 空包标记 | **V2** |
| `capability/tools/builtin/web_search.py` | WebSearchTool (LangChain BaseTool) | **V2** |
| `capability/tools/providers/__init__.py` | 空包标记 | **V2** |
| `capability/tools/providers/base.py` | ToolProvider ABC | **V2** |
| `capability/tools/providers/builtin.py` | BuiltinProvider | **V2** |
| `capability/tools/providers/mcp.py` | MCPProvider | **V2** |

### config/

| 文件 | 作用 | 类别 |
|------|------|------|
| `config/__init__.py` | 导出新旧 API（并存的过渡态） | **V1+V2混合** |
| `config/loader.py` | ConfigLoader + 旧兼容函数(get_model_config等) | **V1+V2混合** |
| `config/mcp.py` | MCP 配置解析 | **V2** |
| `config/schema.py` | AppConfig / ModelConfig Pydantic 模型 | **V2** |
| `config/settings.py` | _SettingsProxy 兼容层 → 委托给 AppConfig | **V1兼容层** |

### core/

| 文件 | 作用 | 类别 |
|------|------|------|
| `core/__init__.py` | 导出 create_llm | **V1兼容层** |
| `core/llm.py` | 旧 LLM 工厂，委托给 ModelFactory | **V1兼容层** |
| `core/pidfile.py` | PID 文件管理（仅 daemon 使用） | **V1** |

### execution/

| 文件 | 作用 | 类别 |
|------|------|------|
| `execution/__init__.py` | 导出 Executor / Planner / Pipeline 等 | **V2** |
| `execution/executor.py` | 统一执行入口 | **V2** |
| `execution/pipeline.py` | 三条执行路径 | **V2** |
| `execution/planner.py` | LangGraph 规划器 | **V2** |
| `execution/request.py` | ExecutionRequest / ExecutionPlan | **V2** |
| `execution/response.py` | ExecutionResponse | **V2** |
| `execution/state.py` | ExecutionState | **V2** |

### infrastructure/

| 文件 | 作用 | 类别 |
|------|------|------|
| `infrastructure/__init__.py` | 空 | **V2** |
| `infrastructure/types.py` | StreamChunk | **V2** |

### interface/

| 文件 | 作用 | 类别 |
|------|------|------|
| `interface/__init__.py` | 空 | **V2** |
| `interface/cli/main.py` | CLI 入口 | **V2** |
| `interface/cli/repl.py` | REPL 循环 | **V2** |
| `interface/cli/__init__.py` | 空 | **V2** |
| `interface/channels/__init__.py` | 导出 BaseChannel / FeishuChannel | **V2** |
| `interface/channels/base.py` | BaseChannel ABC | **V2** |
| `interface/channels/feishu.py` | 飞书 WebSocket | **V2** |
| `interface/daemon.py` | 守护进程 | **V1** (docstring 引用已删除的 Coordinator) |
| `interface/http_server.py` | HTTP API | **V2** |

### kernel/

| 文件 | 作用 | 类别 |
|------|------|------|
| `kernel/__init__.py` | 导出 Event / TraceContext / Errors 等 | **V2** |
| `kernel/callbacks.py` | HavenCallbackHandler | **V2** |
| `kernel/errors.py` | 异常体系 | **V2** |
| `kernel/event.py` | AgentEvent + EventType | **V2** |
| `kernel/lifecycle.py` | LifecycleManager | **V2** |
| `kernel/trace.py` | TraceContext | **V2** |

### memory/

| 文件 | 作用 | 类别 |
|------|------|------|
| `memory/__init__.py` | 导出 V2 API + MemoryPipeline 别名 | **V2** (含一个兼容别名) |
| `memory/base.py` | MemoryItem | **V2** |
| `memory/extractor.py` | FactExtractor (LLM 事实提取) | **V2** |
| `memory/fact_store.py` | FactStore (SQLite 语义事实) | **V2** |
| `memory/manager.py` | MemoryManager (统一入口) | **V2** |
| `memory/pipeline.py` | MemoryPipeline (旧实现, 无人引用) | **V1** (Dead Code) |
| `memory/vector_memory.py` | VectorMemory (ChromaDB) | **V2** |
| `memory/conflict_resolver.py` | ConflictResolver | **V2** |

### model/

| 文件 | 作用 | 类别 |
|------|------|------|
| `model/__init__.py` | 导出 LLMClient / ModelFactory | **V2** |
| `model/llm.py` | LLMClient + ModelFactory | **V2** |

### runtime/

| 文件 | 作用 | 类别 |
|------|------|------|
| `runtime/__init__.py` | 聚合导出（从各 V2 模块 re-export） | **V2** |
| `runtime/context.py` | ContextBuilder (+ Channel-Aware Response) | **V2** |
| `runtime/factory.py` | Runtime 容器 + create_runtime() 装配 | **V2** |

### session/

| 文件 | 作用 | 类别 |
|------|------|------|
| `session/__init__.py` | 导出 Session / SessionState / SessionManager | **V2** |
| `session/manager.py` | SessionManager | **V2** |
| `session/models.py` | Session + SessionState | **V2** |

### workflow/

| 文件 | 作用 | 类别 |
|------|------|------|
| `workflow/__init__.py` | 导出 AgentState / WorkflowRegistry / WorkflowEngine 等 | **V2** |
| `workflow/engine.py` | WorkflowEngine | **V2** |
| `workflow/helpers.py` | create_checkpointer + run_agent_node | **V2** |
| `workflow/registry.py` | WorkflowRegistry | **V2** |
| `workflow/result.py` | WorkflowResult | **V2** |
| `workflow/state.py` | AgentState TypedDict | **V2** |
| `workflow/definitions/__init__.py` | 注册所有定义 | **V2** |
| `workflow/definitions/dev.py` | 开发工作流 | **V2** |
| `workflow/definitions/diagnosis.py` | 诊断工作流 | **V2** |
| `workflow/definitions/research.py` | 研究工作流 | **V2** |
| `workflow/definitions/triage.py` | 分诊工作流 (NEW) | **V2** |

---

## 第二部分：V1 残留分析

### 已删除的 V1 模块（验证通过）

| 模块 | 状态 | 无引用 |
|------|------|--------|
| `tools/` | 已删除 | ✅ |
| `skills/` | 已删除 | ✅ |
| `middleware/` | 已删除 | ✅ |
| `cli/` | 已删除（迁移到 interface/） | ✅ |
| `channels/` | 已删除（迁移到 interface/） | ✅ |
| `runtime/agents/` | 已删除 | ✅ |
| `runtime/workflows/` | 已删除（迁移到 workflow/） | ✅ |
| `runtime/registry.py` | 已删除 | ✅ |
| `runtime/state.py` | 已删除 | ✅ |
| `runtime/stream.py` | 已删除（迁移到 infrastructure/types.py） | ✅ |
| `runtime/coordinator.py` | 已删除（迁移到 execution/planner.py） | ✅ |
| `runtime/dispatcher.py` | 已删除（迁移到 execution/pipeline.py） | ✅ |
| `core/registry.py` | 已删除 | ✅ |
| `core/state.py` (RuntimeState) | 已删除 | ✅ |

### 现存的 V1 代码

| 文件 | 类型 | 详情 |
|------|------|------|
| `core/llm.py` | **V1兼容层** | 包装 V2 ModelFactory。文档写"Phase 7 后移除"但仍在用。仅 `runtime/factory.py` 引用。 |
| `core/__init__.py` | **V1兼容层** | 仅导出 `create_llm` |
| `core/pidfile.py` | **V1** | 仅 `interface/daemon.py` 引用 |
| `config/settings.py` | **V1兼容层** | `_SettingsProxy` 包装 AppConfig。6 个文件引用。 |
| `config/loader.py` | **V1+V2混合** | 新 `ConfigLoader` + 旧 `get_model_config()`, `get_default_model()`, `load_models_config()` |
| `config/__init__.py` | **V1+V2混合** | 同时导出新旧 API |
| `memory/pipeline.py` | **V1 Dead Code** | `MemoryPipeline` 类，零引用。功能被 `MemoryManager` 完全覆盖。 |

### 过期注释/文档字符串

| 文件 | 行 | 内容 |
|------|-----|------|
| `interface/daemon.py` | 3 | "Runtime 包含 Coordinator（规划）+ Dispatcher（执行）" |
| `interface/daemon.py` | 99 | "创建 Runtime（Coordinator + Dispatcher + Agents + Tools）" |
| `interface/channels/base.py` | 26 | "共享的 Runtime 实例（Coordinator + Dispatcher + Agents + Tools）" |
| `interface/channels/feishu.py` | 93 | "self._session = agent # Coordinator 实例" |
| `execution/planner.py` | 7 | "已删除旧 Coordinator.hardcoded_trivial_set" |

---

## 第三部分：重复实现分析

### 重复 1：MemoryPipeline vs MemoryManager

| 维度 | `memory/pipeline.py` (V1) | `memory/manager.py` (V2) |
|------|--------------------------|--------------------------|
| 类名 | `MemoryPipeline` | `MemoryManager` |
| 入口方法 | `after_turn()` / `clear()` | `after_turn()` / `remember()` / `recall()` / `forget()` |
| 依赖 | FactStore + FactExtractor | FactStore + FactExtractor |
| 引用 | **零引用** | `runtime/factory.py` |
| 区别 | 旧 API（`pipeline.add()` 等） | 新 API（`remember` / `recall` / `forget`） |

**推荐保留**: `MemoryManager`（V2）
**推荐迁移**: 无需迁移（无引用）
**推荐删除**: `memory/pipeline.py`（Dead Code）
**注意**: `memory/__init__.py` 中的 `MemoryPipeline = MemoryManager` 别名保留，确保旧 import 不报错。

### 重复 2：core/llm.py (代理) vs model/llm.py (真实实现)

| 维度 | `core/llm.py` | `model/llm.py` |
|------|--------------|----------------|
| 类名 | `create_llm()` 函数 | `ModelFactory` 类 |
| 实现 | 委托给 `ModelFactory` | 真正的实现 |
| 引用 | 1 处 (`runtime/factory.py`) | `core/llm.py` |
| 文档标注 | "Phase 7 后移除此文件" | — |

**推荐保留**: `model/llm.py`（V2）
**推荐迁移**: `factory.py` 直接使用 `ModelFactory` 替代 `create_llm()`
**推荐删除**: `core/llm.py`、`core/__init__.py`

### 重复 3：config/settings.py (代理) vs config/schema.py + config/loader.py (真实实现)

| 维度 | `config/settings.py` | `config/schema.py` + `config/loader.py` |
|------|---------------------|------------------------------------------|
| 类名 | `_SettingsProxy` → `settings` 单例 | `AppConfig` / `ConfigLoader` |
| 访问方式 | `settings.agent_max_iterations` | `load_config().agent_max_iterations` |
| 兼容 | 扁平化属性 (`daemon_feishu_app_id`) | 嵌套 (`daemon.feishu.app_id`) |
| 引用 | 6 处 | 2 处 (通过 `load_config()`) |

**推荐保留**: `config/schema.py` + `config/loader.py`（V2）
**推荐迁移**: 各文件将 `from haven.config import settings` 改为 `from haven.config import load_config`
**推荐删除**: `config/settings.py`（需要先迁移 6 个引用者）

---

## 第四部分：引用关系

### 需要迁移的引用链

```
settings 单例引用者 (6):
  agent/base.py        → settings.agent_max_iterations
  capability/loader.py  → settings.skill_directory (lazy)
  runtime/factory.py    → settings.memory_enabled, settings.memory_db_path, settings.skill_directory, settings.mcp_enabled
  runtime/context.py    → settings.context_window_tokens
  interface/daemon.py   → settings.daemon_feishu_*
  interface/channels/feishu.py → settings.daemon_feishu_*

create_llm 引用者 (1):
  runtime/factory.py    → create_llm(model_name)

MemoryPipeline (旧 class, 0引用):
  ← 无引用，Dead Code
```

### 无人引用的文件 (Dead Code)

| 文件 | 确认方式 |
|------|---------|
| `memory/pipeline.py` | grep 项目无 `from haven.memory.pipeline` 或 `import MemoryPipeline` |

---

## 第五部分：迁移建议

### 类型 A（可直接迁移）

| 文件 | 建议迁移到 | 原因 |
|------|-----------|------|
| `core/llm.py` → 删除 | `runtime/factory.py` 直接调用 `ModelFactory` | 薄代理层，功能完全被 V2 覆盖 |
| `core/__init__.py` → 删除 | 同上 | 仅导出 `create_llm` |
| `config/loader.py` 旧函数 | 替换为新 API | `get_model_config()` → `AppConfig.models[name]` |

### 类型 B（需要保留，不可删）

| 文件 | 原因 |
|------|------|
| `core/pidfile.py` | `interface/daemon.py` 的唯一 PID 管理实现，无 V2 替代 |
| `config/mcp.py` | MCP 配置解析，无 V2 替代 |
| `execution/` (全部) | V2 核心执行引擎 |
| `agent/` (全部) | V2 Agent 层 |
| `capability/` (全部) | V2 能力层 |
| `session/` (全部) | V2 Session 层 |
| `workflow/` (全部) | V2 工作流层 |
| `interface/` (全部) | V2 用户层 |
| `kernel/` (全部) | V2 基础设施 |
| `model/` (全部) | V2 模型层 |
| `infrastructure/` (全部) | V2 类型层 |
| `memory/` (除 pipeline.py) | V2 记忆层 |

### 类型 C（兼容层，暂不能删）

| 文件 | 价值 | 何时可删 |
|------|------|---------|
| `config/settings.py` | 6 个模块依赖 `settings` 单例 | 6 个模块切换到 `AppConfig` 后 |
| `config/loader.py` (旧 API) | `factory.py` 用 `get_auxiliary_model()` | factory.py 改用 `AppConfig.auxiliary_model` |
| `memory/__init__.py` 的 `MemoryPipeline = MemoryManager` | 确保旧 `from haven.memory import MemoryPipeline` 不报错 | 确认无外部引用后 |

### 类型 D（疑似可删除）

| 文件 | 状态 |
|------|------|
| `memory/pipeline.py` | **【疑似可删除】** 零引用，功能完全被 `memory/manager.py` 覆盖 |
| `capability/skills/__init__.py` | **【疑似可删除】** 空文件，仅包标记 |
| `capability/tools/__init__.py` | **【疑似可删除】** 空文件，仅包标记 |
| `capability/tools/builtin/__init__.py` | **需要保留** — 子包导入需要 |
| `capability/tools/providers/__init__.py` | **需要保留** — 子包导入需要 |
| `interface/__init__.py` | **【疑似可删除】** 空文件，仅标记 |
| `interface/cli/__init__.py` | **需要保留** — 子包导入需要 |

---

## 第六部分：统计

| 类别 | 数量 |
|------|------|
| **总 Python 文件** | 73 |
| **V2 文件** | 59 |
| **V1 文件** | 2 (`core/pidfile.py`, `memory/pipeline.py`) |
| **V1 兼容层** | 3 (`core/llm.py`, `core/__init__.py`, `config/settings.py`) |
| **V1+V2 混合** | 2 (`config/loader.py`, `config/__init__.py`) |
| **重复实现** | 3 组 (`Memory`、`LLM Factory`、`Config Settings`) |
| **Dead Code（确认）** | 1 (`memory/pipeline.py` 的 `MemoryPipeline` 类) |
| **过期注释** | 5 处 (`daemon.py` ×2, `base.py` ×1, `feishu.py` ×1, `planner.py` ×1) |
| **建议迁移数量** | 2 (`core/llm.py` → 删除, `factory.py` 直接用 `ModelFactory`) |
| **建议保留数量** | 60 |
| **建议删除（疑似）** | 1 (`memory/pipeline.py` 确认可删) |

---

## 第七部分：结论

**V2 迁移已非常彻底。** 13 个 V1 模块全部删除，零残留引用。

剩余工作：
1. `core/llm.py` + `core/__init__.py` — 薄代理层，修改 `factory.py` 一处引用后可删
2. `memory/pipeline.py` — 零引用 Dead Code，可直接删除
3. `config/settings.py` — 6 个引用者，迁移后删除 `_SettingsProxy`
4. 5 处过期注释 — 清理 docstring 中的 `Coordinator/Dispatcher` 引用
5. `config/loader.py` 旧兼容函数 — 迁移后精简
