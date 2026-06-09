"""FastAPI application entrypoint: wires routers, mounts static files, runs bootstrap."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.api import auth, dashboard, protected, users, rules, datasources, opinions, imports, alerts, tickets, reports, audit
from app.core.config import get_settings
from app.services.bootstrap import init_db
from app.web.routes import pages_router, web_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")

    static_dir = Path(__file__).resolve().parent.parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(auth.router)
    app.include_router(protected.router)
    app.include_router(dashboard.router)
    app.include_router(users.router)
    app.include_router(rules.router)
    app.include_router(datasources.router)
    app.include_router(opinions.router)
    app.include_router(imports.router)
    app.include_router(alerts.router)
    app.include_router(tickets.router)
    app.include_router(reports.router)
    app.include_router(audit.router)
    app.include_router(web_router)
    app.include_router(pages_router)

    @app.on_event("startup")
    def _on_startup() -> None:
        init_db()

    return app


app = create_app()
