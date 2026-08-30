from fastapi import Request
from fastapi.responses import JSONResponse


def problem(status: int, title: str, detail: str, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"https://lead-intake.local/problems/{code}",
            "title": title,
            "status": status,
            "detail": detail,
            "code": code,
        },
    )


class ProblemError(Exception):
    def __init__(self, status: int, title: str, detail: str, code: str) -> None:
        self.status = status
        self.title = title
        self.detail = detail
        self.code = code


async def problem_error_handler(_: Request, exc: ProblemError) -> JSONResponse:
    return problem(exc.status, exc.title, exc.detail, exc.code)
