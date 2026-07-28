import asyncio
import os
import json
import time
from datetime import datetime
from app.evaluation.test_prompts import ALL_PROMPTS, DATASET_INFO
from app.pipeline.intent import extract_intent
from app.pipeline.system_design import design_system
from app.pipeline.schema_gen import generate_schemas
from app.pipeline.refinement import refine_schema
from app.validators.validator import validate_app_schema
from app.validators.runtime_validator import validate_runtime

RESULTS_FILE = os.path.join(os.path.dirname(__file__), "results.json")
DELAY_BETWEEN_PROMPTS = 30  # seconds between prompts to avoid rate limits

async def run_single_prompt(prompt_data: dict) -> dict:
    start_time = time.time()
    result = {
        "id": prompt_data["id"],
        "category": prompt_data["category"],
        "difficulty": prompt_data["difficulty"],
        "prompt": prompt_data["prompt"][:100] + "..." if len(prompt_data["prompt"]) > 100 else prompt_data["prompt"],
        "status": "failed",
        "latency_seconds": 0,
        "retries": 0,
        "runtime_score": 0,
        "executable": False,
        "pages_generated": 0,
        "endpoints_generated": 0,
        "tables_generated": 0,
        "roles_generated": 0,
        "assumptions_made": 0,
        "warnings_count": 0,
        "failure_reason": None,
        "failure_type": None,
        "expected_behavior": prompt_data.get("expected_behavior", "n/a")
    }

    try:
        # Stage 1
        intent = await extract_intent(prompt_data["prompt"])
        result["assumptions_made"] = len(intent.assumptions)

        # Stage 2
        design = await design_system(intent)

        # Stage 3
        schema = await generate_schemas(intent, design)

        # Stage 4
        refined = await refine_schema(schema)

        # Validation
        report, _ = validate_app_schema(refined.model_dump())
        result["warnings_count"] = len(refined.metadata.warnings)

        # Runtime validation
        runtime = validate_runtime(refined)

        # Populate results
        result["status"] = "success"
        result["runtime_score"] = runtime["score"]
        result["executable"] = runtime["executable"]
        result["pages_generated"] = len(refined.ui.pages)
        result["endpoints_generated"] = len(refined.api.endpoints)
        result["tables_generated"] = len(refined.database.tables)
        result["roles_generated"] = len(refined.auth.roles)

    except Exception as e:
        error_str = str(e)
        result["failure_reason"] = error_str[:200]

        # Classify failure type
        if "429" in error_str or "rate_limit" in error_str.lower():
            result["failure_type"] = "rate_limit"
        elif "json" in error_str.lower() or "invalid" in error_str.lower():
            result["failure_type"] = "invalid_json"
        elif "timeout" in error_str.lower():
            result["failure_type"] = "timeout"
        elif "validation" in error_str.lower():
            result["failure_type"] = "validation_error"
        else:
            result["failure_type"] = "unknown"

    result["latency_seconds"] = round(time.time() - start_time, 2)
    return result


