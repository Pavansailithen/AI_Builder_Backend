import logging
import time
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("app_compiler")


def log_request(method: str, path: str, duration: float, status: int):
    logger.info(f"{method} {path} | {status} | {duration:.2f}s")


def log_pipeline_stage(job_id: str, stage: str, status: str, duration: float = None):
    duration_str = f" | {duration:.2f}s" if duration else ""
    logger.info(f"JOB {job_id} | {stage} | {status}{duration_str}")


def log_error(path: str, error: str):
    logger.error(f"ERROR | {path} | {error}")
