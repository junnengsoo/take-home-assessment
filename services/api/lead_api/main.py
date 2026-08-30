from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lead_api.auth import AttorneyIdentity, current_attorney
from lead_api.config import get_settings
from lead_api.database import database
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
    async def me(attorney: AttorneyIdentity = CURRENT_ATTORNEY) -> dict[str, str]:
        return {
            "id": attorney.id,
            "email": attorney.email,
            "displayName": attorney.display_name,
        }

    app.post("/api/v1/leads", status_code=201)(submit_lead)

    return app


app = create_app()
