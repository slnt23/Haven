# Haven 工具层架构文档

> 生成日期: 2026-06-07 | Haven v3.0.0

## 一、架构总览

工具层 (`src/haven/tools/`) 采用 **Provider 架构**，将工具发现、生命周期管理与使用分离。核心三件套：`ToolManager` 编排所有 Provider，`ToolResolver` 将 skill 声明解析为具体工具实例，`HavenTool` 是统一的工具基类。

```
                          SkillRegistry
                               │
                        skill.tools = ["web_search", "file_read"]
                               │
                               ▼
                      ┌─────────────────┐
                      │  ToolResolver   │  ← 语义匹配层
                      │ (名称→标签→类别) │
                      └────────┬────────┘
                               │  ResolveResult.tools
                               ▼
                      ┌─────────────────┐
                      │  ToolManager    │  ← 编排层
                      │ (add/start/stop)│
                      └────────┬────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
      ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
      │BuiltinProvider│ │MCPProvider(1)│ │MCPProvider(N)│
      │  (web_search) │ │ (stdio/http) │ │   (...)      │
      └──────────────┘ └──────────────┘ └──────────────┘
```

**数据流：** Skill 声明工具名 → ToolResolver 语义匹配 → ToolManager 按名取实例 → 绑定到 Agent → ReAct 循环中调用

---

## 二、目录结构

```
src/haven/tools/
├── __init__.py              # 公开 API 导出
├── base.py                  # HavenTool — 统一工具基类 + ToolMetadata
├── manager.py               # ToolManager — 工具编排中心
├── resolver.py              # ToolResolver — 语义解析层
├── web_search.py            # WebSearchTool — 内置搜索引擎工具
└── providers/
    ├── __init__.py          # 提供者包导出
    ├── base.py              # ToolProvider — 提供者抽象基类 + 状态机
    ├── builtin.py           # BuiltinProvider — 内置工具提供者
    └── mcp.py               # MCPProvider — MCP 协议提供者
```

---

## 三、核心组件详解

### 3.1 HavenTool (`base.py`)

**职责：** 统一的工具基类，所有工具（内置、MCP 包装）都适配为此类型。继承自 LangChain `BaseTool`，附加 `ToolMetadata`。

#### 枚举类型

```python
class ToolCategory(str, Enum):
    CODE = "code"              # 代码执行
    FILE = "file"              # 文件操作
    SEARCH = "search"          # 搜索/检索
    KNOWLEDGE = "knowledge"    # 知识库
    COMMUNICATION = "communication"  # 消息/通知
    SYSTEM = "system"          # 系统操作
    CUSTOM = "custom"          # 自定义

class ToolPermission(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    SEND = "send"
```

#### ToolMetadata

```python
class ToolMetadata(BaseModel):
    provider: str                    # 所属提供者名称
    category: ToolCategory           # 工具分类
    permissions: list[ToolPermission] # 权限列表
    requires_confirmation: bool = False  # 是否需要用户确认
    rate_limit_per_minute: int = 0   # 每分钟调用限制 (0=不限)
    cost_estimate: float = 0.0       # 单次调用成本估算
    timeout_seconds: int = 60        # 超时时间
    tags: list[str] = []             # 标签列表 (用于语义匹配)
    version: str = "1.0.0"
```

#### HavenTool

```python
class HavenTool(BaseTool):
    metadata: ToolMetadata

    async def health_check(self) -> bool:
        """默认返回 True，子类可覆盖"""
```

每个 HavenTool 既是 LangChain Tool（可被 `llm.bind_tools()` 直接使用），又携带分类/权限/成本等元信息，供 ToolResolver 过滤和匹配。

---

### 3.2 ToolProvider (`providers/base.py`)

**职责：** 工具提供者抽象基类，封装完整的连接生命周期与状态机。

#### 状态机

```
UNINITIALIZED → CONNECTING → CONNECTED
                            → DEGRADED
                            → ERROR
              ┌─────────────────────────┐
              │→ DISCONNECTED (stop后)  │
              └─────────────────────────┘
```

#### ProviderInfo

