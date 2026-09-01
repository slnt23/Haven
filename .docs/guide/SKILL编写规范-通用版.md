# SKILL 编写规范（通用版）

> 本规范面向希望编写、维护和验证 **Agent Skills** 的开发者。
>
> **规范定位：**以 Agent Skills 开放规范为基线，同时补充跨客户端的工程实践。凡属于某个客户端的扩展能力，都会明确标注“客户端扩展”，避免把平台特性误写成通用标准。

---

## 1. 概述

Agent Skill 是一个可复用的技能包，本质上是一个目录，其中至少包含一个 `SKILL.md`。`SKILL.md` 通过 YAML Frontmatter 描述技能身份与触发场景，并通过 Markdown 正文提供执行指令；Skill 还可以附带脚本、参考文档和静态资源。

Agent Skills 最初由 Anthropic 发起，现已作为开放格式发展，并被多个 AI Agent / 编程工具采用。不同客户端对技能目录位置、工具权限、自动触发和其他扩展能力可能存在差异，因此应区分：

- **规范层**：跨客户端应尽量保持兼容的 Agent Skills 格式。
- **客户端层**：某个具体工具额外支持的目录、字段或行为。
- **工程层**：为了可靠性、可测试性和可维护性而采用的最佳实践。

### 核心原则

1. **单一职责**：一个 Skill 聚焦一个明确任务或紧密相关的一组工作流。
2. **渐进式披露**：启动阶段只暴露 `name` 和 `description` 等元数据；触发后再加载正文；需要时再读取 `references/`、`assets/` 等资源。
3. **自包含**：Skill 所需的脚本、参考资料和模板尽量随 Skill 一起提供。
4. **可执行**：正文中的关键步骤应能指导 Agent 实际完成任务，而不是只有背景知识。
5. **边界清晰**：明确适用范围、限制条件和不应执行的操作。
6. **可验证**：对于可以客观判断结果是否正确的 Skill，应提供验证步骤和测试用例。
7. **跨客户端兼容优先**：除非明确依赖某个平台，否则不要使用客户端专有字段替代标准字段。

---

## 2. Skill 目录结构

### 2.1 最小结构

一个有效 Skill 至少需要：

```text
<skill-name>/
└── SKILL.md
```

### 2.2 推荐结构

```text
<skill-name>/
├── SKILL.md                  # 必须：元数据 + 核心指令
├── scripts/                  # 可选：可重复、确定性强的执行脚本
│   ├── validate.py
│   └── generate.sh
├── references/               # 可选：详细参考资料，按需读取
│   ├── architecture.md
│   └── patterns.md
├── assets/                   # 可选：模板、图片、Schema、配置等输出资源
│   └── template.yaml
└── evals/                    # 可选：测试/评估用例，不属于核心规范
    └── evals.json
```

除上述目录外，可以根据具体 Skill 增加其他文件或目录；但不要为了“看起来完整”而机械创建空目录。

### 2.3 目录命名

推荐：

```text
code-review/
api-doc-generator/
data-analysis/
```

建议遵循：

- 小写字母
- 数字可以使用
- 使用单个连字符 `-`
- 不使用空格、下划线或大写字母
- 不以 `-` 开头或结尾
- 不使用连续连字符 `--`
- 目录名应与 `SKILL.md` 中的 `name` 保持一致

---

## 3. SKILL.md 格式

`SKILL.md` 由两部分组成：

1. YAML Frontmatter
2. Markdown 正文

最小示例：

```markdown
---
name: code-review
description: Review code for bugs, security issues, maintainability, and project conventions. Use when reviewing code, preparing a change for merge, or investigating code quality problems.
---

# Code Review

详细执行指令……
```

---

## 4. YAML Frontmatter 规范

### 4.1 标准字段

当前 Agent Skills 开放规范要求：

| 字段 | 必填 | 约束 / 用途 |
|---|---|---|
| `name` | 是 | 1～64 字符；小写字母、数字和连字符；不能以连字符开头或结尾；不能出现 `--`；应与父目录名一致 |
| `description` | 是 | 1～1024 字符；说明 Skill 做什么，以及什么时候使用 |
| `license` | 否 | 许可证名称，或指向随 Skill 提供的许可证文件 |
| `compatibility` | 否 | 1～500 字符；说明环境、系统包、网络访问、目标产品等要求 |
| `metadata` | 否 | 字符串键值映射，用于存放额外元数据 |
| `allowed-tools` | 否 | 以空格分隔的预批准工具列表；目前属于实验性能力，不同客户端支持程度可能不同 |

