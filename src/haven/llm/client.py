from langchain_openai import ChatOpenAI

from haven.config.settings import Settings

settings = Settings()

_model = None


def _get_model(temperature=0.3, max_tokens=1024):
    global _model
    if _model is None:
        _model = ChatOpenAI(
            base_url="https://api.deepseek.com/v1",
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    return _model


def _make_model(temperature=0.3, max_tokens=1024):
    return ChatOpenAI(
        base_url="https://api.deepseek.com/v1",
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def is_available():
    return settings.llm_api_key is not None and len(settings.llm_api_key) > 0