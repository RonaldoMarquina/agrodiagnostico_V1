"""Cryptographic and password security utilities using Argon2id and SHA-256."""
import hashlib
import secrets
from argon2 import PasswordHasher, Type, exceptions

# RFC 9106 recommended parameters for Argon2id
_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MiB
    parallelism=4,
    hash_len=32,
    type=Type.ID,
)

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128


def validate_password_policy(password: str) -> bool:
    """Validate minimum 12 and maximum 128 characters policy."""
    if not isinstance(password, str):
        return False
    return MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH


def hash_password(password: str) -> str:
    """Hash password using Argon2id with RFC 9106 parameters."""
    if not validate_password_policy(password):
        raise ValueError("Password does not meet length requirements (12-128 characters)")
    return _HASHER.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plain password against stored Argon2id hash in constant time."""
    if not plain_password or not hashed_password:
        return False
    try:
        return _HASHER.verify(hashed_password, plain_password)
    except exceptions.VerifyMismatchError:
        return False
    except exceptions.VerificationError:
        return False
    except Exception:
        return False


def needs_rehash(hashed_password: str) -> bool:
    """Check if the hash was created with parameters weaker than current."""
    try:
        return _HASHER.check_needs_rehash(hashed_password)
    except Exception:
        return True


def generate_secure_token(nbytes: int = 32) -> str:
    """Generate a cryptographically secure URL-safe random token."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Compute SHA-256 hex digest of an opaque token for safe database persistence."""
    if not isinstance(token, str) or not token:
        raise ValueError("Token must be a non-empty string")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token_hash(token: str, expected_hash: str) -> bool:
    """Verify that SHA-256(token) matches expected_hash using constant-time comparison."""
    if not token or not expected_hash:
        return False
    computed = hash_token(token)
    return secrets.compare_digest(computed, expected_hash)