```python
@dataclass
class ProviderInfo:
    name: str                # 提供者唯一名称
    type: str                # "builtin" | "mcp" | 自定义
    description: str = ""
    version: str = "1.0.0"
    tool_count: int = 0
    status: ProviderStatus = ProviderStatus.UNINITIALIZED
    last_error: str | None = None
```

#### ToolProvider 抽象基类

```python
class ToolProvider(ABC):
    def __init__(self, name: str, provider_type: str = "custom"):
        self.info = ProviderInfo(name=name, type=provider_type)
        self._tools: dict[str, HavenTool] = {}

    # === 生命周期 (子类不应覆盖，覆盖钩子即可) ===
    async def start(self) -> None:
        """启动：设置 CONNECTING → _on_start() → discover() → CONNECTED"""

    async def stop(self) -> None:
        """停止：_on_stop() → 清除工具 → DISCONNECTED"""

    async def refresh(self) -> None:
        """刷新工具列表：重新 discover()，替换 _tools"""

    # === 子类必须实现 ===
    @abstractmethod
    async def discover(self) -> list[HavenTool]:
        """发现并返回该提供者的所有工具"""

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查"""

    # === 可选覆盖的钩子 ===
    async def _on_start(self) -> None: ...
    async def _on_stop(self) -> None: ...

    # === 工具访问 ===
    @property
    def tools(self) -> dict[str, HavenTool]: ...
    def get_tool(self, name: str) -> HavenTool | None: ...
    def list_tools(self) -> list[HavenTool]: ...
    def filter_tools(self, category=None, tag=None) -> list[HavenTool]: ...
```

**设计意图：** `start()/stop()/refresh()` 是模板方法，内部处理状态转换和异常捕获。子类只需实现 `discover()` 和 `health_check()`，无需关心生命周期细节。

---

### 3.3 BuiltinProvider (`providers/builtin.py`)

**职责：** 加载 Python 代码定义的内置工具。`health_check()` 始终返回 `True`（内置工具无外部依赖）。

```python
class BuiltinProvider(ToolProvider):
    def __init__(self, name: str = "builtin"):
        super().__init__(name, "builtin")
```

**工具发现机制 (类变量 `_BUILTIN_MODULES`)：**

```python
_BUILTIN_MODULES: list[tuple[str, str, str]] = [
    ("web_search", "haven.tools.web_search", "WebSearchTool"),
    # 新增内置工具在此添加一行即可
]
```

**`discover()` 流程：**
1. 遍历 `_BUILTIN_MODULES`，动态 `importlib.import_module`
2. 实例化工具类，用 `StructuredTool.from_function(coroutine=instance.__call__)` 包装为 LangChain 工具
3. 附加 `ToolMetadata(provider="builtin", category=..., permissions=[READ], tags=...)`
4. 导入失败静默跳过（单个工具故障不影响其他）

**当前内置工具：**

| 工具 | 类别 | 说明 |
|------|------|------|
| `web_search` | SEARCH | 占位搜索引擎，调用 `web_search.py::WebSearchTool` |

---

### 3.4 MCPProvider (`providers/mcp.py`)

**职责：** 连接 MCP (Model Context Protocol) 服务器，将其工具适配为 HavenTool。

```python
class MCPProvider(ToolProvider):
    def __init__(self, server_config: MCPServerConfig):
        # name = server_config.name
        # provider_type = "mcp"
```

#### 支持的传输方式

| 传输 | 实现 | 适用场景 |
|------|------|----------|
| `stdio` | `StdioServerParameters(command, args, env)` | 本地命令行工具 |
| `http` | SSE (`sse_client(url, headers)`) | 远程 HTTP 服务 |
| `websocket` | `websocket_client(url)` | 双向实时通信 |

**连接流程：**
```
 1. 读取 server_config.transport
 2. 创建对应传输上下文 (AsyncExitStack)
 3. 建立 ClientSession → session.initialize()
 4. langchain_mcp_adapters.tools.load_mcp_tools(session)
 5. 每个原始工具 → _adapt() → HavenTool
```

#### 工具适配 (`_adapt`)

