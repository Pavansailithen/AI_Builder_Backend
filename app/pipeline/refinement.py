# Stage 4 - Refinement

import json
from app.utils.gemini import call_gemini
from app.validators.models import AppSchema
from app.utils.config import config



def check_consistency(schema: AppSchema) -> list[str]:
    issues = []

    # Ground truth sets
    valid_roles = set(r.lower() for r in schema.auth.roles)
    valid_table_names = set(t.name.lower() for t in schema.database.tables)
    valid_api_paths = set(e.path for e in schema.api.endpoints)

    # Check 1: UI page access roles
    for page in schema.ui.pages:
        for role in page.access:
            if role.lower() not in valid_roles:
                issues.append(f"UI page '{page.name}' references undefined role '{role}'")

    # Check 2: API endpoint roles
    for endpoint in schema.api.endpoints:
        for role in endpoint.roles:
            if role.lower() not in valid_roles:
                issues.append(f"API endpoint '{endpoint.path}' references undefined role '{role}'")

    # Check 3: Auth permissions keys
    for role_key in schema.auth.permissions.keys():
        if role_key.lower() not in valid_roles:
            issues.append(f"Auth permissions has undefined role key '{role_key}'")

    # Check 4: DB relation targets
    for table in schema.database.tables:
        for relation in table.relations:
            if relation.target_table.lower() not in valid_table_names:
                issues.append(f"Table '{table.name}' has relation to undefined table '{relation.target_table}'")

    # Check 5: Business rule affected routes
    for rule in schema.business_logic.rules:
        for route in rule.affected_routes:
            # Normalize: strip path params for comparison
            normalized = route.split("{")[0].rstrip("/")
            found = any(
                ep.path.split(":")[0].rstrip("/") == normalized or
                ep.path == route
                for ep in schema.api.endpoints
            )
            if not found:
                issues.append(f"Business rule '{rule.name}' references undefined route '{route}'")

    # Check 6: UI Page Route Completeness (routes must map to API paths)
    for page in schema.ui.pages:
        route = page.route.strip("/")
        has_match = any(
            p.strip("/").startswith(route) or route in p
            for p in valid_api_paths
        )
        if not has_match and route not in ["login", "register", "home", "dashboard", "settings", "admin", "landing", ""]:
            issues.append(f"UI page '{page.name}' with route '{page.route}' has no matching API endpoint path")


    # Check 7: API Endpoint Auth Coverage (auth_required endpoints must have roles)
    for endpoint in schema.api.endpoints:
        if endpoint.auth_required and len(endpoint.roles) == 0:
            issues.append(f"API endpoint '{endpoint.path}' requires authentication but has no roles defined")

    # Check 8: API Endpoint DB Coverage (API groups must match DB table names)
    api_groups = set()
    for endpoint in schema.api.endpoints:
        parts = endpoint.path.strip("/").split("/")
        if len(parts) >= 3:
            api_groups.add(parts[2])
    for g in api_groups:
        if g not in valid_table_names and g not in ["auth", "analytics"]:
            issues.append(f"API group '{g}' references undefined database table '{g}'")

    return issues


async def refine_schema(schema: AppSchema) -> AppSchema:
    # Run consistency checks
    issues = check_consistency(schema)

    # Fast path: no issues found
    if not issues:
        schema.metadata.warnings.append("Refinement passed: no inconsistencies found")
        return schema

    # Add issues to metadata warnings
    schema.metadata.warnings.extend(issues)

    # Build issues summary string
    issues_text = "\n".join(f"- {issue}" for issue in issues)

    # Build schema JSON for context (compact representation to save tokens)
    schema_json = schema.model_dump_json()

    # Call Groq to fix issues
    fix_prompt = f"""You are a schema refinement engine for an app generation system.
You have been given a complete app schema that has some inconsistencies.
Your job is to fix ONLY the listed inconsistencies and return the corrected schema.

INCONSISTENCIES FOUND:
{issues_text}

RULES FOR FIXING:
- Fix only what is listed above
- Do not change anything else
- Roles must be consistent across ui, api, and auth sections
- DB relation target_table values must match actual table names exactly
- Business rule affected_routes must match actual API endpoint paths
- Return ONLY the complete corrected JSON schema, no markdown, no explanation

CURRENT SCHEMA:
{schema_json}"""

    # Dynamically calculate max_tokens to stay safely under Groq's TPM limits
    active_model = config.GROQ_MODEL.lower()
    if "70b" in active_model:
        max_total_tokens = 11500  # 12k TPM limit
    elif "27b" in active_model or "qwen" in active_model:
        max_total_tokens = 7500   # 8k TPM limit
    else:
        max_total_tokens = 5500   # 6k TPM limit (for 8b)

    # 4 characters per token is a safe estimation.
    estimated_prompt_tokens = len(fix_prompt) // 4
    estimated_output_tokens = (len(schema_json) // 4) + 1000  # output size matches input schema size + 1000 buffer
    
    if estimated_prompt_tokens + estimated_output_tokens > max_total_tokens:
        max_tokens = max(2048, max_total_tokens - estimated_prompt_tokens)
    else:
        max_tokens = max(2048, estimated_output_tokens)
        
    max_tokens = min(8192, max_tokens)

    raw = await call_gemini(fix_prompt, max_tokens=max_tokens)

    # Clean response robustly
    cleaned = raw.strip()
    if "```json" in cleaned:
        parts = cleaned.split("```json")
        if len(parts) > 1:
            after_json = parts[1]
            if "```" in after_json:
                cleaned = after_json.split("```")[0].strip()
    elif "```" in cleaned:
        parts = cleaned.split("```")
        for part in parts:
            part_str = part.strip()
            if part_str.startswith("{") and part_str.endswith("}"):
                cleaned = part_str
                break
    else:
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
            
    cleaned = cleaned.strip()

    # Parse and validate
    try:
        fixed_data = json.loads(cleaned)
    except json.JSONDecodeError:
        schema.metadata.warnings.append("Refinement fix failed: returned original schema")
        return schema

    try:
        refined_schema = AppSchema(**fixed_data)
        refined_schema.metadata.warnings.append(f"Refinement fixed {len(issues)} issue(s)")
        return refined_schema
    except Exception:
        schema.metadata.warnings.append("Refinement validation failed: returned original schema")
        return schema
