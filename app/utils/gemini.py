import asyncio
import os
from groq import Groq
from dotenv import load_dotenv
from app.utils.config import config

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def get_safe_max_tokens(prompt: str, requested_max: int) -> int:
    active_model = config.GROQ_MODEL.lower()
    if "70b" in active_model:
        max_total_tokens = 11500  # 12k TPM limit
    elif "27b" in active_model or "qwen" in active_model:
        max_total_tokens = 7500   # 8k TPM limit
    else:
        max_total_tokens = 5500   # 6k TPM limit (for 8b)
        
    estimated_prompt_tokens = len(prompt) // 4
    if estimated_prompt_tokens + requested_max > max_total_tokens:
        return max(2048, max_total_tokens - estimated_prompt_tokens)
    return requested_max

async def call_gemini(prompt: str, system_prompt: str = None, max_tokens: int = 8192) -> str:
    """Send a prompt to Groq and return the response text with exponential backoff on HTTP 429 rate limit."""
    await asyncio.sleep(20)
    messages = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    messages.append({"role": "user", "content": prompt})

    # Dynamically scale max_tokens to stay safely under Groq's TPM limits
    safe_max_tokens = get_safe_max_tokens(prompt, max_tokens)

    max_retries = 5
    backoff_factor = 2
    initial_delay = 5  # seconds

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=messages,
                temperature=0.3,
                max_tokens=safe_max_tokens,
            )
            content = response.choices[0].message.content.strip()
            # Strip reasoning/think blocks if output is from a reasoning model (e.g. Qwen)
            if "<think>" in content:
                parts = content.split("</think>")
                if len(parts) > 1:
                    content = parts[-1].strip()
            return content
        except Exception as e:
            # If it is a 413 Payload Too Large error, fail fast immediately
            if (hasattr(e, "status_code") and e.status_code == 413) or "413" in str(e) or "too large" in str(e).lower():
                raise ValueError(f"Groq API payload too large (413): {str(e)}")

            # Check if this is a 429 Rate Limit error
            is_rate_limit = False
            import groq
            if isinstance(e, groq.RateLimitError):
                is_rate_limit = True
            elif hasattr(e, "status_code") and e.status_code == 429:
                is_rate_limit = True
            elif "429" in str(e) or "rate limit" in str(e).lower() or "rate_limit" in str(e).lower():
                is_rate_limit = True

            if is_rate_limit:
                if attempt == max_retries - 1:
                    raise ValueError(f"Groq API rate limit exceeded after {max_retries} attempts: {str(e)}")
                delay = initial_delay * (backoff_factor ** attempt)
                import logging
                logging.getLogger("app_compiler").warning(
                    f"Groq rate limit hit. Retrying in {delay}s... (Attempt {attempt+1}/{max_retries})"
                )
                await asyncio.sleep(delay)
            else:
                # Other exceptions fail immediately
                raise ValueError(f"Groq API call failed: {str(e)}")

