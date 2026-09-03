from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from haven.application.degradation import (
    DB_DEGRADED_RESPONSE,
    LLM_DEGRADED_RESPONSE,
)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except ConnectionError:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "service_unavailable",
                    "message": DB_DEGRADED_RESPONSE,
                },
            )
        except Exception:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "service_unavailable",
                    "message": LLM_DEGRADED_RESPONSE,
                },
            )