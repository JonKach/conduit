from datetime import datetime, timedelta, timezone
from time import time_ns
from typing import Any

import jwt
from fastapi import Request
from fastapi_limiter.identifier import default_identifier
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher
from pyrate_limiter import (
    AbstractBucket,
    BucketFactory,
    Duration,
    Limiter,
    Rate,
    RateItem,
    RedisBucket,
)
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


async def user_or_ip_identifier(request: Request) -> str:
    """Rate-limit key: per authenticated user when possible, else per client IP.

    Prefers the JWT subject and falls back to fastapi_limiter's default
    IP-based identifier.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ")
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        except InvalidTokenError:
            pass
        else:
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
    return await default_identifier(request)


class KeyedRedisBucketFactory(BucketFactory):
    """Gives each distinct rate-limit key its own Redis bucket."""

    def __init__(self, rates: list[Rate], redis: Redis, prefix: str):
        self.rates = rates
        self.redis = redis
        self.prefix = prefix
        self._buckets: dict[str, AbstractBucket] = {}

    def wrap_item(self, name: str, weight: int = 1) -> RateItem:
        return RateItem(name, time_ns() // 1_000_000, weight=weight)

    def get(self, item: RateItem) -> AbstractBucket:
        bucket = self._buckets.get(item.name)
        if bucket is None:
            bucket = RedisBucket.init(
                rates=self.rates,
                redis=self.redis,
                bucket_key=f"{self.prefix}:{item.name}",
            )
            self.schedule_leak(bucket)
            self._buckets[item.name] = bucket
        return bucket


redis_conn = Redis.from_url(settings.REDIS_URL, decode_responses=True)

general_bucket = Limiter(
    KeyedRedisBucketFactory([Rate(180, Duration.MINUTE)], redis_conn, "general-limits")
)

premium_bucket = Limiter(
    KeyedRedisBucketFactory([Rate(2, Duration.MINUTE)], redis_conn, "api-call-limits")
)

auth_bucket = Limiter(
    KeyedRedisBucketFactory(
        [Rate(10, Duration.MINUTE), Rate(60, Duration.HOUR)], redis_conn, "auth-limits"
    )
)

recovery_bucket = Limiter(
    KeyedRedisBucketFactory([Rate(3, Duration.HOUR)], redis_conn, "recovery-limits")
)
