# Stage 3 - Schema Generation

import json
from datetime import datetime

from pydantic import ValidationError

from app.utils.config import config
from app.utils.gemini import call_gemini
from app.validators.models import (
    AppSchema,
    APISchema,
    AuthSchema,
    BusinessLogicSchema,
    BusinessRule,
    DatabaseSchema,
    IntentOutput,
    PipelineMetadata,
    SystemDesignOutput,
    UISchema,
)


# ---------------------------------------------------------------------------
# Helper: clean raw Gemini response and parse as dict
# ---------------------------------------------------------------------------

async def clean_and_parse(raw: str, stage_name: str) -> dict:
    cleaned = raw.strip()
    
    # Robustly extract from markdown code blocks
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

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"{stage_name} returned invalid JSON: {raw[:200]}")


# ---------------------------------------------------------------------------
# Main: generate all schemas from intent + design
# ---------------------------------------------------------------------------

async def generate_schemas(
    intent: IntentOutput, design: SystemDesignOutput
) -> AppSchema:

    # Shared context injected into the prompt
    context = f"""
App Name: {design.app_name}
Entities: {[e.name for e in design.entities]}
Roles: {design.roles}
Pages: {design.pages}
API Groups: {design.api_groups}
DB Tables: {design.db_tables}
Auth Flow: {design.auth_flow}
Business Rules: {design.business_rules}
"""

    system_prompt = (
        "You are a software architect who designs database structures, REST APIs, UI pages, user roles, and business rules.\n"
        "Given an app name, user roles, features, pages, database tables, and business rules, generate a complete and consistent application schema JSON.\n"
        "\n"
        "Return ONLY a valid JSON object with the following exact structure:\n"
        "{\n"
        '  "ui": {\n'
        '    "pages": [\n'
        '      {\n'
        '        "name": "PageName (PascalCase string, e.g., ProjectDashboardPage)",\n'
        '        "route": "/route (string, e.g., /projects)",\n'
        '        "components": [\n'
        '          {\n'
        '            "type": "table|form|chart|card|modal|sidebar|navbar (must be one of these)",\n'
        '            "name": "ComponentName (PascalCase string, e.g., ProjectList)",\n'
        '            "fields": ["list of fields, as strings"],\n'
        '            "actions": ["list of actions, as strings"],\n'
        '            "props": {} (an object with key/value string pairs)\n'
        '          }\n'
        '        ],\n'
        '        "access": ["list of role names allowed to access, e.g., Admin"],\n'
        '        "layout": "default|sidebar|fullscreen"\n'
        '      }\n'
        '    ],\n'
        '    "global_components": []\n'
        '  },\n'
        '  "api": {\n'
        '    "endpoints": [\n'
        '      {\n'
        '        "path": "/path (string, e.g., /api/v1/projects)",\n'
        '        "method": "GET|POST|PUT|DELETE|PATCH",\n'
        '        "description": "what this endpoint does",\n'
        '        "auth_required": true|false,\n'
        '        "roles": ["list of user roles allowed to access"],\n'
        '        "request_body": {"field_name": "type"} (or null/empty),\n'
        '        "response_fields": ["list of field names as strings"],\n'
        '        "validation_rules": {"field_name": "rule description"} (or null/empty)\n'
        '      }\n'
        '    ],\n'
        '    "base_url": "/api/v1",\n'
        '    "auth_endpoint": "/api/v1/auth/login"\n'
        '  },\n'
        '  "database": {\n'
        '    "tables": [\n'
        '      {\n'
        '        "name": "lowercase_table_name",\n'
        '        "columns": [\n'
        '          {\n'
        '            "name": "column_name",\n'
        '            "type": "integer|string|text|boolean|float|datetime|json (must be one of these)",\n'
        '            "primary_key": true|false,\n'
        '            "nullable": true|false,\n'
        '            "unique": true|false,\n'
        '            "default": "default_value as a string or null"\n'
        '          }\n'
        '        ],\n'
        '        "relations": [\n'
        '          {\n'
        '            "type": "one_to_many|many_to_one|many_to_many|one_to_one (must be one of these)",\n'
        '            "target_table": "table_name",\n'
        '            "foreign_key": "column_name"\n'
        '          }\n'
        '        ]\n'
        '      }\n'
        '    ],\n'
        '    "database_type": "postgresql"\n'
        '  },\n'
        '  "auth": {\n'
        '    "roles": ["list of user roles"],\n'
        '    "permissions": {\n'
        '      "role_name": ["list of permission strings"]\n'
        '    },\n'
        '    "auth_method": "jwt",\n'
        '    "token_expiry": "24h",\n'
        '    "refresh_token": true\n'
        '  },\n'
        '  "business_logic": {\n'
        '    "rules": [\n'
        '      {\n'
        '        "name": "rule_name_snake_case",\n'
        '        "description": "description",\n'
        '        "condition": "logical condition",\n'
        '        "affected_routes": ["list of affected API endpoint paths"],\n'
        '        "action": "action description"\n'
        '      }\n'
        '    ]\n'
        '  }\n'
        "}\n"
        "\n"
        "Design Constraints:\n"
        "1. Every page defined in the list of pages must be generated in the ui.pages section. Every generated page must contain at least one UI component.\n"
        "2. Every page the user can navigate to must be backed by a working API endpoint. The page's route (excluding home, login, register, and empty routes) must match or be a substring of the API endpoint path. For example, a UI route '/projects' can correspond to '/api/v1/projects' or '/api/v1/projects/{id}'.\n"
        "3. Every API endpoint that requires authentication must specify which user role(s) can access it, and those roles must be defined in the main Auth configuration roles list.\n"
        "4. Database table names referenced by API endpoints must exactly match table names defined in the DB section (avoid singular/plural mismatches). Specifically, ensure the third segment of the API endpoint path (e.g., 'projects' in '/api/v1/projects') exactly matches the name of a database table.\n"
        "5. Foreign key relationships in the DB section must only point to tables that exist in the same schema.\n"
        "6. Any route referenced by a business rule must be a route that actually exists in the API section.\n"
        "7. All roles used in UI page access settings and API endpoints must be defined in the main Auth configuration roles list.\n"
        "8. Every database table must contain an 'id' primary key column (integer type) and a 'created_at' column (datetime type).\n"
        "9. For every database table, generate standard CRUD endpoints (GET list, GET single, POST, PUT, DELETE) in the API endpoints list.\n"
        "10. Return ONLY valid JSON. Do not include markdown code blocks, explanation, or extra characters.\n"
        "11. Be extremely concise in descriptions and field lists to minimize the JSON size and avoid truncation."
    )

    full_prompt = f"{system_prompt}\n\nApp Design Context:\n{context}"
    active_model = config.GROQ_MODEL.lower()
    max_tokens = 2048
    if "27b" in active_model or "qwen" in active_model:
        max_tokens = 4096
    elif "70b" in active_model:
        max_tokens = 6144
    raw_response = await call_gemini(full_prompt, max_tokens=max_tokens)
    parsed_data = await clean_and_parse(raw_response, "Full Schema Generation")

    # Validate individual parts of the JSON with Pydantic
    try:
        ui_schema = UISchema(**parsed_data.get("ui", {}))
        api_schema = APISchema(**parsed_data.get("api", {}))
        db_schema = DatabaseSchema(**parsed_data.get("database", {}))
        auth_schema = AuthSchema(**parsed_data.get("auth", {}))
        bl_schema = BusinessLogicSchema(**parsed_data.get("business_logic", {}))
    except ValidationError as e:
        raise ValueError(f"Schema compilation model validation failed: {str(e)}")

    metadata = PipelineMetadata(
        generated_at=datetime.utcnow().isoformat(),
        pipeline_version="1.0.0",
        assumptions=intent.assumptions,
        warnings=[],
    )

    app_schema = AppSchema(
        app_name=design.app_name,
        description=f"{design.app_name} - Generated by App Compiler",
        ui=ui_schema,
        api=api_schema,
        database=db_schema,
        auth=auth_schema,
        business_logic=bl_schema,
        metadata=metadata,
    )

    return app_schema

