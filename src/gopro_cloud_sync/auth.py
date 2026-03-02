import base64
import json
import time

import httpx

from .models import TokenData

OAUTH_URL = "https://api.gopro.com/v1/oauth2/token"
CLIENT_ID = "71611e67ea968cfacf45e2b6936c81156fcf5dbe553a2bf2d342da1562d05f46"
CLIENT_SECRET = "3863c9b438c07b82f39ab3eeeef9c24fefa50c6856253e3f1d37e0e3b1ead68d"
SCOPE = "root root:channels public me upload media_library_beta live"


class AuthError(Exception):
    pass


class TwoFactorRequired(AuthError):
    pass


async def login_password(email: str, password: str, client: httpx.AsyncClient) -> TokenData:
    resp = await client.post(
        OAUTH_URL,
        data={
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scope": SCOPE,
            "username": email,
            "password": password,
        },
    )
    if resp.status_code == 401:
        body = resp.text.lower()
        if "mfa" in body or "2fa" in body or "two_factor" in body or "otp" in body:
            raise TwoFactorRequired(
                "2FA is enabled on this account. Use 'gopro-sync login-token <TOKEN>' instead.\n"
                "Get your token from: plus.gopro.com → DevTools → Application → Cookies → gp_access_token"
            )
        raise AuthError(f"Authentication failed: {resp.text}")
    resp.raise_for_status()

    data = resp.json()
    return TokenData(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", ""),
        expires_at=time.time() + data.get("expires_in", 3600),
    )


async def refresh(token: TokenData, client: httpx.AsyncClient) -> TokenData:
    if not token.refresh_token:
        raise AuthError("No refresh token available. Please login again.")
    resp = await client.post(
        OAUTH_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": token.refresh_token,
        },
    )
    if resp.status_code in (401, 403):
        raise AuthError("Token refresh failed. Please login again.")
    resp.raise_for_status()

    data = resp.json()
    return TokenData(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", token.refresh_token),
        expires_at=time.time() + data.get("expires_in", 3600),
    )


def _decode_jwt_exp(token_str: str) -> float:
    try:
        payload = token_str.split(".")[1]
        # Fix base64 padding
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        return float(decoded["exp"])
    except (IndexError, KeyError, ValueError, json.JSONDecodeError):
        return time.time() + 3600


def token_from_manual(raw: str) -> TokenData:
    raw = raw.strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:]
    return TokenData(
        access_token=raw,
        refresh_token="",
        expires_at=_decode_jwt_exp(raw),
    )


def is_expired(token: TokenData, buffer_seconds: int = 300) -> bool:
    return time.time() >= (token.expires_at - buffer_seconds)
