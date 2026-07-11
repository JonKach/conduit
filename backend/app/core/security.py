from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher
from pyrate_limiter import Duration, Rate, RedisBucket
from redis import Redis

from app.core.config import settings

password_hash = PasswordHash(
    (
        Argon2Hasher(),
        BcryptHasher(),
    )
)



ALGORITHM = "HS256"


def create_access_token(subject: str | Any, expires_delta: timedelta) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_password(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    return password_hash.verify_and_update(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)

redis_conn = Redis.from_url(settings.REDIS_URL, decode_responses=True)

general_bucket = RedisBucket.init(
    rates=[Rate(15, Duration.MINUTE)],
    redis=redis_conn,
    bucket_key="general-limits"
)

premium_bucket = RedisBucket.init(
    rates=[Rate(2, Duration.MINUTE)],
    redis=redis_conn,
    bucket_key="api-call-limits"
)
