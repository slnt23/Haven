---
name: 'adr'
description: 'Generates Architecture Decision Records (ADR) following industry best practices from Amazon, Uber, Microsoft, etc. Invoke when user wants to write an ADR, record a technical decision, or document architecture trade-offs.'
---

# ADR (Architecture Decision Record) 格式规范

大厂（以及业界主流团队）对 ADR 的核心要求不在于追求某种"官方标准"，而在于**强制记录决策背后的"为什么"**，并确保这份记录在团队中始终可读、可追溯。

综合 AWS、Martin Fowler 等主流实践，以及 Uber、Microsoft 等公司的内部规范，在生成 ADR 时遵循以下规范。

## 核心格式要求：至少包含"三要素"

无论采用哪种具体模板，一份合格的 ADR 必须回答三个根本问题：

1.  **上下文（Context）**：我们当时面临什么技术或业务问题？有哪些约束条件（如性能要求、团队技能、预算）？
2.  **决策（Decision）**：我们最终决定采用哪个方案？
3.  **后果（Consequences）**：这个决策带来了哪些结果？包括**正面收益**，也**必须包含负面权衡、接受的风险以及未来的潜在影响**。

## 主流模板选择

根据决策的复杂程度选择合适模板：

### 1. Nygard 模板（最简、最通用）

适合快速决策。核心结构仅四部分：**Status（状态）、Context（上下文）、Decision（决策）、Consequences（后果）**。

### 2. MADR 模板（结构更完善）

当决策涉及多个备选方案时使用。强制列出每一个严肃的备选方案，并用 `Good, because... / Bad, because...` 的格式逐一评价优劣，防止"稻草人论证"。

## 大厂强调的"纪律性"要求

### 1. 状态机必须清晰

每份 ADR 必须明确标注状态：

- `Proposed`（提议中）
- `Accepted`（已接受）
- `Deprecated`（已弃用）
- `Superseded`（已被取代）

状态流转规则：一个 **Accepted** 的 ADR **永远不能被改回 Proposed**，只能被新的 ADR 取代。

### 2. 不可变性（Immutability）

一旦决策被接受，正文就不可修改。如果情况变了，**不要改旧文档，而是写一份新的 ADR，然后在旧文档的 Status 里写上 `Superseded by ADR-XXX`**。这样保留完整的决策历史。

### 3. 存储位置与命名

- 存放在代码仓库中的 `docs/adr/` 目录，与代码一同进行版本控制
- 文件命名遵循单调递增的序号：`ADR-001-use-postgres-for-payments.md`
- 编号一旦分配，即使该决策作废也**不可复用**

## ADR 模板

生成 ADR 时使用以下结构：

```markdown
# ADR-{序号}: {简短标题}

- **Status**: {Proposed | Accepted | Deprecated | Superseded} ({日期})
- **Deciders**: @相关人员
- **Technical Story**: {关联需求/工单号，可选}
- **Related ADRs**: {相关 ADR 编号及关联说明，如无则标注"无（经检索确认）"}

## Context

{描述面临的技术或业务问题，以及约束条件}

## Decision Drivers

{列出驱动决策的关键因素，每项一行}

## Considered Options

1. **方案A**：简述方案。Good, because... / Bad, because...
2. **方案B**：简述方案。Good, because... / Bad, because...
3. **方案C**：简述方案。Good, because... / Bad, because...

## Decision Outcome

**Chosen option: {选中的方案}**，因为{简述核心理由}。

### Consequences

**Good:**

- {正面收益1}
- {正面收益2}

**Bad:**

- {负面权衡1}
- {接受的风险1}

**Neutral:**

- {中性影响1}
```

## 创建前：检索已有文档，建立关联

在创建新的 ADR 之前，**必须先检索已有 ADR**，确认是否存在与该决策主题相关的既往记录。

### 检索要求

1. **遍历已有 ADR 目录**（`docs/adr/`），逐一检查标题和内容，判断是否存在与新决策主题相关的既往文档
2. 相关性的判断标准：
   - 同一技术组件或系统模块的决策（如都是关于数据库选型、身份模型、部署方式）
   - 同一用户能力或产品方向的决策（如都是关于语音交互、主动关怀）
   - 存在前后依赖或替代关系的决策
3. 无关旧 ADR 不需要引用

### 如果找到相关联的旧 ADR，必须：

1. **在头部元数据中声明**：使用 `Related ADRs` 字段列出所有相关的旧 ADR 编号及标题，并简要说明关联关系（补充/替代/细化/冲突等）
2. **在 Context 中说明关联**：在上下文段落中明确描述新决策与旧记录的关联关系——是扩展了旧决策的范围、推翻了旧方案、还是对旧方案的具体实施细化
3. **在 Considered Options 中体现**：如果旧 ADR 中已有相关方案，在当前决策的备选方案分析中应引用并说明为何采纳/不采纳旧的思路

### 关联声明示例

```markdown
- **Related ADRs**:
  - [ADR-003](./ADR-003-基础能力架构.md)：本决策是对 S5 通信系统的具体技术方案细化（补充）
  - [ADR-006](./ADR-006-单租户身份模型.md)：本决策依赖其单租户身份模型（依赖）
```

### 关联类型说明

| 关联类型           | 场景                               | Context 写法示例                                                                |
| ------------------ | ---------------------------------- | ------------------------------------------------------------------------------- |
| 补充（extends）    | 新 ADR 是对旧决策的细化或扩展      | "ADR-003 已确定 S5 通信系统负责异步推送，本 ADR 在此基础上决定具体推送技术方案" |
| 依赖（depends）    | 新决策依赖旧决策的结论             | "本决策依赖 ADR-006 的单租户模型——一个设备对应一个人"                           |
| 替代（supersedes） | 新决策取代旧决策                   | "ADR-004 的技术栈选型中未涵盖语音场景，本 ADR 对该决策进行补充更新"             |
| 冲突（conflicts）  | 新决策与旧决策存在冲突，需明确说明 | "ADR-004 选定的技术栈与语音终端要求存在以下冲突，本 ADR 就冲突点做决策"         |

### 如果检索后确认无相关旧文档

在 ADR 中明确标注：

```markdown
- **Related ADRs**: 无（经检索，无与本决策主题相关的既往 ADR）
```

---

## 关键原则

大厂对 ADR 格式的要求，最终归结为一句话：

> **用最轻量的结构，强制记录决策的上下文与权衡，并通过"不可变 + 可取代"的纪律，让决策历史成为团队真正的资产。**

- 格式的具体模板（Nygard 或 MADR）是次要的
- **"写下负面后果"** 和 **"永不修改已接受的 ADR"** 才是最重要的硬性要求
