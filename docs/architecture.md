# Haven 项目架构

基于 Python 3.14+、LangChain 与 deepagents 构建的多智能体交互框架。人格由 Skill 定义（`.md` 文件），领域能力按需激活。

## 目录结构

```
haven/
├── pyproject.toml                  # 项目元信息，haven 命令入口
├── .env                            # 环境变量（LLM Key、SMTP 凭证等）
├── skills/                         # Skill 定义（.md 文件，拖入即用）
│   ├── haven.md                    # 默认人格 — 健健（default: true）
│   ├── code_review.md              # 代码审查
│   ├── translation.md              # 翻译
│   ├── summarization.md            # 摘要
│   └── data_analysis.md            # 数据分析
│
├── src/forest/
│   ├── config/                     # 配置层
│   │   ├── settings.py             # Pydantic BaseSettings 单例
│   │   ├── loader.py               # YAML 配置加载（OmegaConf）
│   │   └── models.yaml             # LLM 模型定义
│   │
│   ├── core/                       # 核心框架层
│   │   ├── base_agent.py           # BaseAgent 抽象基类 + skill 集成
│   │   ├── tool_registry.py        # 工具注册中心（装饰器模式）
│   │   ├── memory.py               # AgentMemory 对话记忆
│   │   └── rag.py                  # RAGEngine 检索增强生成
│   │
│   ├── skills/                     # Skill 系统
│   │   ├── base_skill.py           # BaseSkill 数据类
│   │   ├── loader.py               # SkillLoader — 扫描目录，解析 YAML frontmatter
│   │   └── registry.py             # SkillRegistry（装饰器模式）
│   │
│   ├── agents/                     # Agent 层
│   │   ├── general.py              # GeneralAgent — 唯一通用 agent
│   │   └── orchestrator.py         # OrchestratorAgent — 多 agent 编排
│   │
│   ├── tools/                      # 工具层
│   │   ├── web_search.py           # 网络搜索
│   │   ├── file_ops.py             # 文件读写
│   │   ├── code_exec.py            # 代码执行
│   │   ├── email_tool.py           # 邮件发送
│   │   ├── medical.py              # 医学知识查询
│   │   └── rag_search.py           # RAG 知识库检索
│   │
│   ├── workflows/                  # 工作流层
│   │   ├── research_flow.py        # 调研 → 总结
│   │   ├── dev_flow.py             # 方案 → 编码
│   │   └── diagnosis_flow.py       # 症状分析 → 诊断
│   │
│   ├── cli/                        # CLI 交互层
│   │   ├── main.py                 # haven 命令入口
│   │   └── app.py                  # HavenApp REPL 循环
│   │
│   └── services/                   # 服务层
│       └── email_service.py        # EmailService 邮件后台服务
│
├── scripts/                        # 独立运行脚本
│   ├── run_agent.py
│   ├── run_email_service.py
│   └── eval.py
│
├── tests/                          # 测试
│   ├── test_agents/
│   ├── test_tools/
│   └── test_workflows/
│
└── docs/
    ├── architecture.md             # 本文档
    ├── haven_class.png             # 类图
    ├── haven_package.png           # 包图
    └── haven_sequence.png          # 时序图
```

## 核心设计理念

**两个 Agent 类型，无数种能力：**

```
Agent（管"怎么跑"）          Skill（管"怎么想"）
─────────────────────      ─────────────────────
GeneralAgent        ←──    haven.md         （默认人格，始终在线）
OrchestratorAgent   ←──    code_review.md   （按需激活，关键词匹配）
                            translation.md   （按需激活）
                            *.md             （拖入 skills/ 即用）
```

- **人格** = 默认 Skill（`haven.md`）注入 system prompt
- **领域能力** = 按需 Skill，用户输入触发关键词时临时注入 prompt
- **新能力** = 写一个 `.md` 文件，零代码

## 分层详解

### 1. 配置层 `config/`

**`settings.py`** — 使用 `pydantic-settings` 从 `.env` 读取，全局单例。核心配置项：

```
DEEPSEEK_API_KEY=sk-xxx
OPENAI_API_KEY=sk-xxx
AGENT_DEFAULT_MODEL=deepseek-v4-pro
SKILL_DIRECTORY=skills          # .md skill 文件目录
```

**`models.yaml`** — LLM 模型档：`deepseek-v4-pro`、`gpt-4o`、`gpt-4o-mini`。

**`loader.py`** — OmegaConf 加载 `models.yaml`，`get_model_config(name)` 将模型名解析为 `{provider, api_key, base_url, temperature, max_tokens}`。

### 2. 核心框架层 `core/`

**`BaseAgent`（ABC）**

所有 Agent 的基类：

| 方法 | 说明 |
|------|------|
| `_init_llm(model_name)` | 根据 provider 实例化 `ChatDeepSeek` 或 `ChatOpenAI` |
| `_build_system_prompt()` | 组装默认 skill 的 prompt 为 system prompt |
| `_invoke_llm(task, prompt, use_rag)` | 调用 LLM，可选 RAG 上下文注入 |
| `enable_skill(skill)` | 加载一个 skill 实例 |
| `load_skills_from_dir(dir)` | 扫描 `skills/*.md` 并自动注册 |
| `match_skills(task)` | 返回匹配当前任务关键词的按需 skill |

抽象方法：`run(task)` / `step(messages)`

**`ToolRegistry`** — 装饰器注册表，`@ToolRegistry.register("name")` 注册工具类。

