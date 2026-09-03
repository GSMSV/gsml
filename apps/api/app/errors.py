from fastapi import HTTPException
from fastapi.responses import JSONResponse


class OpenAIError(HTTPException):
    """OpenAI 표준 에러 포맷으로 응답되는 예외."""

    def __init__(self, status_code: int, message: str, type_: str, code: str):
        super().__init__(status_code=status_code, detail=message)
        self.message = message
        self.type_ = type_
        self.code = code


def openai_error_response(exc: OpenAIError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"message": exc.message, "type": exc.type_, "code": exc.code}},
    )


def invalid_api_key() -> OpenAIError:
    return OpenAIError(401, "Invalid API key.", "invalid_request_error", "invalid_api_key")


def expired_api_key() -> OpenAIError:
    return OpenAIError(401, "API key expired.", "invalid_request_error", "expired_api_key")


def insufficient_quota() -> OpenAIError:
    return OpenAIError(
        429, "Daily credit quota exceeded.", "insufficient_quota", "insufficient_quota"
    )


def rate_limited() -> OpenAIError:
    return OpenAIError(
        429, "Concurrent request limit exceeded.", "rate_limit_error", "rate_limit_exceeded"
    )


def upstream_error(detail: str = "Upstream LLM error.") -> OpenAIError:
    return OpenAIError(502, detail, "api_error", "upstream_error")


def service_unavailable(msg: str = "Service unavailable") -> OpenAIError:
    return OpenAIError(503, msg, "api_error", "service_unavailable")
