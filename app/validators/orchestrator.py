import time
import asyncio
from app.validators.repair import run_with_repair
from app.validators.models import ValidationReport

MAX_PIPELINE_ATTEMPTS = 3


async def run_pipeline(prompt: str) -> dict:
    start_time = time.time()
    last_error = None
    best_result = None
    all_attempts = []

    for attempt in range(1, MAX_PIPELINE_ATTEMPTS + 1):
        attempt_start = time.time()
        try:
            # Modify prompt slightly on retries to push for stricter output
            if attempt == 1:
                run_prompt = prompt
            elif attempt == 2:
                run_prompt = f"Be very strict and precise. Return complete valid JSON only.\n\nOriginal request: {prompt}"
            else:
                run_prompt = f"Simple app request (keep it minimal and valid): {prompt}"

            schema, reports = await run_with_repair(run_prompt)
            attempt_time = round(time.time() - attempt_start, 2)
            all_valid = all(r.is_valid for r in reports)
            repair_triggered = any("repair" in r.stage for r in reports)

            attempt_record = {
                "attempt": attempt,
                "status": "success" if all_valid else "success_with_warnings",
                "time_seconds": attempt_time,
                "repair_triggered": repair_triggered,
                "stages": [r.stage for r in reports]
            }
            all_attempts.append(attempt_record)

            # Store best result (prefer fully valid)
            if best_result is None or all_valid:
                best_result = {
                    "schema": schema.model_dump(),
                    "validation_reports": [r.model_dump() for r in reports],
                    "all_valid": all_valid,
                    "repair_triggered": repair_triggered
                }

            # If fully valid, stop retrying
            if all_valid:
                break

        except Exception as e:
            attempt_time = round(time.time() - attempt_start, 2)
            last_error = str(e)
            all_attempts.append({
                "attempt": attempt,
                "status": "failed",
                "time_seconds": attempt_time,
                "error": last_error
            })
            # Wait before retry
            if attempt < MAX_PIPELINE_ATTEMPTS:
                await asyncio.sleep(5)

    total_time = round(time.time() - start_time, 2)

    # Build final response
    if best_result is not None:
        return {
            "status": "success" if best_result["all_valid"] else "success_with_warnings",
            "total_attempts": len(all_attempts),
            "total_time_seconds": total_time,
            "repair_triggered": best_result["repair_triggered"],
            "attempts_detail": all_attempts,
            "schema": best_result["schema"],
            "validation_reports": best_result["validation_reports"],
            "all_valid": best_result["all_valid"],
            "error": None
        }
    else:
        return {
            "status": "failed",
            "total_attempts": len(all_attempts),
            "total_time_seconds": total_time,
            "repair_triggered": False,
            "attempts_detail": all_attempts,
            "schema": None,
            "validation_reports": [],
            "all_valid": False,
            "error": last_error or "Pipeline failed after all attempts"
        }
