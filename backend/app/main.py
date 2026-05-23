import json
import os
import time

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request as FastAPIRequest
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from ._limiter import limiter
from .debug import router as debug_router
from .routes import router as app_router


async def _rate_limit_handler(_: FastAPIRequest, __: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "detail": {
                "code": "rate_limit_exceeded",
                "message": "リクエストが多すぎます。しばらく時間をおいてから再試行してください。",
            }
        },
    )

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]

app = FastAPI(title="GPSアート作成機 API", version="0.1.0")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)


@app.middleware("http")
async def _log_optimize(request: FastAPIRequest, call_next):
    if request.url.path != "/api/optimize":
        return await call_next(request)
    t0 = time.monotonic()
    response = await call_next(request)
    print(
        json.dumps({
            "event": "optimize",
            "status": response.status_code,
            "duration_ms": round((time.monotonic() - t0) * 1000),
        }),
        flush=True,
    )
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.getenv("APP_ENV", "production") == "development":
    app.include_router(debug_router, prefix="/api/debug", tags=["debug"])
app.include_router(app_router, prefix="/api", tags=["app"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
