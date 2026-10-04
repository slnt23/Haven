# Haven 0.0.1 需求文档 — 项目骨架与基础设施

> **⚠️ 历史归档**：本文档描述 MDA 重写前的旧架构（FastAPI / 自建服务）与当时的
> 计划，**不适用于当前版本**，`[x]` 不代表当前已实现。本次仅定点修正与现行能力
> 直接冲突的条目与字段表，其余保留原文。现行实现以 [README](../../README.md) 与代码为准。

> **目标：项目能跑起来，hello world 对话能通。**
> 版本：0.0.1 · 状态：已确认 · 需求 28 条（含验收标准 4 条）

---

## 0.0.1 交付目标

```text
MDA 工程结构就绪 → 配置可加载 → SQLite 懒建表 → 模型可调用 → 基础对话跑通
```

本版本不涉及任何业务功能（建档、血压等），只搭骨架。

---

## 一、基础设施

- [x] **S10.1 配置管理** — pydantic-settings 集中管理环境变量、模型参数、功能开关。敏感配置不得硬编码
- [ ] **S10.2 日志系统** — JSON 结构化日志，DEBUG/INFO/WARNING/ERROR/CRITICAL 分级。不得含健康数据明文
- [x] **S10.3 数据库管理** — SQLAlchemy 异步 + SQLite，首笔工具调用懒初始化建表（`Base.metadata.create_all`）。**无 Alembic 迁移、无 WAL 配置**（后续需要时再评估）
- [ ] **S10.4 LLM 网关**（已废弃）— 无自建网关；模型经 langchain-deepseek 直连，由 `.env` 的 `HAVEN_MODEL` 切换。重试/超时/限流由平台侧承担，仓库不可核对
- [ ] **S10.5 异步框架**（不适用）— 无自建服务；并发由平台托管，仓库不可核对。asyncio 仅用于工具内部
- [ ] **S10.7 API 文档**（不适用）— 无 FastAPI/OpenAPI；接口面由平台与 Studio 提供

## 二、会话管理基础

- [ ] **S8.1 会话创建与标识**（不适用）— 无 session_id；跨会话连续性 = 平台持久线程 + 库内业务表
- [ ] **S8.4 会话状态机**（不适用）— 无四态状态机；现行确定性状态 = 待确认血压行 + 建档草稿（`bp_pending_confirmations` / `onboarding_drafts`）

## 三、记忆系统基础

- [x] **S1.1 用户画像存储** — 持久化存储，含 `created_at` / `updated_at`（**无独立版本列**）
- [x] **S1.2 健康时间线存储** — 按时间顺序存储，支持按用户+时间范围查询
- [x] **S1.8 记忆隔离** — 不同用户数据严格隔离

## 四、数据实体建表

- [ ] **D1 User** — id、haven_owner_id、status、created_at
- [x] **D2 HealthProfile** — id、user_id、nickname、birth_date、gender、height_cm、weight_kg 等
- [x] **D3 DiseaseRecord** — disease_id、user_id、disease_name、diagnosed_date、severity、status、notes（**无 icd10_code**；疾病仅精确匹配「高血压」）
- [x] **D8 血压记录（blood_pressure_records）** — record_id、user_id、systolic、diastolic、measured_at、source、is_abnormal、notes（**无 vital_type / unit**）
- [x] **D13 AuditLog（audit_logs）** — audit_id、subject_key、event_type、event_summary、rule_version、created_at（**无 timestamp / subject_pseudonym**；`subject_key` 为去标识散列）
- [x] **D15 ConsentRecord（consent_records）** — consent_id、user_id、policy_version、scope、consented_at（**无 action / recorded_at**；同意为一次性追加写，无撤回）
- [ ] **D16 SafetyEvent** — id、user_id、rule_version、trigger_reason、risk_level
- [ ] **D19 DataSubjectRequest** — id、user_id、request_type、scope、status、deadline
- [ ] **D20 SafetyRuleVersion** — id、rule_summary、region、version、effective_date、expiry_date

## 五、代码质量

- [ ] **NF5.1 代码质量** — mypy strict mode + ruff，CI 强制检查
- [ ] **NF5.4 代码规范** — ruff 自动格式化 + .editorconfig，CI 强制检查
- [x] **NF6.1 数据库可替换** — SQLAlchemy ORM 抽象层
- [x] **NF6.2 模型可替换** — 换模型仅改 `.env` 的 `HAVEN_MODEL`（经 MDA 装配，无自建网关抽象层）

---

## 0.0.1 不做

- 不建健康档案（0.0.2）
- 不实现 Agent 决策循环（0.0.2）
- 不录入血压数据（0.0.3）
- 不做安全兜底（0.0.3）

---

## 验收标准

- [ ] `haven web` 启动成功，Swagger UI 可访问（不适用：入口为 `mda dev` / `mda deploy`，界面为 Studio）
- [x] SQLite 数据库自动创建，所有表就绪
- [x] 模型可调用（经 MDA 运行时 + langchain-deepseek，无自建网关）
- [ ] mypy + ruff 检查通过