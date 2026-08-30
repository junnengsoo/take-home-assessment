import logging
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import StreamingResponse

from lead_api.auth import AttorneyIdentity, current_attorney
from lead_api.config import get_settings
from lead_api.database import LeadVersionConflict, database
from lead_api.lead_detail import (
    lead_detail_payload,
    parse_lead_id,
    parse_resume_disposition,
    safe_content_disposition,
)
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
from lead_api.lead_status import LeadStatusMutation
from lead_api.leads import submit_lead
from lead_api.observability import configure_logging
from lead_api.problems import ProblemError, problem, problem_error_handler
from lead_api.storage import resume_storage

CURRENT_ATTORNEY = Depends(current_attorney)
logger = logging.getLogger(__name__)


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
    configure_logging(service="api", environment=settings.app_env)
    app = FastAPI(title="Lead Intake API", version="0.1.0", lifespan=lifespan)
    app.add_exception_handler(ProblemError, problem_error_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["Content-Disposition", "X-Request-ID"],
    )

    @app.middleware("http")
    async def correlate_and_log_requests(request: Request, call_next):
        correlation_id = request.headers.get("x-request-id") or str(uuid4())
        request.state.correlation_id = correlation_id
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            route_template = _route_template(request)
            logger.exception(
                "api_request_failed",
                extra={
                    "correlation_id": correlation_id,
                    "route_template": route_template,
                    "method": request.method,
                    "latency_ms": _latency_ms(started),
                    "actor_attorney_id": getattr(request.state, "actor_attorney_id", None),
                    "lead_id": _lead_id(request),
                },
            )
            raise

        response.headers.setdefault("X-Request-ID", correlation_id)
        logger.info(
            "api_request_completed",
            extra={
                "correlation_id": correlation_id,
                "route_template": _route_template(request),
                "method": request.method,
                "status": response.status_code,
                "latency_ms": _latency_ms(started),
                "actor_attorney_id": getattr(request.state, "actor_attorney_id", None),
                "lead_id": _lead_id(request),
            },
        )
        return response

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

    @app.get("/api/v1/admin/leads/{lead_id}")
    async def lead_detail(
        lead_id: str,
        _: AttorneyIdentity = CURRENT_ATTORNEY,
    ) -> dict[str, object]:
        parsed_lead_id = parse_lead_id(lead_id)
        row = await database.fetch_lead_detail(parsed_lead_id)
        if row is None:
            raise ProblemError(
                404,
                "Lead not found",
                "No Lead was found for the authenticated Attorney.",
                "lead_not_found",
            )
        return lead_detail_payload(row)

    @app.patch("/api/v1/admin/leads/{lead_id}/status")
    async def update_lead_status(
        request: Request,
        lead_id: str,
        mutation: LeadStatusMutation,
        attorney: AttorneyIdentity = CURRENT_ATTORNEY,
    ) -> dict[str, object]:
        parsed_lead_id = parse_lead_id(lead_id)
        correlation_id = getattr(request.state, "correlation_id", None) or str(uuid4())
        try:
            row = await database.update_lead_status(
                lead_id=parsed_lead_id,
                expected_version=mutation.version,
                desired_status=mutation.status,
                actor_attorney_id=attorney.id,
                correlation_id=correlation_id,
            )
        except LeadVersionConflict as exc:
            raise ProblemError(
                409,
                "Lead changed",
                "This Lead changed after it was loaded. Refresh and try again.",
                "lead_version_conflict",
            ) from exc
        if row is None:
            raise ProblemError(
                404,
                "Lead not found",
                "No Lead was found for the authenticated Attorney.",
                "lead_not_found",
            )
        logger.info(
            "lead_status_changed",
            extra={
                "correlation_id": correlation_id,
                "lead_id": parsed_lead_id,
                "actor_attorney_id": attorney.id,
                "status": mutation.status,
            },
        )
        return lead_detail_payload(row)

    @app.get("/api/v1/admin/leads/{lead_id}/resume")
    async def lead_resume(
        request: Request,
        lead_id: str,
        disposition: str = "attachment",
        attorney: AttorneyIdentity = CURRENT_ATTORNEY,
    ) -> StreamingResponse:
        parsed_lead_id = parse_lead_id(lead_id)
        parsed_disposition = parse_resume_disposition(disposition)
        row = await database.fetch_lead_detail(parsed_lead_id)
        if row is None:
            raise ProblemError(
                404,
                "Lead not found",
                "No Lead was found for the authenticated Attorney.",
                "lead_not_found",
            )

        content = await resume_storage.download(get_settings(), row["storage_object_key"])
        correlation_id = getattr(request.state, "correlation_id", None) or str(uuid4())
        await database.append_resume_download_audit_event(
            lead_id=parsed_lead_id,
            actor_attorney_id=attorney.id,
            correlation_id=correlation_id,
        )
        logger.info(
            "resume_streamed",
            extra={
                "correlation_id": correlation_id,
                "lead_id": parsed_lead_id,
                "actor_attorney_id": attorney.id,
                "resume_disposition": parsed_disposition,
                "content_type": row["content_type"],
            },
        )

        return StreamingResponse(
            iter([content]),
            media_type=row["content_type"],
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": safe_content_disposition(
                    original_filename=row["original_filename"],
                    requested_disposition=parsed_disposition,
                    content_type=row["content_type"],
                ),
                "X-Request-ID": correlation_id,
            },
        )

    app.post("/api/v1/leads", status_code=201)(submit_lead)

    return app


def _latency_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


def _lead_id(request: Request) -> str | None:
    value = request.path_params.get("lead_id")
    return value if isinstance(value, str) else None


app = create_app()
