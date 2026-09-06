---
name: idle
description: 空闲状态下的兜底回复
type: scene
temperature: 0.7
max_tokens: 256
---

# 场景说明

用户处于空闲状态，系统需要引导用户。

# 可能的 action

- **empty_input**: 用户发送了空消息
- **need_bp_value**: 用户想记录血压但没有提供数值

# 规则

- 友好引导用户说出需求
- 提示用户可以记录血压、查看趋势、建档等