### 4.2 推荐写法

```yaml
---
name: api-doc-generator
description: Generate and update REST API documentation from source code and API definitions. Use when creating API documentation, updating OpenAPI specifications, or reviewing API documentation for consistency.
compatibility: Requires access to the project source code and the project's API definition files.
metadata:
  author: example-team
  version: "1.0.0"
---
```

### 4.3 关于 `version`、`author`、`tags` 等字段

不要把下面这些字段直接当成 Agent Skills 通用标准字段：

```yaml
version: "1.0.0"
author: "xxx"
tags: ["api", "documentation"]
model: "..."
user-invocable: true
```

如果需要保存作者、版本、标签等信息，推荐放入标准 `metadata`：

```yaml
metadata:
  author: example-team
  version: "1.0.0"
  tags: "api,documentation,openapi"
```

某些客户端可能支持额外字段，例如用户直接调用、模型选择等；这些属于**客户端扩展**。如果 Skill 需要跨客户端复用，不应依赖这些扩展字段。

---

## 5. `name` 编写规范

### 5.1 推荐规则

```yaml
name: code-review
```

合法示例：

```text
pdf-processing
data-analysis
api-doc-generator
spring-boot-review
```

不推荐或无效：

```text
Code-Review       # 大写
code_review       # 下划线
code review       # 空格
-code-review      # 以 - 开头
code-review-      # 以 - 结尾
code--review      # 连续 --
```

### 5.2 目录必须匹配

推荐：

```text
code-review/
└── SKILL.md

SKILL.md:
---
name: code-review
description: ...
---
```

不要出现：

```text
code-review/
└── SKILL.md

name: code-reviewer
```

---

## 6. `description` 编写规范

`description` 是 Skill 被发现和判断是否触发的核心元数据。Agent 在决定是否加载 Skill 正文前，通常只能看到 Skill 的名称和描述，因此**触发条件必须写在 `description` 中，而不能只写在正文的“何时使用”章节里**。

### 6.1 必须回答两个问题

`description` 至少要让 Agent 明白：

1. **这个 Skill 能做什么？**
2. **什么情况下应该使用它？**

推荐模板：

```text
<能力描述>. Use when <场景1>, <场景2>, or <场景3>.
```

### 6.2 好的示例

```yaml
description: Review backend code for correctness, security, performance, and maintainability. Use when reviewing pull requests, investigating code quality issues, or preparing backend changes for merge.
```

```yaml
description: Generate and update REST API documentation and OpenAPI specifications from project source code. Use when creating API docs, updating endpoint definitions, or checking documentation consistency.
```

### 6.3 不好的示例

```yaml
description: A skill for code review.
```

问题：只说明名称，没有有效触发场景。

```yaml
description: Helps with development tasks.
```

问题：范围过大，容易与其他 Skill 冲突。

```yaml
description: Generates API documentation.
```

问题：缺少明确的使用场景和边界。

### 6.4 不要把描述限制成“必须出现某个关键词”

不要只写：

```yaml
description: Use when the user says "code review".
```

更好的方式是描述用户意图：

```yaml
description: Review code for bugs, security issues, maintainability, and project conventions. Use when the user asks for a code review, wants a pre-merge quality check, or asks why a piece of code may be problematic.
```

### 6.5 Description 长度

当前开放规范的硬限制是：

```text
1～1024 字符
```

**不是 200 字符。**

工程上仍然建议保持简洁，通常用 1～3 句话就足够。不要为了凑满 1024 字符堆砌关键词。

### 6.6 Description 优化应通过测试，而不是猜测

如果一个 Skill 经常“不触发”或“误触发”，不要无限增加关键词。

建议建立一组真实测试：

- 8～10 个应该触发的请求
- 8～10 个不应该触发的近似请求
- 尽量包含口语化表达、隐含需求和与其他 Skill 容易混淆的场景

然后根据实际触发结果调整 `description`。

---

## 7. Markdown 正文规范

Frontmatter 负责“让 Agent 知道什么时候加载”，正文负责“加载之后怎么做”。

正文没有强制固定章节结构，但推荐：

```markdown
# <Skill 名称>

## 概述

## 何时使用

## 前置条件

## 执行流程

### 步骤 1：...

### 步骤 2：...

## 输出要求

## 边界与限制

## 验证规则

## 参考资源
```

### 7.1 概述

用 2～3 句话说明：

- Skill 的目标
- 主要处理什么任务
- 最终希望得到什么结果

