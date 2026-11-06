import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

SESSION_COOKIE_NAME = "session_token"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7


def _session_cipher() -> Fernet:
    key_material = hashlib.sha256(
        b"comfort-group-session:" + settings.SECRET_KEY.encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(key_material))


def create_session_token(user_id: int, token_version: int = 0) -> str:
    if user_id <= 0 or token_version < 0:
        raise ValueError("Invalid session claims")
    claims = f"{user_id}:{token_version}"
    return _session_cipher().encrypt(claims.encode("ascii")).decode("ascii")


def read_session_token(token: str) -> tuple[int, int]:
    try:
        claims = _session_cipher().decrypt(
            token.encode("ascii"),
            ttl=SESSION_MAX_AGE_SECONDS,
        ).decode("ascii")
        user_id, separator, token_version = claims.partition(":")
        parsed_user_id = int(user_id)
        # Tokens issued before token versions were added represent version zero.
        parsed_token_version = int(token_version) if separator else 0
        if parsed_user_id <= 0 or parsed_token_version < 0:
            raise ValueError("Invalid session claims")
        return parsed_user_id, parsed_token_version
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise ValueError("Invalid or expired session") from exc
