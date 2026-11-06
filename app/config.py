# app/config.py
from pydantic_settings import BaseSettings
from pydantic import field_validator

class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ENVIRONMENT: str = "production"
    CLOUDINARY_CLOUD_NAME: str | None = None
    CLOUDINARY_API_KEY: str | None = None
    CLOUDINARY_API_SECRET: str | None = None
    PASSWORD_RESET_PUBLIC_URL: str | None = None
    SMTP_SERVER: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SENDER_EMAIL: str | None = None

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"production", "prod", "development", "dev", "local"}:
            raise ValueError(
                "ENVIRONMENT must be production, prod, development, dev, or local."
            )
        return value

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 32:
            raise ValueError("SECRET_KEY must contain at least 32 characters.")
        return value

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()