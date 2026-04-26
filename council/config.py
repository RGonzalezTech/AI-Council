import os
from typing import Dict

# Centralized model registry
# Format: {friendly_name: full_litellm_path}
MODELS: Dict[str, str] = {
    "deepseek": "openrouter/deepseek/deepseek-v3.2",
    "gemini-flash": "google/gemini-2.5-flash",
    "gemini-pro": "google/gemini-2.5-pro",
}

# The default model name to use (can be overridden by environment variable)
DEFAULT_MODEL_NAME = os.getenv("COUNCIL_MODEL", "deepseek")

# Resolve the actual LiteLLM string for the default
DEFAULT_MODEL = MODELS.get(DEFAULT_MODEL_NAME, DEFAULT_MODEL_NAME)

def resolve_model(model_str: str) -> str:
    """
    Resolve a friendly model name to its full path.
    If the string is already a full path (contains '/'), returns it as-is.
    """
    if not model_str:
        return DEFAULT_MODEL
    
    # If it looks like a full provider/model string, use it directly
    if "/" in model_str:
        return model_str
        
    return MODELS.get(model_str.lower(), model_str)
