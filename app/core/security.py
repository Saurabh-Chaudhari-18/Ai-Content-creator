import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext
from cryptography.fernet import Fernet
import base64

from app.config import settings

# ─────────────────────────────────────────
#  Password hashing
# ─────────────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ─────────────────────────────────────────
#  JWT tokens
# ─────────────────────────────────────────

def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": subject, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": subject, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises JWTError on failure."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


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

def _get_fernet() -> Fernet:
    """Build a Fernet instance from the encryption key."""
    key = settings.ENCRYPTION_KEY.encode()
    # Fernet requires a 32-byte URL-safe base64-encoded key
    key_bytes = hashlib.sha256(key).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def encrypt_token(plain_token: str) -> str:
    """Encrypt an OAuth token for storage in the database."""
    return _get_fernet().encrypt(plain_token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    """Decrypt an OAuth token retrieved from the database."""
    return _get_fernet().decrypt(encrypted_token.encode()).decode()