不要把整个背景知识库放在这里。

### 7.2 何时使用

这一章节可以帮助阅读和维护 Skill，但**真正决定触发的场景仍必须写在 Frontmatter 的 `description` 中**。

正文中的“何时使用”可以补充更细的判断，例如：

```markdown
## 何时使用

适用于：

- 用户明确要求进行代码审查
- 合并代码前进行质量检查
- 用户要求分析潜在安全问题
- 用户希望判断某段代码是否存在明显性能问题

不适用于：

- 单纯生成一段全新代码
- 单纯解释某个语法概念
- 与代码质量无关的项目管理问题
```

### 7.3 前置条件

明确列出：

- 所需文件
- 所需工具
- 所需权限
- 所需运行环境
- 必须存在的项目上下文

例如：

```markdown
## 前置条件

- 能够读取目标项目源码
- 如果项目存在 CONTRIBUTING.md 或项目级编码规范，应优先读取
- 如果需要运行测试，应确认对应运行环境可用
```

---

## 8. 执行指令编写

### 8.1 使用可执行、明确的语言

推荐：

```markdown
先读取项目级编码规范，再扫描目标模块的目录结构。
确认项目已有测试框架后，再运行与修改范围相关的测试。
发现问题时，给出文件路径、行号、问题原因和修复建议。
```

避免：

```markdown
根据情况检查代码。
适当优化一下。
确保代码质量。
```

后者给 Agent 的决策空间过大，容易产生不一致结果。

### 8.2 使用命令式表达

推荐：

```text
检查……
读取……
确认……
运行……
比较……
验证……
```

而不是大量使用：

```text
可以……
可能需要……
最好……
应该……
```

对于确实允许 Agent 自主选择的地方，应明确说明选择原则，而不是强行规定唯一方案。

### 8.3 不要过度限制 Agent

Skill 的目标不是把 Agent 变成一个死板的脚本解释器。

例如不推荐：

```markdown
必须严格按照以下 37 个步骤执行，任何一步都不能跳过。
```

更好的写法：

```markdown
按以下顺序完成主要流程。对于不适用的步骤，根据前置条件跳过，并在最终结果中说明。
```

**原则：**

- 高风险、容易出错的操作 → 提供更具体的步骤和检查点
- 常规分析、开放性任务 → 保留合理的自主决策空间

---

## 9. 输出格式规范

如果输出格式很重要，应直接给出模板。

例如：

```markdown
## 输出格式

始终按照以下结构输出：

# 代码审查报告

## 概览

- 审查范围：
- 严重问题：
- 一般问题：
- 建议改进：

## 严重问题

1. [分类] 文件:行号
   - 问题：
   - 原因：
   - 建议：

## 一般问题

1. [分类] 文件:行号
   - 问题：
   - 建议：

## 总结

- 是否建议合并：
- 合并前必须处理：
```

对于需要严格机器解析的输出，建议进一步定义 JSON Schema 或固定字段，而不是只给自然语言示例。

---

## 10. 边界与限制

一个成熟 Skill 应明确：

### 10.1 做什么

```markdown
## 边界

本 Skill 负责：

- 检查代码质量
- 发现明显安全问题
- 分析性能风险
- 提供可执行的修复建议
```

### 10.2 不做什么

```markdown
本 Skill 不负责：

- 自动修改生产环境
- 自动提交代码
- 自动发布版本
- 替代项目自身的安全审批流程
```

### 10.3 不确定时怎么办

对于信息不足的场景，应规定：

```markdown
如果缺少判断所需的信息：

1. 优先读取项目已有文档和配置；
2. 如果仍无法确定，明确指出缺失信息；
3. 不要编造项目约定；
4. 不要把推测描述成确定事实。
```

---

## 11. 渐进式披露

Agent Skills 的核心设计之一是渐进式加载：

```text
第 1 层：Skill 元数据
    ↓
name + description
    ↓
用于发现和判断是否触发

第 2 层：SKILL.md 正文
    ↓
Skill 被触发后加载
    ↓
核心工作流和执行指令

第 3 层：Bundled Resources
    ↓
按需读取 / 执行
    ↓
scripts/
references/
assets/
```

### 11.1 内容放在哪里

| 内容 | 推荐位置 |
|---|---|
| Skill 是什么 | `description` |
| 什么时候使用 | `description` |
| 核心执行流程 | `SKILL.md` |
| 关键输出格式 | `SKILL.md` |
| 详细技术资料 | `references/` |
| 可重复执行逻辑 | `scripts/` |
| 模板、图片、Schema | `assets/` |
| 测试 / Eval | `evals/` |

