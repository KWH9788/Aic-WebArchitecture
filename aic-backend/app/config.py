from pydantic_settings import BaseSettings
from pydantic import field_validator


_PLACEHOLDER_HINTS = (
    "change_",
    "placeholder",
    "example",
    "default",
    "your_",
)


class Settings(BaseSettings):
    DB_URL: str = "mysql+aiomysql://aic_user:password@db:3306/aic_db?charset=utf8mb4"
    JWT_SECRET: str = "change_me_in_production_use_32_plus_random_chars"
    ENCRYPTION_KEY: str = "change_me_generate_with_fernet_generate_key"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    PIPELINE_URL: str = "http://pipeline:9000"
    COOKIE_SECURE: bool = False

    @field_validator("JWT_SECRET")
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters.")
        lowered = value.lower()
        if any(hint in lowered for hint in _PLACEHOLDER_HINTS):
            raise ValueError("JWT_SECRET must not use placeholder/default text.")
        return value

    @field_validator("ENCRYPTION_KEY")
    @classmethod
    def validate_encryption_key(cls, value: str) -> str:
        lowered = value.lower()
        if any(hint in lowered for hint in _PLACEHOLDER_HINTS):
            raise ValueError("ENCRYPTION_KEY must not use placeholder/default text.")
        try:
            from cryptography.fernet import Fernet

            Fernet(value.encode("utf-8"))
        except Exception as exc:
            raise ValueError("ENCRYPTION_KEY must be a valid Fernet key.") from exc
        return value

    class Config:
        env_file = ".env"


settings = Settings()
