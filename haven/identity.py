"""Who may call this deployment —— 只回答"能不能进"，不回答"进来的是谁"。

**一个部署 = 一个人（单租户，见 .docs/adr/ADR-006）**：这里的认证是唯一的
准入闸门，而"本人是谁"由配置 `HAVEN_OWNER_ID` 决定（`config.py`），
见 `storage/database.py:caller_user_id`。

注意 LangSmith-key 模式没有"人"的概念：持有 workspace key 的任何人都能进，
且都会被标成 `kind: "service"` 平台主体 —— 所以要给家人用，是**再部署一个
实例**（不同 `HAVEN_OWNER_ID` + 不同库），而不是共享这一个。
"""

from managed_deepagents import auth, define_identity

# LangSmith workspace API keys authenticate callers through `x-api-key` while
# retaining MDA's thread and store authorization hooks.
#
# Managed identity gives every caller private threads and downstream
# credentials. Durable memory is not an identity axis — declare it in memory.py.
identity = define_identity(auth=auth.langsmith_api_key())