### 11.2 SKILL.md 大小建议

开放规范建议利用渐进式披露控制上下文成本：

- `SKILL.md` 尽量控制在 **500 行以内**
- 正文建议控制在约 **5000 tokens 以内**
- 复杂参考资料放入 `references/`

超过这个规模并不代表 Skill 无效，但通常意味着应该进一步拆分。

### 11.3 Reference 文件

如果 `references/` 中存在较大的文档，应：

- 每个文件聚焦一个主题
- 在 `SKILL.md` 中明确什么时候读取它
- 使用相对路径
- 避免多层级、难以追踪的引用链

例如：

```markdown
## 参考资料

当需要判断 API 命名规则时，读取：

`references/api-conventions.md`

当需要判断错误码规则时，读取：

`references/error-codes.md`
```

---

## 12. Scripts 编写规范

脚本适合处理：

- 重复执行的逻辑
- 对确定性要求高的操作
- 不希望每次由模型重新生成的代码
- 文件转换、校验、批处理等任务

### 12.1 推荐原则

脚本应：

- 自包含，或明确记录依赖
- 提供清晰的错误信息
- 正确处理异常情况
- 接受参数而不是硬编码项目路径
- 对重复任务尽量保持确定性
- 在必要时提供 `--help`
- 对版本敏感的依赖尽量固定版本

不要求所有脚本都必须使用 shebang，也不要求所有脚本都必须通过标准输入/输出工作；这些应根据实际运行方式决定。

### 12.2 什么时候不应该写脚本

如果任务只是：

- 简单判断
- 少量文本修改
- 一次性的自然语言分析

没有必要为了“规范完整”而创建脚本。

---

## 13. 路径与资源引用

Skill 内部引用资源时，使用相对于 Skill 根目录的路径：

```markdown
参考：
[API 规范](references/api-conventions.md)

运行：
scripts/validate.py
```

不要硬编码：

```text
C:\Users\xxx\project\...
/home/xxx/project/...
```

这样可以提高 Skill 的可移植性。

---

## 14. 客户端兼容性

### 14.1 标准与客户端扩展要分开

推荐把 Skill 写成：

```text
核心内容
    ↓
Agent Skills 标准
    ↓
尽量跨客户端兼容

客户端扩展
    ↓
Claude Code / VS Code / Cursor / 其他 Agent
    ↓
仅在确实需要时使用
```

例如：

- `name`、`description` → 标准核心字段
- `compatibility`、`metadata`、`license` → 标准可选字段
- `allowed-tools` → 标准中的实验性字段，客户端支持情况可能不同
- `user-invocable`、`model` 等 → 如果某个产品支持，应视为产品扩展，不要写成通用标准

### 14.2 技能目录位置

不同客户端的默认目录可能不同，因此不要把某一个工具的目录写成“所有 Agent 的标准目录”。

例如某客户端可能使用：

```text
.agents/skills/
```

另一个客户端可能使用：

```text
.claude/skills/
.cursor/skills/
```

具体位置应以目标客户端文档为准。

---

## 15. 完整示例：代码审查 Skill

### 15.1 目录结构

```text
code-review/
├── SKILL.md
└── references/
    └── common-issues.md
```

### 15.2 SKILL.md

```markdown
---
name: code-review
description: Review code for correctness, security, performance, maintainability, and project conventions. Use when reviewing code, preparing changes for merge, investigating code quality issues, or checking whether an implementation follows project standards.
metadata:
  version: "1.0.0"
---

# Code Review

对代码进行系统化审查，重点发现真实问题和可执行的改进点。

## 前置条件

- 可以读取目标代码
- 优先读取项目级编码规范和架构文档
- 如果涉及测试，应确认项目测试方式

## 执行流程

### 1. 理解上下文

先确认：

- 项目技术栈
- 目标模块
- 修改目的
- 项目已有规范

### 2. 检查架构与设计

检查：

- 模块边界
- 职责划分
- 依赖方向
- 是否存在明显过度耦合
- 是否引入不必要的抽象

### 3. 检查正确性

检查：

- 空值和异常情况
- 边界条件
- 并发问题
- 资源释放
- 错误处理
- 数据一致性

### 4. 检查安全性

检查：

- 硬编码密钥
- 未校验的用户输入
- 权限绕过
- SQL 注入
- 路径穿越
- 敏感信息泄露

### 5. 检查性能

仅报告有依据的性能问题，例如：

- N+1 查询
- 明显的重复计算
- 不必要的大量内存占用
- 明显的阻塞操作

不要为了“凑问题数量”而提出没有依据的性能优化。

### 6. 检查可维护性

检查：

- 命名
- 代码复杂度
- 重复逻辑
- 注释质量
- 测试覆盖
- 与项目现有风格的一致性

## 输出格式

按严重程度排序：

1. 阻塞问题
2. 高风险问题
3. 一般问题
4. 可选优化

每个问题包含：

- 文件路径和行号
- 问题描述
- 为什么是问题
- 推荐修改方式

如果代码已经满足要求，不要为了提出建议而强行制造问题。

## 边界

- 不要把个人偏好当成项目规范
- 不要在缺少上下文时武断判断
- 不要把理论上的风险描述成已经发生的问题
- 如果无法确认，应明确说明不确定性
```

