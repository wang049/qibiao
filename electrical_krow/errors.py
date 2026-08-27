"""本包错误。"""


class ElectricalKrowError(RuntimeError):
    pass


class ConfigError(ElectricalKrowError):
    pass


class LoginError(ElectricalKrowError):
    pass


class LLMError(ElectricalKrowError):
    pass
