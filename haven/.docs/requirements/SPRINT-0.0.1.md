# Haven 0.0.1 需求文档 — 项目骨架与基础设施

> **目标：项目能跑起来，hello world 对话能通。**
> 版本：0.0.1 · 状态：已确认 · 预计 11 条需求

---

## 0.0.1 交付目标

```text
FastAPI 项目启动 → SQLite 数据库建表 → LLM 网关可调用 → 基础对话跑通
```

本版本不涉及任何业务功能（建档、血压等），只搭骨架。

---

## 一、基础设施

- [x] **S10.1 配置管理** — pydantic-settings 集中管理环境变量、模型参数、功能开关。敏感配置不得硬编码
- [ ] **S10.2 日志系统** — JSON 结构化日志，DEBUG/INFO/WARNING/ERROR/CRITICAL 分级。不得含健康数据明文
- [x] **S10.3 数据库管理** — SQLAlchemy + Alembic 迁移。MVP 用 SQLite（WAL 模式），建表脚本就绪
- [x] **S10.4 LLM 网关** — 统一调用接口，支持模型选择、参数配置、重试（指数退避）、超时、速率限制。DeepSeek / OpenAI 兼容
- [x] **S10.5 异步框架** — asyncio + FastAPI，单进程 50+ 并发
- [x] **S10.7 API 文档** — FastAPI 自动生成 OpenAPI（Swagger UI）

## 二、会话管理基础

- [x] **S8.1 会话创建与标识** — 每次对话创建唯一 session_id
- [x] **S8.4 会话状态机** — 状态：正常对话 / 健康建档 / 紧急响应 / 体征录入。状态转换逻辑清晰

## 三、记忆系统基础

- [x] **S1.1 用户画像存储** — 持久化存储，所有修改记录时间戳和版本
- [x] **S1.2 健康时间线存储** — 按时间顺序存储，支持按用户+时间范围查询
- [x] **S1.8 记忆隔离** — 不同用户数据严格隔离

## 四、数据实体建表

- [ ] **D1 User** — id、haven_owner_id、status、created_at
- [x] **D2 HealthProfile** — id、user_id、nickname、birth_date、gender、height_cm、weight_kg 等
- [x] **D3 DiseaseRecord** — id、user_id、disease_name、icd10_code、diagnosis_date、severity
- [x] **D8 VitalRecord** — id、user_id、vital_type、systolic、diastolic、unit、measured_at
- [x] **D13 AuditLog** — id、timestamp、subject_pseudonym、event_type、rule_version
- [x] **D15 ConsentRecord** — id、user_id、policy_version、scope、action、recorded_at
- [ ] **D16 SafetyEvent** — id、user_id、rule_version、trigger_reason、risk_level
- [ ] **D19 DataSubjectRequest** — id、user_id、request_type、scope、status、deadline
- [ ] **D20 SafetyRuleVersion** — id、rule_summary、region、version、effective_date、expiry_date

## 五、代码质量

- [ ] **NF5.1 代码质量** — mypy strict mode + ruff，CI 强制检查
- [ ] **NF5.4 代码规范** — ruff 自动格式化 + .editorconfig，CI 强制检查
- [x] **NF6.1 数据库可替换** — SQLAlchemy ORM 抽象层
- [x] **NF6.2 模型可替换** — LLM Gateway 抽象层，换模型仅改配置

---

## 0.0.1 不做

- 不建健康档案（0.0.2）
- 不实现 Agent 决策循环（0.0.2）
- 不录入血压数据（0.0.3）
- 不做安全兜底（0.0.3）

---

## 验收标准

- [x] `haven web` 启动成功，Swagger UI 可访问
- [x] SQLite 数据库自动创建，所有表就绪
- [x] 调用 LLM Gateway 能拿到回复
- [ ] mypy + ruff 检查通过