"""电子电器 · SOR填表：登录与识别接入。

出表流水线仍在 electrical。本包只负责登录，并把识别请求转到指定场所的模型服务。
不把填表改成开放式 Agent。
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
