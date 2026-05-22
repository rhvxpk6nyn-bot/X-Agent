"""Agent configuration. Load order: defaults → config.yaml → env vars."""

import os
import yaml
from pathlib import Path
from pydantic import BaseModel

AGENT_HOME = Path(os.environ.get("AGENT_HOME", Path.home() / ".agent"))
CONFIG_PATH = AGENT_HOME / "config" / "config.yaml"


class ModelConfig(BaseModel):
    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7


DEFAULT_MODELS = {
    "deepseek": ModelConfig(
        provider="deepseek", model="deepseek-chat",
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url="https://api.deepseek.com/v1",
    ),
    "qwen-vl": ModelConfig(
        provider="dashscope", model="qwen-vl-max",
        api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        max_tokens=2048,
    ),
    "ollama": ModelConfig(
        provider="ollama", model="llama3.2",
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    ),
}

KEY_ENV_MAP = {"deepseek": "DEEPSEEK_API_KEY", "qwen-vl": "DASHSCOPE_API_KEY"}
KEY_PROMPTS = {
    "deepseek": ("DeepSeek API Key", "https://platform.deepseek.com/api_keys"),
    "qwen-vl": ("Qwen-VL API Key (阿里云百炼)", "https://bailian.console.aliyun.com"),
}


class MemoryConfig(BaseModel):
    hot_max_tokens: int = 2000
    warm_max_retrieved: int = 5
    decay_half_life_days: float = 30.0
    access_multiplier: float = 1.2
    decay_floor: float = 0.05
    consolidation_pending_count: int = 15
    conflict_similarity_threshold: float = 0.85


class ToolConfig(BaseModel):
    allowed_commands: list[str] = ["*"]
    sandbox_enabled: bool = True
    max_execution_time_ms: int = 300_000
    mano_cua_enabled: bool = True


class Config(BaseModel):
    models: dict[str, ModelConfig] = DEFAULT_MODELS
    memory: MemoryConfig = MemoryConfig()
    tools: ToolConfig = ToolConfig()
    default_model: str = "deepseek"
    web_port: int = 9527
    web_host: str = "127.0.0.1"

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                data = yaml.safe_load(f) or {}
            if data.get("models"):
                for k, v in data["models"].items():
                    if isinstance(v, dict) and k in cfg.models:
                        cfg.models[k] = ModelConfig(**{**cfg.models[k].model_dump(), **v})
            for k in ["default_model", "web_port", "web_host"]:
                if k in data:
                    setattr(cfg, k, data[k])
        # Env vars override
        for name, env_var in KEY_ENV_MAP.items():
            env_val = os.environ.get(env_var, "")
            if env_val and name in cfg.models:
                cfg.models[name].api_key = env_val
        return cfg

    def save(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        models_dict = {}
        for name, mc in self.models.items():
            models_dict[name] = {
                "provider": mc.provider, "model": mc.model,
                "api_key": mc.api_key, "base_url": mc.base_url,
            }
        with open(CONFIG_PATH, "w") as f:
            yaml.dump({
                "default_model": self.default_model,
                "models": models_dict,
            }, f, allow_unicode=True)

    def set_key(self, name: str, key: str):
        if name in self.models:
            self.models[name].api_key = key
            self.save()

    def missing_keys(self) -> list[str]:
        return [n for n, mc in self.models.items() if not mc.api_key and n in KEY_ENV_MAP]


config = Config.load()
