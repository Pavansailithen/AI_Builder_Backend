import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    ALLOWED_ORIGINS: list = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://localhost:3000",
        os.getenv("FRONTEND_URL", ""),
        os.getenv("VERCEL_URL", ""),
    ]
    PORT: int = int(os.getenv("PORT", 8000))
    MAX_PIPELINE_ATTEMPTS: int = 3
    MAX_REPAIR_ATTEMPTS: int = 3
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    PIPELINE_VERSION: str = "1.0.0"


config = Config()
