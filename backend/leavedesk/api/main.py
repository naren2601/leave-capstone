"""The FastAPI application.

Run it from the backend folder:

    uvicorn leavedesk.api.main:create_app --factory --reload

Then open http://localhost:8000/docs
"""

import logging
from collections.abc import Callable
from datetime import date

from fastapi import FastAPI

from leavedesk.api.errors import register_error_handlers
from leavedesk.api.middleware import RequestContextMiddleware
from leavedesk.api.routes import auth, leave, notifications
from leavedesk.api.settings import Settings, get_settings
from leavedesk.api.state import build_state


def create_app(settings: Settings | None = None, today: Callable[[], date] = date.today) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    app = FastAPI(
        title="LeaveDesk API",
        version="0.2.0",
        description="Apply for leave, approve or reject it, and get notified.",
        # Hide the interactive docs in production.
        docs_url="/docs" if settings.environment == "dev" else None,
        redoc_url=None,
    )
    app.state.leavedesk = build_state(settings, today)

    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(leave.router)
    app.include_router(notifications.router)
    return app
