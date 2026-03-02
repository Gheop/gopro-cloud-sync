import asyncio
from pathlib import Path

import httpx
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from . import api
from .db import SyncDB
from .models import MediaItem

CHUNK_SIZE = 1024 * 1024  # 1 MB


def compute_dest_path(item: MediaItem, output_dir: Path) -> Path:
    ct = item.capture_time
    date_dir = output_dir / f"{ct.year}" / f"{ct.month:02d}" / f"{ct.day:02d}"
    return date_dir / item.filename


async def download_one(
    client: httpx.AsyncClient,
    item: MediaItem,
    output_dir: Path,
    db: SyncDB,
    progress: Progress,
    task_id: int,
    max_retries: int = 3,
) -> bool:
    dest = compute_dest_path(item, output_dir)
    part = dest.with_suffix(dest.suffix + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        db.mark_done(item.id, str(dest))
        progress.update(task_id, completed=item.file_size or 1, total=item.file_size or 1)
        return True

    db.mark_downloading(item.id)

    for attempt in range(max_retries):
        try:
            # Fetch fresh signed URL each attempt
            url = await api.get_download_url(client, item.id)

            headers = {}
            existing_size = 0
            if part.exists():
                existing_size = part.stat().st_size
                headers["Range"] = f"bytes={existing_size}-"

            async with client.stream("GET", url, headers=headers, follow_redirects=True) as resp:
                if resp.status_code == 416:
                    # Range not satisfiable = file is complete
                    part.rename(dest)
                    db.mark_done(item.id, str(dest))
                    progress.update(task_id, completed=item.file_size or 1, total=item.file_size or 1)
                    return True

                if resp.status_code == 200 and existing_size > 0:
                    # Server doesn't support range, restart
                    existing_size = 0
                    part.unlink(missing_ok=True)

                resp.raise_for_status()

                total = int(resp.headers.get("content-length", 0)) + existing_size
                progress.update(task_id, completed=existing_size, total=total or None)

                mode = "ab" if resp.status_code == 206 else "wb"
                with open(part, mode) as f:
                    async for chunk in resp.aiter_bytes(CHUNK_SIZE):
                        f.write(chunk)
                        progress.advance(task_id, len(chunk))

            part.rename(dest)
            db.mark_done(item.id, str(dest))
            return True

        except (httpx.HTTPStatusError, httpx.TransportError, api.APIError) as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** (attempt + 1))
                continue
            db.mark_error(item.id, str(e))
            return False

    return False


async def download_all(
    items: list[MediaItem],
    output_dir: Path,
    client: httpx.AsyncClient,
    db: SyncDB,
    concurrency: int = 5,
) -> tuple[int, int]:
    """Download all items concurrently. Returns (success_count, error_count)."""
    sem = asyncio.Semaphore(concurrency)
    success = 0
    errors = 0

    progress = Progress(
        TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
        BarColumn(bar_width=30),
        "[progress.percentage]{task.percentage:>3.0f}%",
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
    )

    async def _download(item: MediaItem, task_id: int) -> bool:
        async with sem:
            return await download_one(client, item, output_dir, db, progress, task_id)

    with progress:
        tasks = []
        for item in items:
            tid = progress.add_task(
                item.filename,
                filename=item.filename[:30],
                total=item.file_size or None,
            )
            tasks.append(_download(item, tid))

        results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        if r is True:
            success += 1
        else:
            errors += 1

    return success, errors
