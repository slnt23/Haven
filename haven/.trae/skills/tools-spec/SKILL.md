---
name: "tools-spec"
description: "Defines Haven agent tool design standards: 5 criteria (capability boundaries, interface design, security/permissions, output/errors, idempotency/observability) with @tool decorator patterns and migration guides. Invoke when creating, modifying, or standardizing agent tools."
---

# 工具规范化设计规范（Haven Tools Spec）

为健健（Haven）项目中所有 Agent 工具制定统一的**设计准则、接口规范与实现模式**。
目标是让每个工具都能被 LLM 准确发现、正确调用，且调用者、审计者均可验证。

---

## 一、五项准则

### 准则 1：能力边界 —— 能做事，职责单一

| 要求                 | 说明                                                                                                   |
| -------------------- | ------------------------------------------------------------------------------------------------------ |
| 一个工具只做一件事   | 记血压、查趋势、建档分别独立，不合并                                                                   |
| 不和中间件抢活       | 工具负责业务逻辑，中间件负责通用策略（权限/审计/降级）                                                 |
| LLM 可见 vs 内部工具 | 内部状态机工具（如 `save_onboarding_draft`）应标记为 `system` 别名或通过描述明确其"不向用户转达"的特性 |
| 同步/异步统一        | 所有 I/O 工具统一为 `async def`；纯计算的同步函数也应考虑改为 async 以保持工具列表一致                 |

### 准则 2：接口设计 —— 参数结构化，描述可发现

这是对 LLM 调用准确性影响最大的准则。

| 要求                 | 实现方式                                                            |
| -------------------- | ------------------------------------------------------------------- |
| 参数有 `description` | `@tool(parse_docstring=True)` + Google 风格 `Args:` docstring       |
| 参数有类型约束       | Python 类型注解（`int`、`str`、`float`、`bool` 等），不做 `Any`     |
| 参数有合理默认值     | 可选参数设 `= None` 或合理默认值；必填参数不设默认                  |
| 框架注入参数不可见   | `runtime: ToolRuntime = None` 出现在函数签名中但不暴露给 LLM schema |
| 返回值结构化         | Pydantic BaseModel，包含 `ok: bool` + `message: str` + 业务字段     |

**推荐模式（`@tool(parse_docstring=True)`）：**

```python
from langchain.tools import tool
from pydantic import BaseModel, Field

class MyResult(BaseModel):
    ok: bool = Field(description="操作是否成功")
    message: str = Field(description="人类可读的回复文本")
    extra: str | None = Field(default=None, description="业务字段说明")

@tool(parse_docstring=True)
async def my_tool(
    name: str,
    count: int | None = None,
    runtime: Any = None,  # 框架注入，不暴露给 LLM
) -> MyResult:
    """一句话描述工具做什么。

    更详细的说明可在此展开，包括：
    - 什么情况下调用
    - 副作用是什么
    - 前置条件

    Args:
        name: 参数含义、格式要求、取值范围。
        count: 参数含义。可选，默认值为 1。

    Returns:
        MyResult: 包含操作状态和人类可读消息。
    """
```

**参数描述规范：**

- `Args:` 块中每个参数一行 `参数名: 描述。` 格式
- 描述包含：含义 → 格式/单位 → 取值范围 → 默认行为
- 例如：`systolic: 收缩压（高压），单位 mmHg，范围 60-300。`

### 准则 3：安全与权限 —— 最小权限，高风险需审批

| 要求             | 实现方式                                                                        |
| ---------------- | ------------------------------------------------------------------------------- |
| 同意闸门集中声明 | 每个工具的权限需求在一处注册表声明，中间件自动拦截，不在工具内部重复判断        |
| 高风险操作审批   | `interrupt_on` 声明在工具元数据中，不在 `agent.py` 里硬编码                     |
| 健康数据最小暴露 | 审计日志只记元信息（工具名、结果、耗时），绝不记血压值、档案字段                |
| MCP 工具隔离     | 外部 MCP 走独立的 `mcp_policy` 中间件：白名单 + 审计 + 降级，与本地工具物理隔离 |

**权限登记表模式：**

```python
# tools/permissions.py —— 唯一真相源
from dataclasses import dataclass

@dataclass(frozen=True)
class ToolPermission:
    consent_required: bool = False
    requires_approval: bool = False
    audit_write: bool = True

TOOL_PERMISSIONS: dict[str, ToolPermission] = {
    "record_blood_pressure": ToolPermission(consent_required=True),
    "delete_my_data": ToolPermission(consent_required=False, requires_approval=True),
    # ...
}
```

