import json

config_cache = {}

def get_config(path):
    global config_cache
    if path in config_cache:
        return config_cache[path]
    
    # 1. Open the config file
    with open('./config.txt', 'r', encoding='utf-8') as config_file:
        # 2. Read the entire file content and parse it as JSON
        config_cache = json.load(config_file)

    return config_cache[path]