# Haven 0.0.1 需求追踪矩阵

> 状态：已确认
> 版本：0.0.1
> 范围来源：ADR-005

本表是 `0.0.1` 发布范围的权威清单。测试路径为计划位置；实现后必须替换为实际可运行测试，状态才可改为“已实现”。

| 交付项 | 需求来源 | 用户验收 | 计划测试 | 当前状态 |
| --- | --- | --- | --- | --- |
| 隐私政策与同意记录 | NF4.1、D15 | US-001、US-027 | `tests/acceptance/test_consent.py` | 已确认 |
| 高血压基础建档 | F1.1、F1.2、S1.1 | US-001 | `tests/acceptance/test_profile.py` | 已确认 |
| 手工血压录入 | F2.1、S3.2 | US-003 | `tests/acceptance/test_blood_pressure.py` | 已确认 |
| 范围、单位与逻辑校验 | S3.3 | US-023 | `tests/domain/test_vital_validation.py` | 已确认 |
| 异常值二次确认 | F2.4、S3.4 | US-024 | `tests/acceptance/test_abnormal_confirmation.py` | 已确认 |
| 重复提交幂等 | S10.3 | US-025 | `tests/acceptance/test_vital_idempotency.py` | 已确认 |
| 七日趋势 | F2.3、S4.1 | US-004 | `tests/acceptance/test_seven_day_trend.py` | 已确认 |
| 安全状态机与本地急救提示 | F5.6、F11.1、F11.2、S6.1、D16、D20 | US-013、US-028 | `tests/safety/test_emergency_flow.py` | 已确认 |
| 关键服务降级 | S9.7、NF2.3、NF2.4 | US-026 | `tests/acceptance/test_degradation.py` | 已确认 |
| 最小化审计 | F11.5、S6.7、NF3.7、D13 | US-013 | `tests/security/test_audit_minimization.py` | 已确认 |
| 数据删除请求 | F11.7、S6.8、NF4.3、D19 | US-021 | `tests/acceptance/test_deletion_request.py` | 已确认 |

## 发布检查

- 每行必须对应至少一个通过的自动化测试。
- 测试必须覆盖正常、非法输入、依赖故障和安全边界。
- 不允许使用真实患者数据作为测试夹具。
- 安全规则测试分别报告误报和漏报，不以“100% 可靠”作为验收表述。
- 任何新增 P0 必须先更新 ADR-005 或其替代 ADR，再更新本表。
