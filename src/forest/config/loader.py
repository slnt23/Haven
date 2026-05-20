import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from omegaconf import OmegaConf, DictConfig, ListConfig

_env_file = Path(__file__).resolve().parent.parent.parent.parent / ".env"
load_dotenv(_env_file)

_config: DictConfig | None = None


def _load_config() -> DictConfig | None:
    global _config
    if _config is None:
        config_path = Path(__file__).parent / "models.yaml"
        _config = OmegaConf.load(config_path)
        OmegaConf.resolve(_config)
    return _config


def get_default_model() -> str:
    return str(_load_config().default_model)


def load_models_config() -> DictConfig | ListConfig:
    return _load_config().models


def get_model_config(model_name: str) -> dict[str, Any]:
    """Resolve a model name to its full configuration.

    API keys are read from environment variables.  The ``api_key_env`` field
    in *models.yaml* names the env var (e.g. ``DEEPSEEK_API_KEY``).  Users can
    set it in ``.env`` or their shell — no code changes needed when adding a
    new model.
    """
    models = load_models_config()
    model_cfg = models[model_name]

    api_key_env_name = str(model_cfg.api_key_env)
    api_key = os.environ.get(api_key_env_name, "")

    return {
        "name": model_name,
        "provider": str(model_cfg.provider),
        "api_key": api_key,
        "base_url": str(model_cfg.base_url),
        "temperature": float(model_cfg.temperature),
        "max_tokens": int(model_cfg.max_tokens),
    }