---

## 16. 完整示例：API 文档 Skill

### 16.1 目录结构

```text
api-doc-generator/
├── SKILL.md
├── scripts/
│   └── generate-openapi.py
├── assets/
│   └── template.yaml
└── references/
    └── openapi-conventions.md
```

### 16.2 SKILL.md

```markdown
---
name: api-doc-generator
description: Generate and update REST API documentation and OpenAPI specifications from project source code and API definitions. Use when creating API documentation, updating endpoint definitions, or checking API documentation for consistency.
compatibility: Requires access to the project source code and the project's API definition files.
metadata:
  version: "1.0.0"
---

# API Doc Generator

根据项目实际代码和 API 定义生成或更新 API 文档。

## 前置条件

- 可以读取 API 实现或 API 类型定义
- 如果项目存在已有 API 文档规范，应优先遵循
- 不确定接口行为时，以实际代码为准，不要自行编造

## 执行流程

### 1. 扫描 API

识别：

- Endpoint
- HTTP Method
- Request 参数
- Request Body
- Response
- Error Response

### 2. 对照项目规范

读取：

`references/openapi-conventions.md`

检查命名、错误码、分页、鉴权等约定。

### 3. 生成或更新文档

优先保持已有文档结构，只修改发生变化的部分。

### 4. 验证

检查：

- 所有目标 Endpoint 是否覆盖
- Request / Response Schema 是否完整
- OpenAPI 格式是否有效
- 文档是否与代码一致

## 输出

生成或更新 OpenAPI 文档，并说明：

- 新增接口
- 修改接口
- 删除接口
- 无法确定的信息
```

---

## 17. 验证与检查

### 17.1 结构验证

```text
[ ] Skill 目录存在
[ ] SKILL.md 位于 Skill 根目录
[ ] YAML Frontmatter 存在且可解析
[ ] name 存在
[ ] description 存在
[ ] name 与目录名一致
[ ] name 符合命名规则
[ ] description 不超过 1024 字符
```

### 17.2 Frontmatter 验证

```text
[ ] 没有误用客户端专有字段作为通用标准字段
[ ] compatibility 在存在时不超过 500 字符
[ ] metadata 为字符串键值
[ ] allowed-tools 如果使用，确认目标客户端支持
```

### 17.3 内容验证

```text
[ ] description 同时说明能力和触发场景
[ ] 核心执行步骤明确、可执行
[ ] 关键输出格式明确
[ ] 边界和限制明确
[ ] 引用路径正确
[ ] 没有不必要的大段背景知识
```

### 17.4 功能验证

```text
[ ] 应触发的请求能够触发
[ ] 相邻但不相关的请求不会频繁误触发
[ ] Agent 能根据正文完成主要任务
[ ] 结果符合预期
[ ] 必要时能够调用脚本或读取 references
```

---

## 18. Skill 触发测试

对于重要 Skill，建议建立触发测试集。

### 18.1 测试集建议

建议约 20 条：

```text
8～10 条：应该触发
8～10 条：不应该触发
```

重点测试：

- 不同说法是否都能触发
- 用户是否明确说出 Skill 名称
- 用户没有说出领域关键词时能否正确触发
- 与其他 Skill 的边界是否清楚
- 近似请求是否误触发

### 18.2 示例

```json
[
  {
    "query": "帮我检查这段 Java 代码有没有明显的并发问题",
    "should_trigger": true
  },
  {
    "query": "帮我看看这个 PR 有没有严重代码质量问题",
    "should_trigger": true
  },
  {
    "query": "给我写一个 Java Hello World",
    "should_trigger": false
  }
]
```

