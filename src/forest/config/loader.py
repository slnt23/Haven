import os
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf, DictConfig, ListConfig


def _load_dotenv() -> None:
    """Load .env file into os.environ so get_model_config can read API keys."""
    env_file = Path(__file__).resolve().parent.parent.parent.parent / ".env"
    if not env_file.is_file():
        return
    with open(env_file, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()

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
