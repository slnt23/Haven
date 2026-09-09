"""健健（Haven）—— 0.0.1 个人高血压管理 Managed Deep Agent。

- 身份：`identity.py`（当前：LangSmith API key，单身份原型）。
- 无 `memory.py`：MDA 记忆为部署级共享，健康数据绝不写入；
  跨会话连续性 = 持久线程 + 库内业务表（user_id 隔离）。
- 中间件顺序：紧急输入扫描在最外层（先于一切 LLM 处理），输出安全在后。
- 中断门：异常血压确认与数据删除需人工批准后才执行工具
  （`interrupt_on`），配合工具的确定性闸门（待确认行匹配）。
"""

from managed_deepagents import define_deep_agent

from config import get_settings
from middleware.commands import command_middleware
from middleware.emergency_input import emergency_input_middleware
from middleware.output_safety import output_safety_middleware
from tools.account import delete_my_data
from tools.consent import consent_status, get_consent_policy, record_consent
from tools.onboarding import get_health_profile, save_health_profile
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
    ],
    interrupt_on={
        "confirm_abnormal_blood_pressure": True,
        "delete_my_data": True,
    },
)
