"""LLM 回复生成 —— 在安全边界内用大模型生成自然对话。

设计原则：
- 严格限定角色范围（慢病管理助手），超出范围的话题不生成
- 禁止诊断/处方/用药建议，输出还会过 filter_output 二次拦截
- LLM 不可用时返回 None，调用方走硬编码兜底
- 所有 prompt 从 prompts/*.md 读取，改文案不用动代码
"""

import json

from haven.llm.client import _make_model, is_available
from haven.llm.prompts import load_prompt


async def generate_response(scene: str, user_message: str = "", **context) -> str | None:
    if not is_available():
        return None

    identity = load_prompt("identity")
    scene_prompt = load_prompt(scene)

    if not scene_prompt:
        return None

    context_json = json.dumps(context, ensure_ascii=False) if context else ""

    try:
        model = _make_model(temperature=0.7, max_tokens=512)
        messages = [
            {"role": "system", "content": identity},
            {"role": "system", "content": scene_prompt},
        ]
        if context_json:
            messages.append({
                "role": "system",
                "content": f"当前上下文数据：\n{context_json}",
            })
        if user_message:
            messages.append({"role": "user", "content": user_message})
        else:
            messages.append({"role": "user", "content": "请根据以上场景和上下文生成回复。"})

        result = await model.ainvoke(messages)
        return result.content.strip() if hasattr(result, "content") else str(result).strip()
    except Exception:
        return None