async def run_evaluation(prompt_ids: list = None) -> dict:
    """
    Run evaluation on all prompts or a subset.
    prompt_ids: list of IDs like ["N01", "E01"] or None for all
    """
    prompts_to_run = ALL_PROMPTS
    if prompt_ids:
        prompts_to_run = [p for p in ALL_PROMPTS if p["id"] in prompt_ids]

    print(f"\n{'='*50}")
    print(f"APP COMPILER EVALUATION RUNNER")
    print(f"{'='*50}")
    print(f"Running {len(prompts_to_run)} prompts...")
    print(f"Delay between prompts: {DELAY_BETWEEN_PROMPTS}s")
    print(f"Estimated time: ~{len(prompts_to_run) * (150 + DELAY_BETWEEN_PROMPTS) / 60:.1f} minutes")
    print(f"{'='*50}\n")

    results = []
    eval_start = time.time()

    for i, prompt_data in enumerate(prompts_to_run):
        print(f"[{i+1}/{len(prompts_to_run)}] Running {prompt_data['id']} ({prompt_data['category']})...")
        result = await run_single_prompt(prompt_data)
        results.append(result)

        status_icon = "✓" if result["status"] == "success" else "✗"
        print(f"  {status_icon} {result['status']} | {result['latency_seconds']}s | score: {result['runtime_score']} | pages: {result['pages_generated']} | endpoints: {result['endpoints_generated']}")

        if result["failure_reason"]:
            print(f"  ⚠ {result['failure_type']}: {result['failure_reason'][:80]}...")

        # Delay between prompts
        if i < len(prompts_to_run) - 1:
            print(f"  Waiting {DELAY_BETWEEN_PROMPTS}s before next prompt...")
            await asyncio.sleep(DELAY_BETWEEN_PROMPTS)

    total_time = round(time.time() - eval_start, 2)

    # Calculate summary
    successful = [r for r in results if r["status"] == "success"]
    failed = [r for r in results if r["status"] == "failed"]

    failure_types = {}
    for r in failed:
        ft = r["failure_type"] or "unknown"
        failure_types[ft] = failure_types.get(ft, 0) + 1

    avg_latency = round(sum(r["latency_seconds"] for r in results) / len(results), 2) if results else 0
    avg_score = round(sum(r["runtime_score"] for r in successful) / len(successful), 1) if successful else 0

    normal_results = [r for r in results if r["difficulty"] == "normal"]
    edge_results = [r for r in results if r["difficulty"] == "edge_case"]
    normal_success = len([r for r in normal_results if r["status"] == "success"])
    edge_success = len([r for r in edge_results if r["status"] == "success"])

    summary = {
        "evaluation_date": datetime.utcnow().isoformat(),
        "total_prompts": len(results),
        "successful": len(successful),
        "failed": len(failed),
        "success_rate": f"{round(len(successful)/len(results)*100)}%" if results else "0%",
        "normal_success_rate": f"{round(normal_success/len(normal_results)*100)}%" if normal_results else "0%",
        "edge_case_success_rate": f"{round(edge_success/len(edge_results)*100)}%" if edge_results else "0%",
        "avg_latency_seconds": avg_latency,
        "avg_runtime_score": avg_score,
        "total_evaluation_time_minutes": round(total_time / 60, 1),
        "failure_types": failure_types,
        "dataset_version": DATASET_INFO["version"]
    }

    final_report = {
        "summary": summary,
        "results": results
    }

    # Save to file
    with open(RESULTS_FILE, "w") as f:
        json.dump(final_report, f, indent=2)

    # Print summary
    print(f"\n{'='*50}")
    print(f"EVALUATION COMPLETE")
    print(f"{'='*50}")
    print(f"Total: {summary['total_prompts']} | Success: {summary['successful']} | Failed: {summary['failed']}")
    print(f"Success Rate: {summary['success_rate']}")
    print(f"Normal: {summary['normal_success_rate']} | Edge Cases: {summary['edge_case_success_rate']}")
    print(f"Avg Latency: {summary['avg_latency_seconds']}s | Avg Score: {summary['avg_runtime_score']}/100")
    print(f"Total Time: {summary['total_evaluation_time_minutes']} minutes")
    print(f"Results saved to: {RESULTS_FILE}")
    print(f"{'='*50}\n")

    return final_report


