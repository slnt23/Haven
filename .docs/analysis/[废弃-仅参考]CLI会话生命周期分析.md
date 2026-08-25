# CLI Session 生命周期分析与修改方案

> 日期: 2026-06-16
> 状态: 等待确认
> 约束: 仅分析，不修改代码

---

## 1. 当前实现分析

### 1.1 session_id 的生成位置

| 调用者 | 传入值 | 位置 |
|--------|--------|------|
| CLI `run_repl()` | **不传**（使用默认值） | [repl.py:42](src/haven/interface/cli/repl.py#L42) |
| Daemon `_init_runtime()` | `"daemon"` | [daemon.py:102](src/haven/interface/daemon.py#L102) |
| HTTP Server | 外部传入 | [http_server.py:49](src/haven/interface/http_server.py#L49) |

`create_runtime()` 签名:

```python
# factory.py:170-172
async def create_runtime(
    session_id: str = "default",   # ← 硬编码默认值
    ...
)
```

**CLI 不传 session_id → 永远使用 "default"。**

---

### 1.2 thread_id 的生成位置

`thread_id` 在系统中出现在以下位置：

| 位置 | 值来源 | 说明 |
|------|--------|------|
| [pipeline.py:59](src/haven/execution/pipeline.py#L59) | `thread_id = session.id` | 直接对话路径 |
| [pipeline.py:79](src/haven/execution/pipeline.py#L79) | `thread_id = session.id` | 流式路径 |
| [pipeline.py:121](src/haven/execution/pipeline.py#L121) | `thread_id=thread_id` (即 session.id) | 流式直接对话 |
| [pipeline.py:164](src/haven/execution/pipeline.py#L164) | `thread_id=session.id` | 工作流回退路径 |
| [pipeline.py:105](src/haven/execution/pipeline.py#L105) | `step_thread = str(uuid.uuid4())` | 多步编排 — 每步独立 |
| [pipeline.py:192](src/haven/execution/pipeline.py#L192) | `step_thread = str(uuid.uuid4())` | 多步编排 (非流式) |
| [workflow/engine.py:56](src/haven/workflow/engine.py#L56) | `"thread_id": session.id` | 工作流级 config |
| [workflow/helpers.py:54](src/haven/workflow/helpers.py#L54) | `node_thread = str(uuid.uuid4())` | 工作流节点 — 每节点独立 |

**结论：除多步编排和工作流节点已使用独立 UUID 外，所有路径的 thread_id 都等于 session.id。**

---

### 1.3 session_id 与 thread_id 是否为同一个概念

**是。明确声明为同一概念。**

```python
# session/models.py:19
class Session:
    """会话标识 —— 不可变。
    id 即 LangGraph checkpointer 的 thread_id。
    """
    id: str
```

```
Session.id  ≡  LangGraph thread_id  ≡  Checkpointer 存储键
```

当一个概念等于另一个概念时，改变 session_id 就改变了 thread_id，也就改变了 checkpointer 读取的消息历史。

**这是一个好的设计。** 它意味着 session 隔离和对话历史隔离是同一件事。

---

### 1.4 SessionManager 的职责

[manager.py](src/haven/session/manager.py) 完整分析：

| 方法 | 职责 |
|------|------|
| `create(session_id, ...)` | 创建 Session + SessionState；session_id=None 时自动生成 UUID |
| `get(session_id)` | 返回已有 Session，不存在返回 None |
| `get_or_create(session_id)` | 获取已有或创建新 Session |
| `close(session_id)` | 移除 Session + SessionState（不删除 checkpointer 数据） |
| `reset(session_id)` | 仅重置 SessionState（turn_count=0），不改变 session_id |
| `get_checkpointer()` | 返回共享的 checkpointer |

**SessionManager 本身已经支持 UUID 生成：** `session_id=None` → `str(uuid.uuid4())`。但调用方从未使用这个能力。

---

### 1.5 Checkpointer 的职责

[factory.py:200-202](src/haven/runtime/factory.py#L200-L202)：

```python
conn = await aiosqlite.connect(str(db_dir / "checkpoint.db"))
checkpointer = AsyncSqliteSaver(conn)
```

- **存储位置**: `resource/checkpoint.db`（持久化，当前 13MB）
- **存储内容**: LangGraph 状态（messages 列表、tool_calls 等）
- **键**: `thread_id`（即 session.id）
- **生命周期**: 跨进程持久化，手动删除才清理

---

### 1.6 Runtime 如何持有当前 Session

```python
# factory.py:71
self._current_session_id = ""

# factory.py:286 (create_runtime 末尾)
runtime._current_session_id = session_id   # "default"
```

`execute()` 使用逻辑：

```python
# factory.py:73-76
async def execute(self, task: str, session_id: str = "") -> str:
    sid = session_id or self._current_session_id   # "default"
    request = ExecutionRequest(task=task, session_id=sid)
```

---

### 1.7 /clear 的实现逻辑

[factory.py:109-142](src/haven/runtime/factory.py#L109-L142)：

```
reset_session()
  │
  ├─ 1. 保留旧 session 的 user_id + channel
  ├─ 2. new_sid = str(uuid.uuid4())             ← 生成新 UUID
  ├─ 3. session_manager.close(old_sid)          ← 移除旧 Session 对象
  ├─ 4. checkpointer.adelete_thread(old_sid)    ← 尝试删除旧 checkpointer 数据
  ├─ 5. session_manager.create(new_sid, ...)    ← 创建新 Session
  ├─ 6. self._current_session_id = new_sid      ← 更新当前 ID
  └─ 7. agents.reset()                          ← 重置所有 Agent
```

**`/clear` 已经实现了我们想要的行为。** 问题是：首次启动时用的是硬编码 `"default"` 而非 UUID。

---

### 1.8 完整数据流（当前）

```
CLI 启动
  │
  ▼
create_runtime(session_id="default")          ← 硬编码
  │
  ├─ session_manager.create("default", ...)
  │    └─ Session(id="default")               ← Session.id = "default"
  │
  ├─ runtime._current_session_id = "default"
  │
  └─ 返回 Runtime
       │
       │  用户输入 "你好"
       ▼
  runtime.execute("你好")
    │
    ├─ sid = "default"
    ├─ request = ExecutionRequest(task="你好", session_id="default")
    │
    └─ executor.execute(request)
         │
         ├─ session = session_manager.get_or_create("default")
         │    └─ 已存在，返回 Session(id="default")
         │
         ├─ plan = planner.plan(request)
         │
         └─ pipeline.run(plan, task, session)
              │
              └─ agent.run(task, thread_id=session.id)
                   │        thread_id="default"
                   │
                   └─ checkpointer 读取 thread="default"
                        │
                        ├─ [第 2 次启动] 加载上次的全部消息历史  ← 问题！
                        └─ [第 1 次启动] 空
```

---

## 2. 影响范围评估

### 2.1 依赖 session_id/thread_id 的模块

| 模块 | 受影响？ | 风险 | 说明 |
|------|:---:|:---:|------|
| **runtime/factory.py** | ✅ 直接修改 | 🟢 低 | 改默认值 + 加 UUID 生成 |
| **runtime/factory.py (Runtime)** | ✅ 逻辑不变 | 🟢 低 | `_current_session_id` 现在存 UUID 而非 "default" |
| **execution/pipeline.py** | ❌ 不受影响 | 🟢 低 | 它读 `session.id`，不关心值是什么 |
| **execution/executor.py** | ❌ 不受影响 | 🟢 低 | 同 pipeline |
| **execution/planner.py** | ❌ 不受影响 | 🟢 低 | 不接触 session_id |
| **session/manager.py** | ❌ 不受影响 | 🟢 低 | 已支持 UUID 生成 |
| **session/models.py** | ❌ 不受影响 | 🟢 低 | 纯数据模型 |
| **memory/** | ❌ 不受影响 | 🟢 低 | 使用 entity_name，不依赖 session_id |
| **workflow/engine.py** | ❌ 不受影响 | 🟢 低 | 接收 session.id，值变但逻辑不变 |
| **workflow/helpers.py** | ❌ 不受影响 | 🟢 低 | 已使用独立 UUID |
| **agent/base.py** | ❌ 不受影响 | 🟢 低 | thread_id 是参数，不关心里面是什么 |
| **interface/cli/repl.py** | ❌ 可选修改 | 🟢 低 | 不传 session_id 即可（自动生成） |
| **interface/daemon.py** | ❌ 不受影响 | 🟢 低 | 显式传 `"daemon"` → 保持固定 |
| **interface/http_server.py** | ❌ 不受影响 | 🟢 低 | 接收 Runtime，内部行为透明 |
| **interface/channels/feishu.py** | ❌ 不受影响 | 🟢 低 | 显式传 session_id（但代码有 bug，见下文） |

### 2.2 不需要修改的模块（确认）

- **agent/**: thread_id 只是参数，不关心值
- **workflow/**: 已使用独立 UUID 隔离节点
- **memory/**: 使用 entity_name 索引，不依赖 session_id
- **session/**: 已内置 UUID 生成能力
- **execution/**: 读 `session.id`，值的内容不影响逻辑

### 2.3 已存在的 bug（附带发现）

[feishu.py:203-205](src/haven/interface/channels/feishu.py#L203-L205):

```python
self.runtime.state.session_id = f"feishu_{open_id}"
self.runtime.state.entity_name = f"feishu_{open_id}"
self.runtime.state.channel = "feishu"
```

`Runtime` 类没有 `state` 属性（`__slots__` 不含 `state`）。这段代码会抛出 `AttributeError`。这是已有 bug，不在本次修改范围内。

---

## 3. 三种方案分析

### 方案 A：CLI 启动时生成 UUID

```python
# repl.py — 修改
import uuid

async def run_repl() -> None:
    session_id = uuid.uuid4().hex
    runtime = await create_runtime(session_id=session_id, channel="cli")
```

| 优点 | 缺点 |
|------|------|
| ✅ 最小修改（1 行） | ❌ 把职责放在 Interface 层 |
| ✅ Interface 拥有 session 控制权 | ❌ 如果有新 CLI 入口，需要重复 |
| | ❌ 不符合 "Runtime 负责 Session 生命周期" 的架构 |

### 方案 B：create_runtime() 自动生成 UUID

```python
# factory.py — 修改
async def create_runtime(
    session_id: str = "",      # 改: "default" → ""
    ...
) -> Runtime:
    session_id = session_id or str(uuid.uuid4())  # 加: 空字符串 → UUID
```

| 优点 | 缺点 |
|------|------|
| ✅ 集中管理，所有入口自动受益 | ❌ 需要所有显式传 ID 的调用者确认（daemon 已传 "daemon"） |
| ✅ 符合 V2 架构（Runtime 管理 Session 生命周期） | |
| ✅ CLI 无需修改 | |
| ✅ Daemon / HTTP 传显式 ID 的行为不变 | |

### 方案 C：SessionManager 负责生成 UUID

```python
# manager.py — 已在 create() 中支持 session_id=None → UUID
# 只需调用方不传 session_id
```

| 优点 | 缺点 |
|------|------|
| ✅ SessionManager 已有此能力 | ❌ 调用链太长：CLI → create_runtime → SessionManager.create |
| | ❌ create_runtime 默认值 "default" 绕过了 SessionManager 的 UUID 逻辑 |
| | ❌ 需要同时改 create_runtime 默认值 + CLI，反而更复杂 |

---

## 4. 推荐方案：**方案 B**

### 理由

1. **最符合 V2 架构**。V2 设计中 Runtime 负责 Session 生命周期。CLI 不应该关心 session_id 是什么。

2. **修改量最小**。实质改动仅 2 行（`factory.py`），不触及任何 Interface 代码。

3. **向后兼容**。显式传 `session_id="daemon"` 的 Daemon 不受影响；`session_id=""` → 自动 UUID。

4. **`/clear` 行为不变**。`reset_session()` 继续生成新 UUID 替换当前 session。

### 修改文件

**仅 1 个文件：`src/haven/runtime/factory.py`**

| 行 | 修改前 | 修改后 |
|----|--------|--------|
| 171 | `session_id: str = "default"` | `session_id: str = ""` |
| 205 前 | (无) | `session_id = session_id or str(uuid.uuid4())` |

### 不需要修改的 Pydantic 默认值

[execution/request.py:41](src/haven/execution/request.py#L41)：

```python
class ExecutionRequest(BaseModel):
    session_id: str = Field(default="default")
```

该字段的 Pydantic 默认值 **不需要修改**。原因：
- `Runtime.execute()` 和 `Runtime.execute_stream()` 始终显式传入 `session_id=sid`
- Pydantic 默认值仅在无人传值时生效（不会在正常路径中发生）
- 保留它作为安全网，确保模型始终有合法值

### 测试影响

[tests/execution/test_models.py:12](tests/execution/test_models.py#L12)：

```python
assert req.session_id == "default"
```

该测试验证 `ExecutionRequest` 的 Pydantic 默认值。**不需要修改**——数据模型的默认值与业务逻辑解耦。

### 数据流变化

```
修改前:
  CLI → create_runtime() → session_id="default" → checkpointer 加载旧历史

修改后:
  CLI → create_runtime() → session_id="" → UUID 生成 → checkpointer 空白开始
  Daemon → create_runtime(session_id="daemon") → session_id="daemon" → 不变
  HTTP → 取决于调用方传入
```

---

## 5. 具体修改计划

### 文件：`src/haven/runtime/factory.py`

**修改 1**：第 171 行 — 默认值

```python
# 修改前
async def create_runtime(
    session_id: str = "default",

# 修改后
async def create_runtime(
    session_id: str = "",
```

**修改 2**：第 205 行之前 — 自动生成 UUID

```python
# 修改前
    session_manager.create(session_id, user_id=entity_name, channel=channel)

# 修改后
    session_id = session_id or str(uuid.uuid4())
    session_manager.create(session_id, user_id=entity_name, channel=channel)
```

**修改 3**：更新 `create_runtime()` 的 docstring（如存在）

无需额外修改——当前无显式文档说明默认值行为。

### 不需要修改的文件

| 文件 | 原因 |
|------|------|
| `interface/cli/repl.py` | 不传 session_id，自动享受新行为 |
| `interface/daemon.py` | 显式传 `"daemon"`，不受影响 |
| `interface/http_server.py` | 接收 Runtime 实例，行为透明 |
| `session/manager.py` | 已有 UUID 生成能力 |
| `execution/pipeline.py` | 读 `session.id`，值变但逻辑不变 |
| 所有其他模块 | 不依赖 session_id 的具体值 |

---

## 6. 测试计划

### 测试 1：启动 CLI 生成新 UUID

```
操作:
  1. 删除 resource/checkpoint.db（确保干净起点）
  2. 启动 CLI: uv run haven
  3. 输入任意对话

验证:
  - resource/checkpoint.db 中出现新的 thread_id（UUID 格式，非 "default"）
  - 可通过日志或调试确认 session_id 为 UUID
```

### 测试 2：第二次启动不加载历史

```
操作:
  1. 第一次启动 CLI，对话 "我叫张三"
  2. 退出 CLI
  3. 第二次启动 CLI，对话 "我叫什么名字？"

验证:
  - Agent 不知道你叫张三
  - Agent 回答类似 "我无法知道你的名字，因为你没有告诉过我"
  - 不是回答 "你叫张三"
```

### 测试 3：同一次运行内上下文保持

```
操作:
  1. 启动 CLI
  2. 连续对话：
     - "我叫张三"
     - "我喜欢Python"
     - "我叫什么名字？我喜欢什么语言？"

验证:
  - Agent 正确回答 "你叫张三，你喜欢Python"
  - 上下文在同一 session 内保持
```

### 测试 4：/clear 生成新 UUID

```
操作:
  1. 启动 CLI，对话 "我叫张三"
  2. 执行 /clear
  3. 对话 "我叫什么名字？"

验证:
  - Agent 不知道你叫张三
  - /clear 后是新 session
  - 长期记忆不受影响
```

### 测试 5：Daemon 模式固定 session_id

```
操作:
  1. 启动 Daemon: uv run haven serve
  2. 查看日志确认 session_id 为 "daemon"

验证:
  - Daemon 仍然使用固定 session_id="daemon"
  - 不生成随机 UUID
```

### 测试 6：全量测试回归

```bash
uv run pytest tests/ -v
```

预期：208 passed（或更多，如果没有测试耦合于 "default" session_id）。

---

## 7. 风险总结

| 风险 | 等级 | 缓解 |
|------|:---:|------|
| 旧 `checkpoint.db` 中 "default" thread 变成孤儿数据 | 🟢 极低 | 与 `/clear` 行为一致，自然废弃 |
| 测试依赖 `session_id="default"` | 🟡 低 | 搜索测试中是否有硬编码 "default" |
| Daemon 重启后丢失上下文 | 🟢 无 | Daemon 显式传 `"daemon"`，不受影响 |
| 长期记忆受影响 | 🟢 无 | Memory 以 entity_name 为索引，与 session 隔离 |

---

## 8. 总结

```
                    当前                        修改后
                    ────                        ────
CLI 启动          "default"                    UUID (自动)
CLI /clear        UUID (新)                    UUID (新) — 不变
Daemon 启动       "daemon"                     "daemon" — 不变
HTTP              取决于调用方                  取决于调用方 — 不变
上下文保持        同一 session 内 ✅             同一 session 内 ✅
历史隔离          跨启动 ❌ (共享 "default")     跨启动 ✅ (每次新 UUID)
```

**修改量：1 个文件，2 行代码。**
