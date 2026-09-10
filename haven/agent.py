"""健健（Haven）—— 0.0.1 个人高血压管理 Managed Deep Agent。

- 身份：**单租户（一个部署 = 一个人，见 ADR-006）**。`identity.py` 只回答
  "能不能进"（LangSmith API key 认证）；"进来的是谁"由配置 `HAVEN_OWNER_ID`
  决定 —— 运行时注入的身份不参与授予，只用于否决真正的 `person` 身份
  （见 `storage/database.py:caller_user_id`）。
- **无 `memory.py`**：MDA 记忆（`define_memory`）是**部署级共享**的，一个
  部署里所有调用者读写同一棵树，健康数据绝不写入。
- 记忆注入 = `middleware/memory_context.py`：每次模型调用前，从库内业务表
  **确定性组装**该用户的数据摘要并入 system prompt（B2 / S1.6），只读、
  不落库、不进线程历史 —— 它和 MDA 记忆、和根目录 `memory.py` 都不是
  一回事，勿混。跨会话连续性 = 持久线程 + 库内业务表（user_id 隔离）。
- 中间件顺序：紧急输入扫描在最外层（先于一切 LLM 处理），命令路由、
  输出安全依次在后，记忆注入在安全中间件内侧（它只往 system prompt
  追加内容块，不重写，见 `middleware/memory_context.py` 模块头）。
- 中断门：异常血压确认与数据删除需人工批准后才执行工具
  （`interrupt_on`），配合工具的确定性闸门（待确认行匹配）。
"""

from managed_deepagents import define_deep_agent

from config import get_settings
from middleware.commands import command_middleware
from middleware.emergency_input import emergency_input_middleware
from middleware.memory_context import memory_context_middleware
from middleware.output_safety import output_safety_middleware
from tools.account import delete_my_data
from tools.consent import consent_status, get_consent_policy, record_consent
from tools.onboarding import (
    get_health_profile,
    save_health_profile,
    save_onboarding_draft,
)
from tools.trends import get_seven_day_trend
from tools.vitals import (
    confirm_abnormal_blood_pressure,
    get_pending_blood_pressure,
    record_blood_pressure,
)

agent = define_deep_agent(
    name="haven",
    model=get_settings().agent_model,
    tools=[
        get_consent_policy,
        consent_status,
        record_consent,
        get_health_profile,
        save_health_profile,
        save_onboarding_draft,
        record_blood_pressure,
        get_pending_blood_pressure,
        confirm_abnormal_blood_pressure,
        get_seven_day_trend,
        delete_my_data,
    ],
    middleware=[
        emergency_input_middleware,  # 最外层：急救词优先于一切命令
        command_middleware,  # /hello /help /consent /cancel 确定性路由
        output_safety_middleware,
        memory_context_middleware,  # 只追加 system prompt 内容块，放其内侧
    ],
    interrupt_on={
        "confirm_abnormal_blood_pressure": True,
        "delete_my_data": True,
    },
)