def log_user_prompt(prompt: str, status: str, schema_dict: dict = None, error_msg: str = None, latency: float = 0.0):
    """
    Saves a user-submitted prompt execution result to results.json, keeping only the last 10.
    """
    import os
    import json
    import time
    from datetime import datetime
    
    user_result = {
        "id": "PENDING",
        "category": "user_submitted",
        "difficulty": "normal",
        "prompt": prompt[:100] + "..." if len(prompt) > 100 else prompt,
        "status": status,
        "latency_seconds": round(latency, 2),
        "retries": 0,
        "runtime_score": 0,
        "executable": False,
        "pages_generated": 0,
        "endpoints_generated": 0,
        "tables_generated": 0,
        "roles_generated": 0,
        "assumptions_made": 0,
        "warnings_count": 0,
        "failure_reason": error_msg[:200] if error_msg else None,
        "failure_type": "unknown" if status == "failed" else None,
        "expected_behavior": "n/a",
        "timestamp": time.time()
    }
    
    if status == "success" and schema_dict:
        try:
            user_result["pages_generated"] = len(schema_dict.get("ui", {}).get("pages", []))
            user_result["endpoints_generated"] = len(schema_dict.get("api", {}).get("endpoints", []))
            user_result["tables_generated"] = len(schema_dict.get("database", {}).get("tables", []))
            user_result["roles_generated"] = len(schema_dict.get("auth", {}).get("roles", []))
            user_result["warnings_count"] = len(schema_dict.get("metadata", {}).get("warnings", []))
            user_result["assumptions_made"] = len(schema_dict.get("metadata", {}).get("assumptions", []))
        except Exception:
            pass
            
        try:
            from app.validators.models import AppSchema
            from app.validators.runtime_validator import validate_runtime
            app_schema = AppSchema.model_validate(schema_dict)
            runtime = validate_runtime(app_schema)
            user_result["runtime_score"] = runtime["score"]
            user_result["executable"] = runtime["executable"]
        except Exception:
            pass
            
    # Load existing results
    all_results = []
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict) and "results" in data:
                    all_results = data["results"]
        except Exception:
            pass
            
    # Separate user and non-user results
    non_user_results = [r for r in all_results if r.get("category") != "user_submitted" and not r.get("id", "").startswith("U")]
    user_results = [r for r in all_results if r.get("category") == "user_submitted" or r.get("id", "").startswith("U")]
    
    # Add new user result
    user_results.append(user_result)
    
    # Sort user results by timestamp to keep them ordered
    user_results.sort(key=lambda x: x.get("timestamp", 0))
    
    # Keep only the last 10 user results
    user_results = user_results[-10:]
    
    # Re-index user results IDs sequentially (U01 to U10)
    for idx, ur in enumerate(user_results):
        ur["id"] = f"U{idx+1:02d}"
        
    # Combine back
    final_results = non_user_results + user_results
    
    # Calculate summary
    successful = [r for r in final_results if r["status"] == "success"]
    failed = [r for r in final_results if r["status"] == "failed"]
    
    failure_types = {}
    for r in failed:
        ft = r.get("failure_type") or "unknown"
        failure_types[ft] = failure_types.get(ft, 0) + 1
        
    avg_latency = round(sum(r.get("latency_seconds", 0) for r in final_results) / len(final_results), 2) if final_results else 0
    avg_score = round(sum(r.get("runtime_score", 0) for r in successful) / len(successful), 1) if successful else 0
    
    normal_results = [r for r in final_results if r.get("difficulty") == "normal"]
    edge_results = [r for r in final_results if r.get("difficulty") == "edge_case"]
    normal_success = len([r for r in normal_results if r.get("status") == "success"])
    edge_success = len([r for r in edge_results if r.get("status") == "success"])
    
    summary = {
        "evaluation_date": datetime.utcnow().isoformat(),
        "total_prompts": len(final_results),
        "successful": len(successful),
        "failed": len(failed),
        "success_rate": f"{round(len(successful)/len(final_results)*100)}%" if final_results else "0%",
        "normal_success_rate": f"{round(normal_success/len(normal_results)*100)}%" if normal_results else "0%",
        "edge_case_success_rate": f"{round(edge_success/len(edge_results)*100)}%" if edge_results else "0%",
        "avg_latency_seconds": avg_latency,
        "avg_runtime_score": avg_score,
        "total_evaluation_time_minutes": round(sum(r.get("latency_seconds", 0) for r in final_results) / 60, 1),
        "failure_types": failure_types,
        "dataset_version": "hybrid-user-dataset"
    }
    
    final_report = {
        "summary": summary,
        "results": final_results
    }
    
    # Save to file
    with open(RESULTS_FILE, "w") as f:
        json.dump(final_report, f, indent=2)
