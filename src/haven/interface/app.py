from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from haven.config.settings import Settings
from haven.infrastructure.database import close_db, init_db
from haven.infrastructure.logging import setup_logging
from haven.interface.middleware.audit import AuditMiddleware
from haven.interface.middleware.emergency import EmergencyMiddleware
from haven.interface.middleware.error_handler import ErrorHandlerMiddleware
from haven.interface.routes.chat import router as chat_router
from haven.interface.routes.consent import router as consent_router
from haven.interface.routes.profile import router as profile_router
from haven.interface.routes.trends import router as trends_router
from haven.interface.routes.vitals import router as vitals_router
from haven.llm.client import is_available

settings = Settings()
setup_logging(settings)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db(settings)
    if is_available():
        print(f"[Haven] LLM 已启用，模型: {settings.llm_model}")
    else:
        print("[Haven] LLM 未配置，使用关键词匹配兜底")
        print("[Haven] 请在 .env 文件中设置 OWL_DEEPSEEK_API_KEY=你的密钥")
    yield
    await close_db()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Haven - 个人慢病管理智能体",
        description="面向患者的长期陪伴型慢病管理智能体 API",
        version="0.0.1",
        lifespan=lifespan,
    )

    app.add_middleware(ErrorHandlerMiddleware)
    app.add_middleware(AuditMiddleware)
    app.add_middleware(EmergencyMiddleware)

    app.include_router(consent_router)
    app.include_router(profile_router)
    app.include_router(vitals_router)
    app.include_router(trends_router)
    app.include_router(chat_router)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.get("/", response_class=FileResponse)
        async def index():
            return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()