**`AgentMemory`** — 基于 `deque(maxlen=100)` 的对话历史。

**`RAGEngine`** — OpenAI 兼容 embedding + `InMemoryVectorStore`，支持 `add_texts` / `add_files` / `add_directory` 导入，`retrieve(query)` 语义检索。

### 3. Skill 系统 `skills/`

**Skill 定位**：介于 Tool（原子操作）和 Agent（完整智能体）之间的可复用能力包。

**`.md` 文件格式：**

```markdown
---
name: code_review
description: 审查代码中的 bug 和安全漏洞
category: development
default: false              # true = 始终激活的人格 skill
trigger_keywords:
  - review
  - 审查
  - code review
---

## 角色：高级代码审查员
你是经验丰富的代码审查专家……
```

**`BaseSkill`** — 纯数据类，字段包括 `name`、`description`、`prompt`、`trigger_keywords`、`category`、`default`。

**`SkillLoader`** — 扫描目录下所有 `.md` 文件，解析 YAML frontmatter，实例化 `BaseSkill`。

**`SkillRegistry`** — 程序化注册（装饰器模式），与 `ToolRegistry` 同风格。

**激活机制：**

```
_build_system_prompt()
  └── 注入所有 default=true 的 skill.prompt     ← 人格（haven.md）

match_skills(task)
  └── 返回 trigger_keywords 匹配 task 的 skill   ← 领域能力（按需）
```

### 4. Agent 层 `agents/`

| Agent | 职责 |
|-------|------|
| `GeneralAgent` | 唯一通用 agent。人格由默认 skill 定义，领域能力由按需 skill 匹配。无硬编码角色 |
| `OrchestratorAgent` | 维护 `sub_agents` 字典，`run(task)` 广播给所有子 agent 并聚合结果 |

```python
from forest.agents import GeneralAgent, OrchestratorAgent

# 单 agent 模式
agent = GeneralAgent()
agent.load_skills_from_dir()
await agent.run("帮我审查这段代码")    # 自动匹配 code_review skill

# 编排模式
orchestrator = OrchestratorAgent()
orchestrator.register_agent("a", GeneralAgent("general"))
orchestrator.register_agent("b", GeneralAgent("general"))
await orchestrator.run("实现一个 CLI 工具")
```

### 5. CLI 交互层 `cli/`

**`HavenApp`** — 交互式 REPL，启动流程：

```
haven 命令
  → _init_agent()     → GeneralAgent 初始化，LLM 就绪
  → _load_skills()    → 扫描 skills/ 目录，区分默认/按需 skill
  → _print_banner()   → Haven (健健) — 多智能体交互框架
  → REPL 循环
       ├── /skills    → 列出已加载 skill（区分 [默认] / [按需]）
       ├── /clear     → 清空对话历史
       ├── /model     → 显示当前模型
       ├── /exit      → 退出
       └── 其他输入    → _chat()
            ├── _build_system_prompt()    ← 默认 skill
            ├── match_skills(input)       ← 按需匹配
            ├── memory.get_history()
            └── llm.ainvoke(messages)
```

每条消息都携带完整对话历史，实现多轮记忆。

### 6. 工作流层 `workflows/`

多个 `GeneralAgent` 实例串联执行：

| 工作流 | 流程 |
|--------|------|
| `ResearchFlow` | Agent A 研究 → Agent B 总结 |
| `DevFlow` | Agent A 方案 → Agent B 实现 |
| `DiagnosisFlow` | Agent A 医学调研 → Agent B 诊断 |

所有 agent 使用相同的 `GeneralAgent("general")`，差异化来自任务描述和按需 skill 匹配。

### 7. 服务层 `services/`

**`EmailService`** — 独立运行的邮件后台进程：

- **IMAP 轮询**：定时收取未读邮件，白名单过滤
- **Agent 回调**：邮件内容传递给 agent handler 处理并自动回复
- **SMTP 发送**：TLS/SSL 发送邮件
- **日报摘要**：定时发送每日汇总
- **状态持久化**：`processed_ids` 保存至 `.data/`

## 分层依赖关系

```
config/  ←── 所有层读取配置
   ↑
 core/   ←── agents/、skills/、tools/、workflows/、services/ 依赖
   ↑
 skills/ ←── core/（BaseSkill）+ 外部 skills/*.md 文件
   ↑
 agents/ ←── core/（BaseAgent）+ skills/（SkillLoader）
   ↑
cli/     ←── agents/（GeneralAgent）+ skills/（SkillLoader）
   ↑
workflows/ ←── agents/（GeneralAgent / OrchestratorAgent）
   ↑
services/  ←── agents/（回调）
```

## 扩展方式

| 需求 | 做法 | 改动量 |
|------|------|--------|
| 新领域能力 | `skills/` 下新建 `.md` 文件 | 零代码 |
| 新人格 | 新建 `.md`，设 `default: true` | 零代码 |
| 新工具 | `tools/` 新建类 + `@ToolRegistry.register` | 一个文件 |
| 新工作流 | `workflows/` 编排 `GeneralAgent` 实例 | 一个文件 |
| 新模型 | `models.yaml` 加条目 | 一行配置 |
| 新 Agent 类型 | 继承 `BaseAgent`，实现 `run()` / `step()` | 一个类 |

## UML 图

- [类图](haven_class.png) — 所有类的属性/方法/关系
- [包图](haven_package.png) — 模块分层与依赖方向
- [时序图](haven_sequence.png) — 对话交互完整流程
