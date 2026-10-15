"""Uniform error shape from docs/CONTRACT.md section 5."""


class RetconError(Exception):
    """Raised by core functions; MCP wrappers return `as_payload()` instead of raising."""

    def __init__(self, code, message, details=None):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.details = code, message, details or {}

    def as_payload(self):
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}