```
原始 LangChain Tool
  → 工具名加命名空间前缀: "{provider_name}__{original_name}"
  → 推断 ToolCategory (_infer_category: 名称/描述关键词匹配)
  → 推断 ToolPermission (_infer_permissions: 含 write/delete 关键词→WRITE)
  → 包装为 _MCPToolWrapper(HavenTool)
```

#### 环境变量解析

MCP 配置中 `env` 字段的值支持 `${VAR}` 语法：
```json
{ "API_KEY": "${MY_API_KEY}" }
```
`_resolve_env()` 自动从 `os.environ` 读取并替换。

#### 内部包装类 `_MCPToolWrapper`

```python
class _MCPToolWrapper(HavenTool):
    def __init__(self, _raw: BaseTool, **kwargs):
        # 保存原始工具，委托调用
    async def _arun(*args, **kwargs):
        # → _raw.ainvoke() 或 _raw._run()
```

**设计意图：** 每个 MCP 服务器是一个独立的 Provider，单服务器故障不影响其他。断开/错误状态通过 Provider 状态机独立管理。

---

### 3.5 ToolManager (`manager.py`)

**职责：** 中心编排点，管理所有 Provider 的生命周期与工具索引。

```python
class ToolManager:
    def __init__(self):
        self._providers: dict[str, ToolProvider] = {}     # name → provider
        self._tools: dict[str, HavenTool] = {}            # name → tool
        self._tool_to_provider: dict[str, str] = {}       # tool_name → provider_name
        self._started: bool = False
```

#### Provider 管理

| 方法 | 说明 |
|------|------|
| `add_provider(provider) -> ToolManager` | 注册提供者，名称冲突抛 ValueError |
| `remove_provider(name)` | 移除提供者及其所有工具 |
| `get_provider(name) -> ToolProvider \| None` | 按名称查找 |
| `list_providers() -> list[ToolProvider]` | 列出所有已注册提供者 |

#### 生命周期

| 方法 | 说明 |
|------|------|
| `async start_all()` | `asyncio.gather` 并行启动所有 Provider，失败不影响其他 |
| `async stop_all()` | 并行停止，清除所有工具索引 |
| `async refresh_all()` | 刷新所有 Provider 工具列表 |

启动策略：逐个 Provider 独立启动 (`_start_one`)，捕获异常记录日志但不阻断。

#### 工具检索 (多维度)

| 方法 | 匹配方式 | 说明 |
|------|----------|------|
| `get_tool(name)` | 精确名称 | 最常用 |
| `get_tools_by_names(names)` | 批量精确名称 | 静默跳过缺失 |
| `get_tools_by_tags(tags)` | OR 语义 | 匹配任一标签 |
| `get_tools_by_categories(categories)` | OR 语义 | 匹配任一分类 |
| `get_tools_by_provider(provider_name)` | 提供者过滤 | 查某个 MCP 服务器的所有工具 |
| `get_tools_for_skills(skill_tools)` | skill→tool 映射 | 已不推荐，请用 ToolResolver |
| `filter_tools(category, tag, provider, only_available)` | 组合过滤 | 多条件 AND |
| `list_all() -> dict[str, HavenTool]` | 全部 | 返回完整工具字典 |
| `list_names() -> list[str]` | 全部名称 | 轻量查询 |

#### 状态展示

```python
def format_status(self) -> str:
    """
    + deepseek     内置工具            [CONNECTED]
    ~ filesystem   文件系统操作        [DEGRADED]
    ! github       GitHub API         [ERROR]
    """
```

符号含义：`+` CONNECTED · `~` DEGRADED · `!` ERROR · `-` DISCONNECTED · `.` CONNECTING

---

### 3.6 ToolResolver (`resolver.py`)

**职责：** Skill 层与 ToolManager 之间的语义解析层。将 skill 中声明的工具需求（字符串列表）解析为具体工具实例。

#### 为什么需要 Resolver？

Skill 声明工具名时可能是非精确匹配（如 "file" vs "filesystem__read_file"），ToolResolver 通过多级匹配找到正确的工具，并施加 channel / 权限 / 可用性过滤。

#### 数据类

