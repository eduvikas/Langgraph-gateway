"""OpenAI-shaped error envelopes, so a client's existing error handling
(checking error.type / error.code) doesn't need an AI Gateway-specific path."""
from fastapi import HTTPException


def openai_error(status_code: int, message: str, error_type: str,
                  code: str | None = None, retry_after: str | None = None) -> HTTPException:
    # Budget and policy rejections are not transient: retrying can't succeed, and
    # the OpenAI SDK retries 429s by default (sleeping Retry-After seconds, twice),
    # which would freeze a blocked agent for minutes. x-should-retry: false is the
    # header the SDK honors to skip retries.
    headers = {"x-should-retry": "false"}
    if retry_after:
        headers["Retry-After"] = retry_after
    return HTTPException(
        status_code=status_code,
        detail={"error": {"message": message, "type": error_type, "code": code}},
        headers=headers,
    )
