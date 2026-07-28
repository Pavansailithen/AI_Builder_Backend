# Stage 1 - Intent Extraction

import json

from pydantic import ValidationError

from app.utils.config import config
from app.utils.gemini import call_gemini
from app.validators.models import IntentEntity, IntentOutput


async def extract_intent(prompt: str) -> IntentOutput:
    system_prompt = (
        "You are an intent extraction engine for an app generation system.\n"
        "Your job is to analyze a user's app description and extract structured intent.\n"
        "\n"
        "Return ONLY a valid JSON object with this exact structure:\n"
        "{\n"
        '  "app_name": "string - a suitable name for the app",\n'
        '  "app_type": "string - type of app (crm, ecommerce, dashboard, social, productivity, etc)",\n'
        '  "core_entities": [\n'
        "    {\n"
        '      "name": "string - entity name (singular, PascalCase)",\n'
        '      "attributes": ["list of attribute names as strings"],\n'
        '      "relationships": ["list of relationship descriptions as strings"]\n'
        "    }\n"
        "  ],\n"
        '  "user_roles": ["list of user role names"],\n'
        '  "core_features": ["list of core features as strings"],\n'
        '  "auth_required": true/false,\n'
        '  "payment_required": true/false,\n'
        '  "assumptions": ["list of assumptions you made as strings"]\n'
        "}\n"
        "\n"
        "Rules:\n"
        "- Return ONLY the JSON object. No markdown, no explanation, no code fences.\n"
        "- Always include at least one entity\n"
        "- Always include at least one role\n"
        "- If auth is mentioned or implied, set auth_required to true\n"
        "- Document every assumption you make in the assumptions array\n"
        "- Entity names must be PascalCase singular nouns"
    )

    full_prompt = f"{system_prompt}\n\nUser's app description:\n{prompt}"

    active_model = config.GROQ_MODEL.lower()
    max_tokens = 4096 if ("27b" in active_model or "qwen" in active_model) else 512
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
        # Try to salvage by extracting the outermost { ... }
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                parsed_data = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                raise ValueError(
                    f"Intent extraction failed - invalid JSON: {raw_response[:200]}"
                )
        else:
            raise ValueError(
                f"Intent extraction failed - invalid JSON: {raw_response[:200]}"
            )

    # Validate with Pydantic
    try:
        intent_output = IntentOutput(**parsed_data)
    except ValidationError as e:
        raise ValueError(f"Intent extraction schema mismatch: {str(e)}")

    return intent_output
