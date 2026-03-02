from dataclasses import dataclass
from datetime import datetime


@dataclass
class TokenData:
    access_token: str
    refresh_token: str
    expires_at: float  # unix timestamp


@dataclass
class MediaItem:
    id: str
    filename: str
    capture_time: datetime
    media_type: str  # Video, Photo, TimeLapse, Burst
    file_size: int
    width: int
    height: int
