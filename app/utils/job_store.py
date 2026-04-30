import asyncio
import uuid
from datetime import datetime
from typing import Optional

# In-memory job store
jobs = {}


def create_job(prompt: str) -> str:
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "job_id": job_id,
        "status": "created",
        "current_stage": None,
        "progress": 0,
        "prompt": prompt,
        "created_at": datetime.utcnow().isoformat(),
        "completed_at": None,
        "result": None,
        "error": None
    }
    return job_id


def update_job(job_id: str, **kwargs):
    if job_id in jobs:
        jobs[job_id].update(kwargs)


def get_job(job_id: str) -> Optional[dict]:
    return jobs.get(job_id)


def complete_job(job_id: str, result: dict):
    if job_id in jobs:
        jobs[job_id].update({
            "status": "completed",
            "progress": 100,
            "current_stage": "done",
            "completed_at": datetime.utcnow().isoformat(),
            "result": result
        })


def fail_job(job_id: str, error: str):
    if job_id in jobs:
        jobs[job_id].update({
            "status": "failed",
            "completed_at": datetime.utcnow().isoformat(),
            "error": error
        })
