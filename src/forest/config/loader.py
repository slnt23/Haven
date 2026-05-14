from pathlib import Path
from typing import Any

from omegaconf import OmegaConf, DictConfig, ListConfig

from .settings import settings


def _init_resolvers() -> None:
    OmegaConf.register_new_resolver(
        "default_model",
        lambda: settings.agent_default_model,
        replace=True,
    )


def load_models_config() -> DictConfig | ListConfig:
    config_path = Path(__file__).parent / "models.yaml"
    cfg = OmegaConf.load(config_path)
    OmegaConf.resolve(cfg)
    return cfg.models


def load_agents_config() -> DictConfig | ListConfig:
    _init_resolvers()
    config_path = Path(__file__).parent / "agents.yaml"
    cfg = OmegaConf.load(config_path)
    OmegaConf.resolve(cfg)
    return cfg.agents


def get_model_config(model_name: str) -> dict[str, Any]:
    """Resolve a model name to its full configuration."""
    models = load_models_config()
    model_cfg = models[model_name]

    api_key_env_name = str(model_cfg.api_key_env)
    api_key = getattr(settings, api_key_env_name.lower(), "")

    return {
        "name": model_name,
        "provider": str(model_cfg.provider),
        "api_key": api_key,
        "base_url": str(model_cfg.base_url),
        "temperature": float(model_cfg.temperature),
        "max_tokens": int(model_cfg.max_tokens),
    }