### 准则 4：输出与错误 —— 清晰、可解析、可验证

| 要求                  | 实现方式                                                            |
| --------------------- | ------------------------------------------------------------------- |
| 统一 `ok` + `message` | 所有返回值 Pydantic 模型都有这两个字段                              |
| 错误分类有枚举码      | 定义 `ToolErrorCode` enum，替代当前纯字符串判断                     |
| 工具异常可溯源        | 异常信息写入 ToolMessage content（而非空白 "Error invoking tool"）  |
| 降级文案统一          | 数据库不可用 → `degraded()` 固定文案；LLM 故障 → 模型层降级；不混淆 |

**错误码设计：**

```python
from enum import StrEnum

class ToolErrorCode(StrEnum):
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    INVALID_PARAM = "INVALID_PARAM"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    DUPLICATE_RECORD = "DUPLICATE_RECORD"
    PENDING_EXPIRED = "PENDING_EXPIRED"
    PENDING_MISMATCH = "PENDING_MISMATCH"
```

### 准则 5：幂等性与可观测性 —— 重试不惹祸，每一步可见

| 要求              | 实现方式                                                                    |
| ----------------- | --------------------------------------------------------------------------- |
| 写操作幂等        | 重复同意 → 返回"已同意"；重复建档 → 整档重写；1 分钟内同数值血压 → 拒绝重复 |
| tool_call_id 关联 | 审计日志关联 LLM 的 `tool_call_id`，可追溯"哪次调用触发了哪次写操作"        |
| 执行耗时记录      | 统一日志记录工具调用耗时（ms），用于性能监控                                |
| 审计覆盖完整      | 所有写操作（建档、记血压、确认、删除）都落审计日志，不只同意和 MCP          |

---

## 二、`@tool` 装饰器使用规范

### 引入方式

```python
from langchain.tools import tool
```

> 项目当前 `langchain==1.4.0`、`langchain-core==1.6.2`，`@tool` 完全可用。
> MDA 的 SKILL.md 也推荐使用 `@tool(parse_docstring=True)`。

### 三种使用模式

| 模式           | 用法                               | 适用场景                    |
| -------------- | ---------------------------------- | --------------------------- |
| 基础 `@tool`   | `@tool` + 类型注解                 | 简单工具，参数少            |
| 解析 docstring | `@tool(parse_docstring=True)`      | 参数多、需要详细描述的工具  |
| 显式 schema    | `@tool(args_schema=MyInputSchema)` | 需要完全控制 JSON Schema 时 |

项目推荐使用模式 2（`parse_docstring=True`），参数描述写在 Google 风格 docstring 的 `Args:` 块中。

### runtime 注入参数处理

`ToolRuntime` 类型的参数是框架注入的，不应暴露给 LLM。
LangChain 会**自动将 `ToolRuntime` 注解的参数从 LLM 可见的 schema 中移除**。

```python
@tool(parse_docstring=True)
async def record_blood_pressure(
    systolic: int,              # LLM 可见
    diastolic: int,              # LLM 可见
    measured_at: str | None = None,  # LLM 可见（可选）
    runtime: ToolRuntime = None,     # 框架注入，LLM 不可见
) -> BpRecordResult:
    """..."""
```

> **注意**：使用 `ToolRuntime`（来自 `langchain.tools`）而非
> `ManagedDeepAgentRuntime`，因为 MDA 的 runtime 代理不是
> `ManagedDeepAgentRuntime` 实例，pydantic 校验会失败。

### 返回值约定

`@tool` 装饰器会尊重函数的返回类型注解。返回 Pydantic BaseModel 时，
LangChain 会自动将其序列化为 JSON 写入 ToolMessage.content。

因此**不需要改动现有的返回值 Schema**（`schemas/tools.py` 中的模型继续使用）。

---

## 三、工具实现模板

### 标准异步工具（有参数、有 DB）

