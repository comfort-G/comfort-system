# app/core/session.py
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import os

SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-local-key")
SERIALIZER_SALT = "cookie-session-salt"

serializer = URLSafeTimedSerializer(SECRET_KEY, salt=SERIALIZER_SALT)

def create_session_token(data: dict) -> str:
    """Sign and serialize user session data into a secure token string."""
    return serializer.dumps(data)

def verify_session_token(token: str, max_age: int = 86400) -> dict:
    """Unsign and validate the session token. Raises exception if tampered or expired."""
    try:
        # max_age defaults to 24 hours (86400 seconds)
        data = serializer.loads(token, max_age=max_age)
        return data
    except (BadSignature, SignatureExpired):
        return None