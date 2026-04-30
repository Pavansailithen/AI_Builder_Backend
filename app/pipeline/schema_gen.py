# Stage 3 - Schema Generation

import json
from datetime import datetime

from pydantic import ValidationError

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
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json"):]
    elif cleaned.startswith("```"):
        cleaned = cleaned[len("```"):]
    if cleaned.endswith("```"):
        cleaned = cleaned[: -len("```")]
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

    # Shared context injected into every prompt
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

    # ------------------------------------------------------------------
    # CALL 1 — Database Schema
    # ------------------------------------------------------------------
    db_prompt = f"""You are a database schema generator.
Given this app design, generate a complete PostgreSQL database schema.

Return ONLY valid JSON matching this exact structure:
{{
  "tables": [
    {{
      "name": "lowercase_table_name",
      "columns": [
        {{
          "name": "column_name",
          "type": "integer|string|text|boolean|float|datetime|json",
          "primary_key": true,
          "nullable": false,
          "unique": false,
          "default": "default_value or null"
        }}
      ],
      "relations": [
        {{
          "type": "one_to_many|many_to_one|many_to_many|one_to_one",
          "target_table": "table_name",
          "foreign_key": "column_name"
        }}
      ]
    }}
  ],
  "database_type": "postgresql"
}}

Rules:
- Every table must have an id column as integer primary_key
- Every table must have created_at as datetime
- String foreign keys must match actual table names
- Return ONLY JSON, no markdown, no explanation

App Design Context:
{context}"""

    db_raw = await call_gemini(db_prompt)
    db_data = await clean_and_parse(db_raw, "DB Schema")
    db_schema = DatabaseSchema(**db_data)

    # ------------------------------------------------------------------
    # CALL 2 — API Schema
    # ------------------------------------------------------------------
    api_prompt = f"""You are an API schema generator.
Given this app design and database schema, generate complete REST API endpoints.

Return ONLY valid JSON matching this exact structure:
{{
  "endpoints": [
    {{
      "path": "/resource/action",
      "method": "GET|POST|PUT|DELETE|PATCH",
      "description": "what this endpoint does",
      "auth_required": true,
      "roles": ["role1", "role2"],
      "request_body": {{"field": "type"}},
      "response_fields": ["field1", "field2"],
      "validation_rules": {{"field": "rule description"}}
    }}
  ],
  "base_url": "/api/v1",
  "auth_endpoint": "/api/v1/auth/login"
}}

Rules:
- Every db table must have at minimum GET (list), GET (single), POST, PUT, DELETE endpoints
- Auth endpoints do not require auth_required
- Roles must be from this list: {design.roles}
- Return ONLY JSON, no markdown, no explanation

App Design Context:
{context}

Database Tables Generated:
{json.dumps(db_data, indent=2)}"""

    api_raw = await call_gemini(api_prompt)
    api_data = await clean_and_parse(api_raw, "API Schema")
    api_schema = APISchema(**api_data)

    # ------------------------------------------------------------------
    # CALL 3 — Auth Schema
    # ------------------------------------------------------------------
    auth_prompt = f"""You are an auth schema generator.
Given this app design, generate the complete authentication and authorization schema.

Return ONLY valid JSON matching this exact structure:
{{
  "roles": ["role1", "role2"],
  "permissions": {{
    "role_name": ["permission1", "permission2"]
  }},
  "auth_method": "jwt",
  "token_expiry": "24h",
  "refresh_token": true
}}

Rules:
- Roles must match exactly: {design.roles}
- Permissions must reflect the business rules
- Return ONLY JSON, no markdown, no explanation

App Design Context:
{context}"""

    auth_raw = await call_gemini(auth_prompt)
    auth_data = await clean_and_parse(auth_raw, "Auth Schema")
    auth_schema = AuthSchema(**auth_data)

    # ------------------------------------------------------------------
    # CALL 4 — UI Schema
    # ------------------------------------------------------------------
    ui_prompt = f"""You are a UI schema generator.
Given this app design, generate the complete UI schema with all pages and components.

Return ONLY valid JSON matching this exact structure:
{{
  "pages": [
    {{
      "name": "PageName",
      "route": "/route",
      "components": [
        {{
          "type": "table|form|chart|card|modal|sidebar|navbar",
          "name": "ComponentName",
          "fields": ["field1", "field2"],
          "actions": ["action1", "action2"],
          "props": {{}}
        }}
      ],
      "access": ["role1", "role2"],
      "layout": "default|sidebar|fullscreen"
    }}
  ],
  "global_components": [
    {{
      "type": "navbar|sidebar",
      "name": "ComponentName",
      "fields": ["field1"],
      "actions": ["action1"],
      "props": {{}}
    }}
  ]
}}

Rules:
- Every page in {design.pages} must be included
- Access roles must be from {design.roles}
- Every page must have at least one component
- Return ONLY JSON, no markdown, no explanation

App Design Context:
{context}"""

    ui_raw = await call_gemini(ui_prompt)
    ui_data = await clean_and_parse(ui_raw, "UI Schema")
    ui_schema = UISchema(**ui_data)

    # ------------------------------------------------------------------
    # CALL 5 — Business Logic Schema
    # ------------------------------------------------------------------
    bl_prompt = f"""You are a business logic schema generator.
Given these business rules, generate structured business logic.

Return ONLY valid JSON matching this exact structure:
{{
  "rules": [
    {{
      "name": "rule_name_snake_case",
      "description": "human readable description",
      "condition": "logical condition as string",
      "affected_routes": ["/route1", "/route2"],
      "action": "what happens when condition is met"
    }}
  ]
}}

Rules to convert: {design.business_rules}
Return ONLY JSON, no markdown, no explanation."""

    bl_raw = await call_gemini(bl_prompt)
    bl_data = await clean_and_parse(bl_raw, "Business Logic")
    bl_schema = BusinessLogicSchema(**bl_data)

    # ------------------------------------------------------------------
    # Assemble final AppSchema
    # ------------------------------------------------------------------
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
