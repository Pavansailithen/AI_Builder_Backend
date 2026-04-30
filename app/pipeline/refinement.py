# Stage 4 - Refinement

import json
from app.utils.gemini import call_gemini
from app.validators.models import AppSchema


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

    # Build schema JSON for context
    schema_json = schema.model_dump_json(indent=2)

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

    raw = await call_gemini(fix_prompt)

    # Clean response
    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
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