```python
from langchain.tools import tool, ToolRuntime
from schemas.tools import XxxResult
from tools._helpers import degraded, has_consented, uid_of

@tool(parse_docstring=True)
async def example_tool(
    required_param: int,
    optional_param: str | None = None,
    runtime: ToolRuntime = None,
) -> XxxResult:
    """一句话描述。

    详细说明块（可选但推荐）。

    Args:
        required_param: 必填参数的含义、格式、范围。
        optional_param: 可选参数的含义。留空则默认 xxx。

    Returns:
        XxxResult: 包含操作状态和人类可读消息。
    """
    uid = uid_of(runtime)
    if uid is None:
        return XxxResult(ok=False, message=NO_IDENTITY_REPLY)

    # 业务校验（在 DB 操作之前）
    if optional_param and not validate(optional_param):
        return XxxResult(ok=False, message="参数格式错误：…")

    try:
        async with session_scope() as session:
            if not await has_consented(session, uid):
                return XxxResult(ok=False, message=MSG.consent_required)
            # ... 业务逻辑 ...
    except DatabaseUnavailable:
        return XxxResult(ok=False, message=degraded())

    return XxxResult(ok=True, message="操作成功", ...)
```

### 无参数同步工具

```python
@tool
def get_policy() -> PolicyResult:
    """展示政策全文。无需前置条件。"""
    return PolicyResult(
        policy_version=VERSION,
        message=f"政策内容…{GUIDANCE}",
    )
```

---

## 四、改造路线图

### 阶段 0：基础规范制定（当前已完成）

- [x] 五项准则定义
- [x] `@tool` 装饰器模式确认
- [x] 本文档编写

### 阶段 1：试点改造（逐个工具加 `@tool`）

| 顺序 | 工具                              | 特点                          | 风险 |
| ---- | --------------------------------- | ----------------------------- | ---- |
| 1    | `get_consent_policy`              | 同步、无参数、无 DB           | 最低 |
| 2    | `get_seven_day_trend`             | 异步、有 runtime、无 LLM 参数 | 低   |
| 3    | `get_pending_blood_pressure`      | 异步、有 runtime、无 LLM 参数 | 低   |
| 4    | `consent_status`/`record_consent` | 异步、有 runtime、无 LLM 参数 | 低   |
| 5    | `record_blood_pressure`           | 异步、参数最多、受益最大      | 中   |
| 6    | `save_health_profile`             | 异步、参数多                  | 中   |
| 7    | `save_onboarding_draft`           | 异步、内部记账工具            | 中   |
| 8    | `confirm_abnormal_blood_pressure` | 异步、中断门                  | 中   |
| 9    | `get_health_profile`              | 异步                          | 低   |
| 10   | `delete_my_data`                  | 异步、中断门                  | 中   |

### 阶段 2：权限外化

- 创建 `tools/permissions.py` 权限登记表
- 创建 `middleware/consent_policy.py` 同意中间件
- 从工具内部移除 `has_consented()` 内联调用
- 工具元数据支持中断门声明

### 阶段 3：可观测性加固

- 统一审计日志接入（所有写操作）
- tool_call_id 关联
- 执行耗时记录
- 错误码枚举化

---

## 五、常见反模式（不要这样做）

| 反模式                       | 为什么不好                         | 正确做法                                 |
| ---------------------------- | ---------------------------------- | ---------------------------------------- |
| 参数用 `Any` 类型            | LLM 不知道能传什么                 | 用具体类型 `int`/`str`/`bool`/`float`    |
| 参数无 description           | LLM 只能猜参数含义                 | 用 `parse_docstring=True` + `Args:` 块   |
| 工具内联权限判断             | 分散、易遗漏                       | 权限在中间件统一处理                     |
| 工具抛异常而不是返回错误结果 | LLM 看到空白 "Error invoking tool" | 捕获异常，返回 `ok=False` + message      |
| 同步/异步混用无规律          | 工具列表行为不一致                 | 统一用 `async def`（除纯计算工具）       |
| 返回值直接用 `str`           | 下游无法解析结构化数据             | 用 Pydantic BaseModel                    |
| 硬编码权限在 agent.py        | 工具和权限声明分离，不同步         | 权限声明在工具元数据中，或在中间件登记表 |

---

## 六、检查清单

创建或修改工具时，逐一确认：

- [ ] 工具职责单一，一个函数只做一件事
- [ ] 使用了 `@tool(parse_docstring=True)` 装饰器
- [ ] 所有 LLM 可见参数在 `Args:` 块中有描述（格式、单位、范围）
- [ ] `runtime: ToolRuntime = None` 放在参数列表最后
- [ ] 返回 Pydantic BaseModel（含 `ok` + `message`）
- [ ] 所有异常路径返回 `ok=False` + 人类可读 message，不裸抛异常
- [ ] 数据库不可用 → 返回 `degraded()` 固定文案
- [ ] 写操作有幂等处理（重复调用不产生副作用）
- [ ] 权限需求在 `tools/permissions.py` 中声明（若有）
- [ ] 审计日志记录了必要的元信息（若有）
