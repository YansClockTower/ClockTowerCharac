import json
import os

config_cache = {}

_SECRETS_KEYS = ("secret_key", "resend_api_key")
_CONFIG_PATH = "./config.txt"
_SECRETS_PATH = "./secrets.txt"


def _load_json_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _load_merged_config():
    """合并 config.txt 与 secrets.txt（后者覆盖同名键）。"""
    merged = _load_json_file(_CONFIG_PATH)
    if os.path.isfile(_SECRETS_PATH):
        secrets = _load_json_file(_SECRETS_PATH)
        for key in _SECRETS_KEYS:
            if key in secrets:
                merged[key] = secrets[key]
        # 也允许 secrets 里放其它私密项
        for key, value in secrets.items():
            if key not in merged:
                merged[key] = value
    return merged


def get_config(path):
    global config_cache
    if path in config_cache:
        return config_cache[path]

    config_cache = _load_merged_config()
    return config_cache[path]


def clear_config_cache():
    """测试或热更新时清空缓存。"""
    global config_cache
    config_cache = {}
