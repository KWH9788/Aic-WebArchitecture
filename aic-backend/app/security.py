from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.types import TypeDecorator, Text

from app.config import settings


ENCRYPTED_VALUE_PREFIX = "enc:v1:"


class FieldEncryptor:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode("utf-8"))

    def encrypt(self, value: str | None) -> str | None:
        if value is None or value.startswith(ENCRYPTED_VALUE_PREFIX):
            return value
        token = self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")
        return f"{ENCRYPTED_VALUE_PREFIX}{token}"

    def decrypt(self, value: str | None) -> str | None:
        if value is None or not value.startswith(ENCRYPTED_VALUE_PREFIX):
            return value
        token = value[len(ENCRYPTED_VALUE_PREFIX):]
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Encrypted database value could not be decrypted.") from exc


field_encryptor = FieldEncryptor(settings.ENCRYPTION_KEY)


class EncryptedText(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        return field_encryptor.encrypt(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:
        return field_encryptor.decrypt(value)