```python
@dataclass
class ToolRequirement:
    raw: str              # 原始需求字符串，如 "file_read"
    skill_name: str       # 来自哪个 skill
    matched: bool         # 是否匹配成功
    resolved_to: str      # 解析后的工具名

@dataclass
class ResolveResult:
    tools: list[HavenTool]              # 解析成功的工具实例
    unresolved: list[ToolRequirement]   # 未能解析的需求
    warnings: list[str]                 # 警告信息
    source_map: dict[str, str]          # tool_name → 来源 skill 映射

    @property
    def all_resolved(self) -> bool: ...
    @property
    def tool_names(self) -> list[str]: ...
```

#### 匹配优先级 (4 级降级)

```
输入: "file_read"
  │
  ├─ 1. 精确名称匹配 → self._name_index["file_read"]
  │    命中条件: ToolManager 中存在同名工具
  │
  ├─ 2. 标签匹配 → self._tag_index["file_read"]
  │    命中条件: 工具的 tags 列表中包含该字符串
  │
  ├─ 3. 类别匹配 → self._category_index[ToolCategory.FILE]
  │    命中条件: 需求字符串能映射到 ToolCategory 枚举值
  │
  └─ 4. 能力关键词映射 → _CAPABILITY_CATEGORY["file"]
       映射表: {"file": FILE, "code": CODE, "search": SEARCH,
                "rag": KNOWLEDGE, "email": COMMUNICATION, ...}
```

#### 过滤器 (`_apply_filters`)

解析完成后施加三道过滤：

| 过滤维度 | 说明 | 示例 |
|----------|------|------|
| `only_available` | 过滤掉 DISCONNECTED/ERROR 状态的 Provider 工具 | MCP 服务器挂了，其工具被排除 |
| `permissions` | 写操作需要 `"write"` 权限，执行需要更高权限 | `cli` channel 默认有 write 权限 |
| `channel` | 工具带 `channel:xxx` tag 且与当前 channel 不匹配 | `feishu` channel 专用工具 |

#### 缓存

- 以 `(skill_names, channel, permissions)` 为 key 缓存 ResolveResult
- LRU 策略，最多 64 条
- `invalidate_cache()` 可手动清空

#### 核心方法

```python
class ToolResolver:
    def __init__(self, tool_manager: ToolManager):
        # 延迟构建多维索引

    def resolve(
        self,
        skill_tools: dict[str, list[str]],   # {skill_name: [tool_reqs]}
        context: str = "",
        channel: str = "cli",
        permissions: list[str] = None,
        only_available: bool = True,
        use_cache: bool = True,
    ) -> ResolveResult:
        """
        1. 延迟构建索引 (名称/标签/类别)
        2. 检查缓存
        3. 收集所有需求 → _match_all 逐条匹配
        4. 应用过滤器 (channel/权限/可用性)
        5. 构建 source_map → 缓存
        """

    def invalidate_cache(self) -> None: ...
```

---

### 3.7 WebSearchTool (`web_search.py`)

**职责：** 内置搜索引擎工具（当前为占位实现）。

```python
class WebSearchTool:
    async def search(self, query: str, num_results: int = 5) -> list[dict]:
        """返回占位结果 [{title, url, snippet}]"""

    async def __call__(self, query: str) -> str:
        """调用 search() 并格式化为文本"""
```

通过 `BuiltinProvider._BUILTIN_MODULES` 注册。`search()` 返回单个结果项，snippet 内容包含查询文本作为回显。

---

## 四、典型数据流

### Agent 执行时的工具绑定全流程

