# Haven 项目文档

> 代号：健健 — Personal Chronic Disease Management Agent（个人慢病管理智能体）
> 版本：0.0.1
> 状态：需求基线与项目骨架阶段

---

## 项目定位（一句话）

Haven 是**面向患者端的长期陪伴型慢病管理智能体（Agent）**：长期陪伴一个用户，理解其健康状态，帮助管理疾病风险。

**这不是普通的 Chatbot 或 Web 应用，而是 Personal Chronic Disease Management Agent。** 产品目标、主路线与硬性要求见 [requirements/](requirements/README.md)。

---

## 文档体系：两类文档，两种角色

| 目录                                       | 性质         | 面向角色      | 内容                     |
| ------------------------------------------ | ------------ | ------------- | ------------------------ |
| **[requirements/](requirements/README.md)** | **★ 开发标准** | **开发人员** | **要做什么、怎么做、验收标准** |
| **[adr/](adr/README.md)**                 | 决策存档     | 架构师 / PM   | 为什么做这些决策、备选与权衡 |

### 开发人员看这里

**你只需要看 `requirements/` 目录，它是开发唯一入口。** 从 [requirements/README.md](requirements/README.md) 开始——那里定义了 Agent 主路线和 0.0.1 的交付标准。

ADR 是决策过程的存档，解释"为什么选这个方向"。**你不需要读 ADR 来写代码。** 需求文档已包含全部必要信息。

### 架构师 / PM 看这里

ADR 记录关键决策的背景、备选方案和权衡，且**只记决策、不重复维护需求明细**。明细一律以 `requirements/` 为唯一来源。需要理解某个决策的来龙去脉时，从 [adr/README.md](adr/README.md) 进入。

---

## 目录结构

```
.docs/
├── README.md            # 本文档 — 文档导航（角色分流）
├── adr/                 # 决策存档（非开发必读）
│   ├── README.md        # ADR 索引 + 阅读指引
│   ├── ADR-001-项目定位-个人慢病管理智能体.md
│   ├── ADR-002-核心能力定义.md
│   ├── ADR-003-基础能力架构.md
│   ├── ADR-004-技术栈选型.md
│   └── ADR-005-MVP范围与项目入口.md
└── requirements/        # ★ 开发标准（开发人员唯一需要看的）
    ├── README.md        # Agent 主路线 + 0.0.1 标准 + 开发工作流
    ├── REQ-001-功能需求-用户端能力.md   # Agent 面向用户的能力
    ├── REQ-002-功能需求-系统基础能力.md # 支撑 Agent 闭环的系统底座
    ├── REQ-003-非功能需求.md
    ├── REQ-004-用户故事与验收标准.md
    ├── REQ-005-数据需求.md
    └── TRACEABILITY.md  # 0.0.1 交付追踪矩阵
```

---

## 设计方法论：Agent-First

```
定义 Agent → 反推能力 → 确定架构 → 选择技术栈
```

先明确 Agent 要做什么、为谁服务；再反推需要什么能力与底层支撑；最后选技术。每一层都有明确的业务价值来源，避免过度设计。

> 本目录只负责导航。**需求管理（优先级、状态）与主路线定义已下沉到 [requirements/README.md](requirements/README.md)**，避免同一套规则两处维护。
