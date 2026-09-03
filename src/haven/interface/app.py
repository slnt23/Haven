from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from haven.agent.chat import handle_message
from haven.config.settings import Settings
from haven.infrastructure.database import close_db, get_session, init_db
from haven.infrastructure.logging import setup_logging
from haven.llm.client import is_available

settings = Settings()
setup_logging(settings)

STATIC_DIR = Path(__file__).parent / "static"


async def startup():
    await init_db(settings)
    if is_available():
        print(f"[Haven] LLM 已启用，模型: {settings.llm_model}")
    else:
        print("[Haven] LLM 未配置，使用关键词匹配兜底")
        print("[Haven] 请在 .env 文件中设置 OWL_DEEPSEEK_API_KEY=你的密钥")


async def shutdown():
    await close_db()


app = FastAPI(
    title="Haven - 个人慢病管理智能体",
    version="0.0.1",
    on_startup=[startup],
    on_shutdown=[shutdown],
)


@app.post("/api/chat")
async def chat(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    body = await request.json()
    text = body.get("message", "").strip()
    user_id = request.headers.get("X-User-ID", "00000000-0000-0000-0000-000000000001")

    return await handle_message(text, session, UUID(user_id))


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")