```
Skill 激活
  │  skill.tools = ["web_search", "file_read"]
  ▼
ToolResolver.resolve({"coder": ["web_search", "file_read"]}, channel="cli")
  │
  ├─ _collect_requirements → [ToolRequirement("web_search"), ToolRequirement("file_read")]
  │
  ├─ _match_one("web_search")
  │    → 精确名称命中 → tool_manager._tools["web_search"]  ✓
  │
  ├─ _match_one("file_read")
  │    → 名称未命中 → 标签未命中 → 类别匹配 FILE → filesystem__read_file  ✓
  │
  ├─ _apply_filters
  │    → filesystem 提供者 CONNECTED?  ✓
  │    → 权限检查: READ only ✓
  │
  └─ ResolveResult(tools=[WebSearchTool, FileReadTool], all_resolved=True)
       │
       ▼
  绑定到 BaseAgent
       │  agent.set_tools(resolved_tools)
       │  agent._agent 重建 (工具哈希不同)
       ▼
  ReAct 循环
       │  LLM 决定调用 web_search("Python 3.14 新特性")
       │  → 工具执行 → 结果注入消息历史
       ▼
  下一轮 turn: agent.restore_base_tools()
```

### MCP 工具生命周期

```
启动阶段 (factory.py)
  │  _load_mcp_configs() → 读取 mcp.json, 过滤 enabled=true
  │  MCPProvider(server_config) → ToolManager.add_provider()
  │
  ▼
ToolManager.start_all()
  │  asyncio.gather(provider.start() for each)
  │
  ├─ MCPProvider.start()
  │    ├─ _on_start() → 创建 AsyncExitStack
  │    ├─ discover() → _load_mcp_tools() → ClientSession → load_mcp_tools()
  │    ├─ _adapt()×N → 工具名加命名空间 + 推断类别/权限
  │    └─ self._tools = {adapted tools}
  │
  └─ ToolManager._sync(provider)
       └─ 索引更新: _tools[name] = tool, _tool_to_provider[name] = provider_name
```

---

## 五、扩展指南

### 添加内置工具

1. 创建 `src/haven/tools/your_tool.py`，实现工具类：
```python
class YourTool:
    async def __call__(self, param: str) -> str:
        # 工具逻辑
        return result
```

2. 在 `BuiltinProvider._BUILTIN_MODULES` 添加：
```python
_BUILTIN_MODULES = [
    ("web_search", "haven.tools.web_search", "WebSearchTool"),
    ("your_tool", "haven.tools.your_tool", "YourTool"),  # 新增
]
```

3. 在 `_CATEGORY_MAP` 添加分类映射：
```python
_CATEGORY_MAP = {
    "web_search": ToolCategory.SEARCH,
    "your_tool": ToolCategory.CUSTOM,
}
```

### 添加自定义 Provider

```python
from haven.tools.providers.base import ToolProvider

class RestAPIProvider(ToolProvider):
    def __init__(self, base_url: str):
        super().__init__(name="rest_api", provider_type="rest")

    async def discover(self) -> list[HavenTool]:
        # 调用 API 获取工具列表
        ...

    async def health_check(self) -> bool:
        # 检查 API 可用性
        ...
```

然后通过 `ToolManager.add_provider(RestAPIProvider(...))` 注册。

### MCP 服务器接入

在 CWD 下创建 `mcp.json`：
```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
      "transport": "stdio",
      "enabled": true
    },
    "remote-api": {
      "url": "https://api.example.com/mcp/sse",
      "transport": "http",
      "enabled": true
    }
  }
}
```

`factory.py` 会自动加载并启动所有 `enabled: true` 的服务器。

---

## 六、关键设计决策

### 命名空间隔离

MCP 工具以 `{provider_name}__{tool_name}` 命名（双下划线分隔）。例如 `filesystem` 服务器的 `read_file` → `filesystem__read_file`。这样不同 MCP 服务器的同名工具不会冲突。

### 单 Provider 故障隔离

`ToolManager.start_all()` 使用 `asyncio.gather` 但逐个捕获异常。一个 MCP 服务器连接失败不会阻止其他 Provider 正常工作。失败的 Provider 标记为 ERROR 状态，其工具在 `only_available=True` 过滤时被排除。

### 惰性索引

`ToolResolver` 的三维索引（名称/标签/类别）在首次 `resolve()` 调用时才构建，避免启动时的额外开销。索引构建后一直保持，直到调用 `invalidate_cache()`。

### tool_choice 由 Agent 控制

框架不干预 LLM 的工具选择。工具绑定后完全由 ReAct Agent 的 `create_react_agent` 决定何时调用哪个工具，保持了 LLM 的自主性。
