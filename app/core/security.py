import base64
import hashlib
import logging
import uuid
from datetime import datetime, timezone, timedelta
from functools import lru_cache
from typing import Optional

import bcrypt
import jwt
from cryptography.fernet import Fernet

from app.config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
#  Password hashing
#  bcrypt used directly: passlib is unmaintained and breaks with bcrypt >= 4.1.
#  Hashes are standard $2b$ — existing passlib-created hashes still verify.
# ─────────────────────────────────────────

_BCRYPT_ROUNDS = 12
_BCRYPT_MAX_BYTES = 72  # bcrypt silently truncates beyond 72 bytes — reject instead


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        raise ValueError("Password must be at most 72 bytes.")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    raw = plain_password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(raw, hashed_password.encode("utf-8"))
    except ValueError:
        return False


# ─────────────────────────────────────────
#  JWT tokens
#  PyJWT (python-jose dropped: CVE-2024-33663 / CVE-2024-33664).
#  Tokens carry iss/aud/jti and are verified against an explicit
#  algorithm allowlist — the token header is never trusted.
# ─────────────────────────────────────────

def _build_token(subject: str, token_type: str, lifetime: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + lifetime,
        "jti": uuid.uuid4().hex,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    lifetime = expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return _build_token(subject, "access", lifetime)


def create_refresh_token(subject: str) -> str:
    return _build_token(subject, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises jwt.PyJWTError on failure."""
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],  # explicit allowlist
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
        options={"require": ["exp", "iat", "sub"]},
    )


def hash_token(token: str) -> str:
    """SHA-256 hash of a token (for storing refresh tokens safely)."""
    return hashlib.sha256(token.encode()).hexdigest()


# ─────────────────────────────────────────
#  Content hashing (for approval integrity)
# ─────────────────────────────────────────

def compute_content_hash(caption: str, media_urls: list[str]) -> str:
    """
    SHA-256 hash of caption + sorted media URLs.
    Used to detect edits after approval.
    """
    sorted_urls = sorted(media_urls)
    content = caption + "|".join(sorted_urls)
    return hashlib.sha256(content.encode()).hexdigest()


# ─────────────────────────────────────────
#  AES Encryption (for OAuth tokens at rest)
# ─────────────────────────────────────────

@lru_cache
def _get_fernet() -> Fernet:
    """Build a Fernet instance from the encryption key.

    Preferred: ENCRYPTION_KEY is a real Fernet key
    (python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())").

    Legacy fallback: an arbitrary passphrase is derived via SHA-256 so
    existing dev installs keep decrypting their stored tokens — with a loud
    warning, because a low-entropy passphrase weakens every stored token.
    """
    raw_key = settings.ENCRYPTION_KEY.encode()
    try:
        return Fernet(raw_key)
    except (ValueError, TypeError):
        logger.warning(
            "ENCRYPTION_KEY is not a valid Fernet key; deriving one via SHA-256 "
            "(legacy mode). Generate a proper key with Fernet.generate_key() "
            "and re-encrypt stored tokens before production."
        )
        key_bytes = hashlib.sha256(raw_key).digest()
        return Fernet(base64.urlsafe_b64encode(key_bytes))


def encrypt_token(plain_token: str) -> str:
    """Encrypt an OAuth token for storage in the database."""
    return _get_fernet().encrypt(plain_token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt an OAuth token retrieved from the database."""
    return _get_fernet().decrypt(encrypted_token.encode()).decode()
