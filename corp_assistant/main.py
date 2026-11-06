import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from sqlalchemy import text
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from corp_assistant.api import router
from corp_assistant.config import get_settings
from corp_assistant.errors import AppError
from corp_assistant import knowledge, store
from corp_assistant.logging_setup import setup_logging

logger = logging.getLogger(__name__)
INDEX_FILE = Path(__file__).resolve().parent / "static" / "index.html"


def create_app() -> FastAPI:
    setup_logging()
    store.init_db()
    store.seed()
    knowledge.load()
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="企业内部助手示例。鉴权、工单、知识库、审计和 LangChain 工具调用都只做最小实现。",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "%s %s %s %.0fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        request_id = getattr(request.state, "request_id", "")
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "request_id": request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError):
        request_id = getattr(request.state, "request_id", "")
        return JSONResponse(
            status_code=422,
            content={
                "detail": "参数不正确",
                "errors": jsonable_encoder(exc.errors()),
                "request_id": request_id,
            },
        )

    @app.get("/")
    def index():
        return FileResponse(INDEX_FILE)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        try:
            with store.get_conn() as conn:
                conn.execute(text("SELECT 1")).fetchone()
        except Exception as exc:
            raise AppError(503, f"数据库不可用: {exc}") from exc
        return {"status": "ready"}

    app.include_router(router)
    logger.info(
        "database %s:%s/%s",
        settings.mysql_host,
        settings.mysql_port,
        settings.mysql_database,
    )
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
