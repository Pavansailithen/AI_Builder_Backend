# Stage 2 - System Design

import json

from pydantic import ValidationError

from app.utils.config import config
from app.utils.gemini import call_gemini
from app.validators.models import IntentEntity, IntentOutput, SystemDesignOutput


async def design_system(intent: IntentOutput) -> SystemDesignOutput:
    intent_context = intent.model_dump_json()

    system_prompt = (
        "You are a senior software architect for an app generation system.\n"
        "Given a structured app intent, your job is to design the system architecture.\n"
        "\n"
        "Return ONLY a valid JSON object with this exact structure:\n"
        "{\n"
        '  "app_name": "string - same app name from intent",\n'
        '  "entities": [\n'
        "    {\n"
        '      "name": "string - entity name PascalCase",\n'
        '      "attributes": ["list of attribute names"],\n'
        '      "relationships": ["list of relationship descriptions"]\n'
        "    }\n"
        "  ],\n"
        '  "roles": ["list of user role names"],\n'
        '  "pages": ["list of page names as PascalCase strings e.g. DashboardPage, LoginPage"],\n'
        '  "api_groups": ["list of API controller group names as lowercase strings e.g. auth, contacts, users"],\n'
        '  "db_tables": ["list of database table names as lowercase_snake_case strings"],\n'
        '  "auth_flow": "string - describe the complete authentication flow in one paragraph",\n'
        '  "business_rules": ["list of business rules as clear human-readable strings"]\n'
        "}\n"
        "\n"
        "Rules:\n"
        "- Return ONLY the JSON object. No markdown, no explanation, no code fences.\n"
        "- Pages must cover every feature mentioned in the intent\n"
        "- Every core entity must have a corresponding db_table\n"
        "- Every core feature must have a corresponding api_group\n"
        "- auth_flow must be specific and detailed, not generic\n"
        "- business_rules must be derived directly from the intent features\n"
        "- If payment is required, include a payments table and payment api_group\n"
        "- Always include at least: LoginPage, DashboardPage in pages\n"
        "- Always include auth in api_groups if auth_required is true"
    )

    full_prompt = f"{system_prompt}\n\nStructured App Intent:\n{intent_context}"

    active_model = config.GROQ_MODEL.lower()
    max_tokens = 4096 if ("27b" in active_model or "qwen" in active_model) else 1024
    # Call Gemini
    raw_response = await call_gemini(full_prompt, max_tokens=max_tokens)

    # Clean the response
    cleaned = raw_response.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json"):]
    elif cleaned.startswith("```"):
        cleaned = cleaned[len("```"):]
    if cleaned.endswith("```"):
        cleaned = cleaned[: -len("```")]
    cleaned = cleaned.strip()

    # Parse JSON
    try:
        parsed_data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                parsed_data = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                raise ValueError(
                    f"System design failed - invalid JSON: {raw_response[:200]}"
                )
        else:
            raise ValueError(
                f"System design failed - invalid JSON: {raw_response[:200]}"
            )

    # Validate with Pydantic
    try:
        system_design_output = SystemDesignOutput(**parsed_data)
    except ValidationError as e:
        raise ValueError(f"System design schema mismatch: {str(e)}")

    return system_design_output
