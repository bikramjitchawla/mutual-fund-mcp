from __future__ import annotations


class FundError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_response(self) -> dict:
        return {
            "success": False,
            "error": {"code": self.code, "message": self.message},
        }

