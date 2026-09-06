from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from haven.agent.chat import handle_message
from haven.application.consent import get_policy, record_consent
from haven.application.vitals import BloodPressureData, record_blood_pressure
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


@app.get("/api/consent/policy")
async def get_consent_policy():
    policy = await get_policy()
    return JSONResponse({"policy": policy})


@app.get("/api/consent/status")
async def get_consent_status(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    from haven.application.consent import has_consented
    
    user_id = request.headers.get("X-User-ID", "00000000-0000-0000-0000-000000000001")
    consented = await has_consented(session, UUID(user_id))
    return JSONResponse({"consented": consented})


@app.post("/api/consent/agree")
async def agree_consent(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.headers.get("X-User-ID", "00000000-0000-0000-0000-000000000001")
    policy = await get_policy()
    record = await record_consent(session, UUID(user_id), policy_version="v1.0")
    return JSONResponse({"success": True, "policy_version": "v1.0"})


@app.post("/api/blood-pressure")
async def record_bp(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    body = await request.json()
    systolic = body.get("systolic")
    diastolic = body.get("diastolic")
    
    if not systolic or not diastolic:
        return JSONResponse({"error": "缺少收缩压或舒张压"}, status_code=400)
    
    user_id = request.headers.get("X-User-ID", "00000000-0000-0000-0000-000000000001")
    data = BloodPressureData(systolic=int(systolic), diastolic=int(diastolic))
    record = await record_blood_pressure(session, UUID(user_id), data)
    
    level = "normal"
    if systolic >= 180 or diastolic >= 120:
        level = "severe"
    elif systolic >= 160 or diastolic >= 100:
        level = "grade_3"
    elif systolic >= 140 or diastolic >= 90:
        level = "grade_2"
    elif systolic >= 130 or diastolic >= 85:
        level = "grade_1"
    elif systolic >= 120 or diastolic >= 80:
        level = "high_normal"
    
    return JSONResponse({
        "success": True,
        "systolic": systolic,
        "diastolic": diastolic,
        "level": level,
        "measured_at": record.measured_at.isoformat(),
    })


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/favicon.ico")
    async def favicon():
        return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")