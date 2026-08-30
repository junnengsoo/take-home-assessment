from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from lead_api.auth import AttorneyIdentity, current_attorney
from lead_api.config import get_settings
from lead_api.database import database
from lead_api.lead_queue import (
    DEFAULT_PAGE_SIZE,
    attorney_payload,
    current_attorney_payload,
    lead_queue_payload,
    normalize_email_search,
    parse_assignment,
    parse_cursor,
    parse_page_size,
    parse_scope,
    parse_status,
)
from lead_api.leads import submit_lead
from lead_api.problems import ProblemError, problem, problem_error_handler

CURRENT_ATTORNEY = Depends(current_attorney)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    await database.connect(settings)
    try:
        yield
    finally:
        await database.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Lead Intake API", version="0.1.0", lifespan=lifespan)
    app.add_exception_handler(ProblemError, problem_error_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready")
    async def ready():
        current_settings = get_settings()
        if not current_settings.required_configured:
            return problem(
                503,
                "Configuration incomplete",
                "Required API configuration is missing.",
                "configuration_incomplete",
            )
        if not await database.ready():
            return problem(
                503,
                "PostgreSQL unavailable",
                "The API could not verify PostgreSQL connectivity.",
                "postgres_unavailable",
            )
        return {"status": "ready"}

    @app.get("/api/v1/attorneys/me")
    async def legacy_me(attorney: AttorneyIdentity = CURRENT_ATTORNEY) -> dict[str, str]:
        return current_attorney_payload(attorney)

    @app.get("/api/v1/admin/attorneys/me")
    async def me(attorney: AttorneyIdentity = CURRENT_ATTORNEY) -> dict[str, str]:
        return current_attorney_payload(attorney)

    @app.get("/api/v1/admin/attorneys")
    async def attorneys(_: AttorneyIdentity = CURRENT_ATTORNEY) -> list[dict[str, str]]:
        return [attorney_payload(row) for row in await database.list_attorneys()]

    @app.get("/api/v1/admin/leads/counts")
    async def lead_counts(attorney: AttorneyIdentity = CURRENT_ATTORNEY) -> dict[str, int]:
        return await database.lead_queue_counts(current_attorney_id=attorney.id)

    @app.get("/api/v1/admin/leads")
    async def leads(
        scope: str = "my",
        status: Optional[str] = None,
        assignment: Optional[str] = None,
        q: Optional[str] = None,
        cursor: Optional[str] = None,
        page_size: int = Query(default=DEFAULT_PAGE_SIZE, alias="pageSize"),
        attorney: AttorneyIdentity = CURRENT_ATTORNEY,
    ) -> dict[str, object]:
        parsed_scope = parse_scope(scope)
        parsed_status = parse_status(status)
        parsed_assignment = parse_assignment(assignment)
        parsed_page_size = parse_page_size(page_size)
        parsed_cursor = parse_cursor(cursor)
        search_email = normalize_email_search(q)
        counts = await database.lead_queue_counts(current_attorney_id=attorney.id)
        rows = await database.list_leads(
            current_attorney_id=attorney.id,
            scope=parsed_scope,
            status=parsed_status,
            assignment=parsed_assignment,
            search_email=search_email,
            cursor=parsed_cursor,
            page_size=parsed_page_size,
        )
        return lead_queue_payload(rows, page_size=parsed_page_size, counts=counts)

    app.post("/api/v1/leads", status_code=201)(submit_lead)

    return app


app = create_app()
