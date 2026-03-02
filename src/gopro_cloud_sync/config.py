import json
import os
from pathlib import Path

from .models import TokenData

CONFIG_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "gopro-cloud-sync"
)
CONFIG_FILE = CONFIG_DIR / "config.json"


def load() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text())


def save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.chmod(tmp, 0o600)
    tmp.rename(CONFIG_FILE)


def get_token() -> TokenData | None:
    data = load()
    t = data.get("token")
    if not t:
        return None
    return TokenData(
        access_token=t["access_token"],
        refresh_token=t.get("refresh_token", ""),
        expires_at=t.get("expires_at", 0),
    )


def set_token(token: TokenData) -> None:
    data = load()
    data["token"] = {
        "access_token": token.access_token,
        "refresh_token": token.refresh_token,
        "expires_at": token.expires_at,
    }
    save(data)


def clear_token() -> None:
    data = load()
    data.pop("token", None)
    save(data)
