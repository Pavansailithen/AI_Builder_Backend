from app.validators.models import AppSchema
from typing import Any


def make_check(check: str, passed: bool, details: str, affected: list = None) -> dict:
    return {
        "check": check,
        "passed": passed,
        "details": details,
        "affected": affected or []
    }


def validate_runtime(schema: AppSchema) -> dict:
    checks = []

    # --- Setup ground truth ---
    api_paths = set(e.path for e in schema.api.endpoints)
    api_path_normalized = set(
        p.split("{")[0].rstrip("/") for p in api_paths
    )
    db_table_names = set(t.name.lower() for t in schema.database.tables)
    valid_roles = set(r.lower() for r in schema.auth.roles)

    # All response fields across all endpoints
    all_response_fields = set()
    for e in schema.api.endpoints:
        all_response_fields.update(e.response_fields)

    # --- CHECK 1: Route Completeness ---
    # Every UI page route should have at least one API endpoint starting with same path
    pages_without_api = []
    for page in schema.ui.pages:
        route = page.route.strip("/")
        has_match = any(
            p.strip("/").startswith(route) or route in p
            for p in api_paths
        )
        if not has_match and route not in ["login", "register", "home", "dashboard", "settings", "admin", "landing", ""]:
            pages_without_api.append(page.route)


    checks.append(make_check(
        "route_completeness",
        len(pages_without_api) == 0,
        f"All {len(schema.ui.pages)} UI pages have matching API endpoints" if not pages_without_api
        else f"{len(pages_without_api)} pages have no matching API endpoint",
        pages_without_api
    ))

    # --- CHECK 2: Auth Coverage ---
    # Every endpoint with auth_required=True must have at least one role
    endpoints_missing_roles = []
    for e in schema.api.endpoints:
        if e.auth_required and len(e.roles) == 0:
            endpoints_missing_roles.append(e.path)

    checks.append(make_check(
        "auth_coverage",
        len(endpoints_missing_roles) == 0,
        f"All protected endpoints have roles defined" if not endpoints_missing_roles
        else f"{len(endpoints_missing_roles)} protected endpoints have no roles",
        endpoints_missing_roles
    ))

    # --- CHECK 3: DB Coverage ---
    # Every API group should map to a DB table
    api_groups = set()
    for e in schema.api.endpoints:
        parts = e.path.strip("/").split("/")
        if len(parts) >= 3:
            api_groups.add(parts[2])

    groups_without_table = [g for g in api_groups if g not in db_table_names and g not in ["auth", "analytics"]]

    checks.append(make_check(
        "db_coverage",
        len(groups_without_table) == 0,
        f"All API groups map to DB tables" if not groups_without_table
        else f"{len(groups_without_table)} API groups have no matching DB table",
        groups_without_table
    ))

    # --- CHECK 4: Role Consistency ---
    # All roles used in UI and API must be in auth.roles
    undefined_roles = set()
    for page in schema.ui.pages:
        for role in page.access:
            if role.lower() not in valid_roles:
                undefined_roles.add(f"UI:{page.name}:{role}")
    for e in schema.api.endpoints:
        for role in e.roles:
            if role.lower() not in valid_roles:
                undefined_roles.add(f"API:{e.path}:{role}")

    checks.append(make_check(
        "role_consistency",
        len(undefined_roles) == 0,
        f"All roles are consistently defined" if not undefined_roles
        else f"{len(undefined_roles)} undefined role references found",
        list(undefined_roles)
    ))

    # --- CHECK 5: DB Foreign Key Validity ---
    # Every relation target_table must exist
    invalid_relations = []
    for table in schema.database.tables:
        for rel in table.relations:
            if rel.target_table.lower() not in db_table_names:
                invalid_relations.append(f"{table.name} -> {rel.target_table}")

    checks.append(make_check(
        "foreign_key_validity",
        len(invalid_relations) == 0,
        f"All foreign key relations point to valid tables" if not invalid_relations
        else f"{len(invalid_relations)} invalid foreign key relations",
        invalid_relations
    ))

    # --- CHECK 6: Business Rule Route Validity ---
    # Affected routes in business rules should map to real API paths
    invalid_rule_routes = []
    for rule in schema.business_logic.rules:
        for route in rule.affected_routes:
            normalized = route.split("{")[0].rstrip("/")
            found = any(
                ep.path.split(":")[0].rstrip("/") == normalized or
                ep.path == route or
                normalized in ep.path
                for ep in schema.api.endpoints
            )
            if not found:
                invalid_rule_routes.append(f"{rule.name}:{route}")

    checks.append(make_check(
        "business_rule_routes",
        len(invalid_rule_routes) == 0,
        f"All business rule routes map to API endpoints" if not invalid_rule_routes
        else f"{len(invalid_rule_routes)} business rules reference undefined routes",
        invalid_rule_routes
    ))

    # --- SCORE CALCULATION ---
    passed = sum(1 for c in checks if c["passed"])
    total = len(checks)
    score = round((passed / total) * 100)
    executable = score >= 60

    # --- SUMMARY ---
    if score == 100:
        summary = "Schema is fully executable — all checks passed"
    elif score >= 80:
        summary = f"Schema is executable with {total - passed} minor issue(s)"
    elif score >= 60:
        summary = f"Schema is partially executable — {total - passed} issue(s) need attention"
    else:
        summary = f"Schema has significant issues — {total - passed} checks failed"

    return {
        "executable": executable,
        "score": score,
        "passed_checks": passed,
        "total_checks": total,
        "checks": checks,
        "summary": summary
    }
