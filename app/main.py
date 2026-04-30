from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import time
from datetime import datetime
from app.routes.generate import router
from app.utils.config import config
from app.utils.logger import logger, log_request, log_error

app = FastAPI(
    title="App Compiler",
    description="Natural Language → Production-Ready App Schema. A multi-stage LLM pipeline with validation and repair.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request timing middleware
@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = round(time.time() - start, 3)
    log_request(request.method, request.url.path, duration, response.status_code)
    response.headers["X-Process-Time"] = str(duration)
    return response


# Global validation error handler (Pydantic request errors)
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    log_error(request.url.path, str(exc))
    return JSONResponse(
        status_code=422,
        content={
            "status": "error",
            "error_code": "VALIDATION_ERROR",
            "message": "Request body validation failed",
            "details": exc.errors(),
            "timestamp": datetime.utcnow().isoformat(),
            "path": request.url.path
        }
    )


# Global unhandled exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log_error(request.url.path, str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error_code": "INTERNAL_ERROR",
            "message": str(exc),
            "timestamp": datetime.utcnow().isoformat(),
            "path": request.url.path
        }
    )


# Include routes
app.include_router(router, prefix="/api")


# Health check
@app.get("/", tags=["Health"])
async def health_check():
    return {
        "status": "ok",
        "message": "App Compiler API is running",
        "version": config.PIPELINE_VERSION,
        "environment": config.ENVIRONMENT,
        "timestamp": datetime.utcnow().isoformat()
    }


# Pipeline info (no auth needed)
@app.get("/info", tags=["Health"])
async def system_info():
    return {
        "name": "App Compiler",
        "version": config.PIPELINE_VERSION,
        "description": "Natural Language to Production-Ready App Schema",
        "llm_provider": "Groq",
        "model": config.GROQ_MODEL,
        "pipeline_stages": 4,
        "environment": config.ENVIRONMENT
    }