如果进行正式评估，可以为每条测试定义：

- 预期结果
- 可验证条件
- 输入文件
- 实际触发情况

---

## 19. 输出质量验证

“Skill 被触发”不等于“Skill 写得好”。

建议将验证拆成两个层次：

### 层次 1：触发正确性

```text
用户请求
   ↓
是否应该触发？
   ↓
实际是否触发？
```

### 层次 2：执行质量

```text
Skill 被触发
   ↓
是否遵循指令？
   ↓
输出是否完整？
   ↓
结果是否正确？
```

因此，一个成熟 Skill 至少要同时关注：

```text
Trigger Quality
+
Execution Quality
```

---

## 20. 版本管理

如果 Skill 会持续维护，建议使用版本信息。

推荐：

```yaml
metadata:
  version: "1.2.0"
```

或者由项目自身的版本管理系统记录。

如果版本变化会影响行为，建议在 Git 中保留修改记录。

注意：`version` 本身不是 Agent Skills 核心必填 Frontmatter 字段；这里将其放在 `metadata` 中，是为了保持标准兼容。

---

## 21. 常见反模式

| 反模式 | 问题 | 改进 |
|---|---|---|
| description 太模糊 | Agent 不知道什么时候使用 | 写清能力 + 触发场景 |
| description 只有关键词 | 容易误触发 | 描述用户意图和任务范围 |
| 把触发条件只写在正文 | 触发前 Agent 看不到正文 | 把关键触发条件放进 description |
| 一个 Skill 包含多个无关任务 | 职责混乱、触发冲突 | 拆分 Skill |
| SKILL.md 过大 | 占用上下文 | 把详细资料移到 references |
| 大量背景知识 | Agent 得到的信息多，但执行指导少 | 保留必要背景，优先写操作指令 |
| 过度使用 MUST | 限制 Agent 自主判断 | 仅对关键约束使用强制规则 |
| 硬编码绝对路径 | 无法跨项目复用 | 使用相对路径和参数 |
| 所有逻辑都让模型现写 | 结果不稳定 | 将确定性逻辑放进 scripts |
| 为了完整而创建空目录 | 增加维护成本 | 只创建实际需要的目录 |
| 把客户端扩展当成标准 | 降低跨客户端兼容性 | 明确区分标准字段和平台扩展 |
| 没有验证步骤 | 无法判断结果是否正确 | 增加 Validation |
| 只有正向测试 | 容易误触发 | 增加近似负向测试 |
| 为了凑问题数量而输出建议 | 降低结果可信度 | 没有问题就明确说明没有发现 |

---

## 22. 推荐的最终检查清单

### Skill 结构

```text
[ ] SKILL.md 存在
[ ] 目录名与 name 一致
[ ] 只有实际需要的 scripts/references/assets/evals
```

### Frontmatter

```text
[ ] name 合法
[ ] description 合法
[ ] description ≤ 1024 字符
[ ] description 包含“做什么”
[ ] description 包含“什么时候使用”
[ ] 可选字段符合 Agent Skills 规范
[ ] 客户端扩展没有被误写成通用标准
```

### 正文

```text
[ ] 目标明确
[ ] 前置条件明确
[ ] 执行步骤可执行
[ ] 输出格式明确
[ ] 边界清晰
[ ] 有验证方法
[ ] 没有无意义的重复说明
[ ] 没有把大量参考资料直接塞进正文
```

### 资源

```text
[ ] scripts 可执行且依赖明确
[ ] references 使用相对路径
[ ] assets 只存真正需要的资源
[ ] 大型参考资料没有重复塞入 SKILL.md
```

### 测试

```text
[ ] 有代表性的正向触发用例
[ ] 有近似负向用例
[ ] 已验证 Skill 能正确触发
[ ] 已验证 Skill 触发后能正确执行
```

---

## 23. 参考资源

- Agent Skills Specification：<https://agentskills.io/specification>
- Agent Skills Overview：<https://agentskills.io/home>
- Description 优化指南：<https://agentskills.io/skill-creation/optimizing-descriptions>
- Skill Quickstart：<https://agentskills.io/skill-creation/quickstart>
- Anthropic 官方 `skill-creator`：<https://github.com/anthropics/skills/tree/main/skills/skill-creator>

> 本规范应优先以 Agent Skills 官方规范为准。由于不同 Agent 客户端可能增加自己的目录约定和扩展字段，实际部署时还应同时检查目标客户端的官方文档。
