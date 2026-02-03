import os

if "HF_ENDPOINT" not in os.environ:
    os.environ["HF_ENDPOINT"] = "http://localhost:8080"

import huggingface_hub
from huggingface_hub import *

try:
    from huggingface_hub import constants
    constants.ENDPOINT = os.environ["HF_ENDPOINT"]
except (ImportError, AttributeError):
    pass

__all__ = getattr(huggingface_hub, "__all__", [])
globals().update({k: v for k, v in huggingface_hub.__dict__.items() if not k.startswith("__")})
