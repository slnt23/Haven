from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from haven.application.emergency import check_emergency
from haven.safety.emergency import EmergencyLevel


class EmergencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "GET":
            return await call_next(request)

        body = await request.body()
        text = body.decode("utf-8", errors="replace")

        result = check_emergency(text)

        if result.is_emergency:
            return JSONResponse(
                status_code=200,
                content={
                    "emergency": True,
                    "message": result.response,
                    "reason": result.reason,
                },
            )

        if result.level == EmergencyLevel.SUSPICIOUS:
            request.state.emergency_suspicious = True
            request.state.emergency_reason = result.reason

        return await call_next(request)