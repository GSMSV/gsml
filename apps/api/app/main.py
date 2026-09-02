import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .db import init_db
from .errors import OpenAIError, openai_error_response
from .routers import auth, keys, me, openai_proxy, usage
from .scheduler import catch_up_resets, start_scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    catch_up_resets()
    scheduler = start_scheduler()

    # Balancer 시작 (upstream.yml 파싱 + 헬스체크 태스크)
    from .upstream import init_balancer
    balancer = init_balancer()
    balancer.start()

    try:
        yield
    finally:
        await balancer.stop()
        scheduler.shutdown(wait=False)


app = FastAPI(title="GSML API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-RateLimit-Limit-Credits",
        "X-RateLimit-Remaining-Credits",
        "X-RateLimit-Limit-Tokens",
        "X-RateLimit-Remaining-Tokens",
    ],
)


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    logger.warning(
        "HTTPException endpoint=%s status_code=%d detail=%s",
        request.url.path,
        exc.status_code,
        exc.detail,
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(OpenAIError)
async def _openai_error_handler(request: Request, exc: OpenAIError) -> JSONResponse:
    logger.warning(
        "OpenAIError endpoint=%s status_code=%d detail=%s",
        request.url.path,
        exc.status_code,
        exc.detail,
    )
    return openai_error_response(exc)


@app.get("/healthz")
def healthz():
    return {"ok": True}


app.include_router(auth.router)
app.include_router(me.router)
app.include_router(keys.router)
app.include_router(usage.router)
app.include_router(openai_proxy.router)
