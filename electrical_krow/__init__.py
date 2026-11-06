"""电子电器 · SOR填表：登录后出表。

出表流水线仍在 electrical。本包负责登录，并把识别请求转到指定场所的模型服务。
交付两种壳：客户端（127.0.0.1）与场所网页（内网 nginx）。不把填表改成开放式 Agent。
"""

from electrical_krow.config import Settings, load_settings
from electrical_krow.errors import ConfigError, LLMError, LoginError
from electrical_krow.llm import ChatResult, complete
from electrical_krow.login import AuthSession, login_with_api_key, login_with_password

__all__ = [
    "AuthSession",
    "ChatResult",
    "ConfigError",
    "LLMError",
    "LoginError",
    "Settings",
    "complete",
    "load_settings",
    "login_with_api_key",
    "login_with_password",
]

# 与 pyproject.toml 的 version 同步；Windows 包不带 pyproject，「关于」页从这里读
__version__ = "0.1.1"
