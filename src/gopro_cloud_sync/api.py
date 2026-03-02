import asyncio
from collections.abc import AsyncIterator
from datetime import datetime

import httpx

from .models import MediaItem

BASE_URL = "https://api.gopro.com"


class APIError(Exception):
    pass


class RateLimitError(APIError):
    pass


async def list_media(
    client: httpx.AsyncClient, page: int = 1, per_page: int = 100
) -> tuple[list[MediaItem], int]:
    """Fetch a page of media items. Returns (items, total_count)."""
    resp = await client.get(
        f"{BASE_URL}/media/search",
        params={
            "per_page": per_page,
            "page": page,
            "order_by": "captured_at",
            "order": "desc",
        },
    )
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", "5"))
        raise RateLimitError(f"Rate limited, retry after {retry_after}s")
    resp.raise_for_status()

    data = resp.json()
    total = data.get("_pages", {}).get("total_items", 0)
    raw_media = data.get("_embedded", {}).get("media", [])

    items = []
    for m in raw_media:
        try:
            capture_str = m.get("captured_at", m.get("created_at", ""))
            capture_time = datetime.fromisoformat(capture_str.replace("Z", "+00:00"))
            items.append(
                MediaItem(
                    id=m["id"],
                    filename=m.get("filename", f"{m['id']}.mp4"),
                    capture_time=capture_time,
                    media_type=m.get("type", "Video"),
                    file_size=m.get("file_size", 0),
                    width=m.get("width", 0),
                    height=m.get("height", 0),
                )
            )
        except (KeyError, ValueError):
            continue

    return items, total


async def list_all_media(client: httpx.AsyncClient) -> AsyncIterator[MediaItem]:
    """Paginate through all media items."""
    page = 1
    per_page = 100
    max_retries = 3

    while True:
        for attempt in range(max_retries):
            try:
                items, total = await list_media(client, page=page, per_page=per_page)
                break
            except RateLimitError:
                wait = 2 ** (attempt + 1)
                await asyncio.sleep(wait)
        else:
            raise APIError(f"Failed to fetch page {page} after {max_retries} retries")

        for item in items:
            yield item

        if page * per_page >= total:
            break
        page += 1


async def get_download_url(client: httpx.AsyncClient, media_id: str) -> str:
    """Get the signed S3 download URL for a media item."""
    resp = await client.get(f"{BASE_URL}/media/{media_id}/download")
    if resp.status_code == 404:
        raise APIError(f"Media {media_id} not found in cloud")
    if resp.status_code == 429:
        raise RateLimitError("Rate limited on download URL fetch")
    resp.raise_for_status()

    data = resp.json()

    # Try different response structures observed in the wild
    # Structure 1: _embedded.files[].url
    files = data.get("_embedded", {}).get("files", [])
    if files:
        # Prefer the "source" type file
        for f in files:
            if f.get("type") == "source":
                return f["url"]
        return files[0]["url"]

    # Structure 2: _embedded.variations[].url
    variations = data.get("_embedded", {}).get("variations", [])
    if variations:
        return variations[0]["url"]

    # Structure 3: direct url field
    if "url" in data:
        return data["url"]

    raise APIError(f"Could not extract download URL for {media_id}: {data}")
