"""Configuration-related exceptions."""


class ConfigError(Exception):
    def __init__(self, message: str, path: str | None = None, suggestion: str | None = None):
        self.message = message
        self.path = path
        self.suggestion = suggestion
        parts = [message]
        if path:
            parts.insert(0, f"[{path}]")
        if suggestion:
            parts.append(f"提示: {suggestion}")
        super().__init__(" ".join(parts))
