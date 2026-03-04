# -*- coding: utf-8 -*-
"""Media downloader — download image URLs to local files for CLI processing.

When a channel (e.g. wecom) receives an image message, the image URL needs to
be downloaded to a local file so that the CLI (claude/codebuddy) can read it
via its built-in Read tool.

Files are stored directly in the CLI session directory (the same cwd where the
CLI executes) so that the CLI's Read tool can access them naturally.  A caller
may also supply an explicit ``dest_dir``; otherwise a fallback under
``/tmp/vh_images/<hash>/`` is used.
"""

import asyncio
import hashlib
import logging
import time
import uuid
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Defaults
FALLBACK_DIR_ROOT = Path("/tmp/vh_images")
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB
DOWNLOAD_TIMEOUT = 30  # seconds
IMAGE_TTL = 3600  # 1 hour — files older than this are eligible for cleanup

# MIME → extension mapping
MIME_EXT_MAP = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/svg+xml": ".svg",
}


def _fallback_dir(session_id: str) -> Path:
    """Return a per-session sub-directory under the fallback image root."""
    safe = hashlib.md5(session_id.encode()).hexdigest()[:12]
    return FALLBACK_DIR_ROOT / safe


def _guess_extension(url: str, mime_type: Optional[str] = None) -> str:
    """Guess file extension from MIME type or URL path."""
    if mime_type:
        ext = MIME_EXT_MAP.get(mime_type.lower())
        if ext:
            return ext
    # Fallback: parse URL path
    parsed = urlparse(url)
    path = parsed.path.lower()
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
        if path.endswith(ext):
            return ext if ext != ".jpeg" else ".jpg"
    return ".png"  # default


async def download_image(
    url: str,
    dest_dir: Optional[str] = None,
    session_id: str = "default",
    mime_type: Optional[str] = None,
    timeout: int = DOWNLOAD_TIMEOUT,
    max_size: int = MAX_IMAGE_SIZE,
    decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
) -> Optional[str]:
    """Download a single image URL to a local file.

    Args:
        url: Image URL to download.
        dest_dir: Target directory for the downloaded file.  When provided the
            image is saved directly into this directory (typically the CLI
            session cwd).  Falls back to ``/tmp/vh_images/<hash>/``.
        session_id: Used to derive fallback directory when *dest_dir* is None.
        mime_type: Optional MIME type hint for extension detection.
        timeout: HTTP request timeout in seconds.
        max_size: Maximum allowed image size in bytes.
        decrypt_fn: Optional callable ``(encrypted_bytes) -> decrypted_bytes``.

    Returns:
        Local file path on success, ``None`` on failure.
    """
    if dest_dir:
        out_dir = Path(dest_dir)
    else:
        out_dir = _fallback_dir(session_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"Image download failed: HTTP {resp.status_code} for {url}")
                return None
            data = resp.content
            if len(data) > max_size:
                logger.warning(f"Image data exceeds limit ({len(data)} bytes), skipping: {url}")
                return None

            # Prefer real filename from Content-Disposition header
            filename = None
            cd = resp.headers.get("content-disposition", "")
            if cd:
                filename = _parse_content_disposition_filename(cd)

            # Fallback: generate a name; prefer Content-Type from response
            # over the caller-supplied mime_type (which may be a guess).
            if not filename:
                resp_ct = resp.headers.get("content-type", "")
                # Strip parameters like "; charset=utf-8"
                resp_mime = resp_ct.split(";")[0].strip().lower() if resp_ct else ""
                ext = _guess_extension(url, resp_mime or mime_type)
                filename = f"img_{uuid.uuid4().hex[:8]}{ext}"

        # Decrypt if needed (e.g. WeCom encrypted media)
        if decrypt_fn:
            try:
                data = decrypt_fn(data)
            except Exception as e:
                logger.warning(f"Image decryption failed: {e} for {url}")
                return None

        # Sanitize filename
        filename = filename.replace("/", "_").replace("\\", "_")
        out_path = out_dir / filename
        # Avoid overwriting: append _1, _2, ... suffix if file exists
        if out_path.exists():
            stem = out_path.stem
            suffix = out_path.suffix
            counter = 1
            while out_path.exists():
                out_path = out_dir / f"{stem}_{counter}{suffix}"
                counter += 1
        out_path.write_bytes(data)
        logger.info(f"Downloaded image: {url} -> {out_path} ({len(data)} bytes)")
        return str(out_path)
    except httpx.TimeoutException:
        logger.warning(f"Image download timed out ({timeout}s): {url}")
        return None
    except Exception as e:
        logger.warning(f"Image download error: {e} for {url}")
        return None


async def download_images(
    urls: List[dict],
    dest_dir: Optional[str] = None,
    session_id: str = "default",
    decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
) -> List[str]:
    """Download multiple images concurrently.

    Args:
        urls: List of dicts with ``url`` and optional ``mime_type`` keys.
        dest_dir: Target directory (passed through to :func:`download_image`).
        session_id: Session ID for fallback directory isolation.
        decrypt_fn: Optional decryption function passed to each download.

    Returns:
        List of local file paths (only successful downloads).
    """
    tasks = [
        download_image(
            url=item["url"],
            dest_dir=dest_dir,
            session_id=session_id,
            mime_type=item.get("mime_type"),
            decrypt_fn=decrypt_fn,
        )
        for item in urls
        if item.get("url")
    ]
    if not tasks:
        return []
    results = await asyncio.gather(*tasks, return_exceptions=True)
    paths = []
    for r in results:
        if isinstance(r, str):
            paths.append(r)
        elif isinstance(r, Exception):
            logger.warning(f"Image download exception: {r}")
    return paths


def _parse_content_disposition_filename(header: str) -> Optional[str]:
    """Extract filename from a Content-Disposition header value."""
    import re as _re
    # Try filename*= (RFC 5987) first, e.g.: filename*=UTF-8''drawio.rar
    m = _re.search(r"filename\*\s*=\s*['\"]?(?:UTF-8''|utf-8'')(.+?)(?:['\";]|$)", header, _re.IGNORECASE)
    if m:
        from urllib.parse import unquote as _unquote
        return _unquote(m.group(1).strip())
    # Fallback: filename="..." or filename=...
    m = _re.search(r'filename\s*=\s*"([^"]+)"', header, _re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = _re.search(r"filename\s*=\s*([^\s;]+)", header, _re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


async def download_file(
    url: str,
    dest_dir: Optional[str] = None,
    session_id: str = "default",
    file_name: Optional[str] = None,
    timeout: int = DOWNLOAD_TIMEOUT,
    max_size: int = MAX_IMAGE_SIZE,
    decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
) -> Optional[str]:
    """Download a generic file URL to a local file.

    Unlike :func:`download_image`, this function preserves the original file
    name (when available) and does not assume the content is an image.

    Args:
        url: File URL to download.
        dest_dir: Target directory for the downloaded file.
        session_id: Used for fallback directory when *dest_dir* is None.
        file_name: Original file name hint (from the platform payload).
        timeout: HTTP request timeout in seconds.
        max_size: Maximum allowed file size in bytes.
        decrypt_fn: Optional callable ``(encrypted_bytes) -> decrypted_bytes``.
            When provided, the downloaded bytes are decrypted before writing.
            Used for WeCom file attachments which are AES-256-CBC encrypted.

    Returns:
        Local file path on success, ``None`` on failure.
    """
    if dest_dir:
        out_dir = Path(dest_dir)
    else:
        out_dir = _fallback_dir(session_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"File download failed: HTTP {resp.status_code} for {url}")
                return None
            data = resp.content
            if len(data) > max_size:
                logger.warning(f"File data exceeds limit ({len(data)} bytes), skipping: {url}")
                return None

            # Try to extract file name from Content-Disposition header
            if not file_name:
                cd = resp.headers.get("content-disposition", "")
                if cd:
                    file_name = _parse_content_disposition_filename(cd)

        # Decrypt if needed (e.g. WeCom encrypted file attachments)
        if decrypt_fn:
            try:
                data = decrypt_fn(data)
                logger.info(f"Decrypted file data ({len(data)} bytes)")
            except Exception as e:
                logger.warning(f"File decryption failed: {e} for {url}")
                return None

        # Determine file name: prefer explicit name, then URL path, then random
        if not file_name:
            parsed = urlparse(url)
            path_name = Path(parsed.path).name
            # Only use URL path name if it looks like a real file name
            if path_name and "." in path_name and len(path_name) < 200:
                file_name = path_name
            else:
                file_name = f"file_{uuid.uuid4().hex[:8]}"

        # Sanitize file name
        file_name = file_name.replace("/", "_").replace("\\", "_")
        # Avoid overwriting: prefix with short uuid if file exists
        out_path = out_dir / file_name
        if out_path.exists():
            stem = out_path.stem
            suffix = out_path.suffix
            file_name = f"{stem}_{uuid.uuid4().hex[:6]}{suffix}"
            out_path = out_dir / file_name

        out_path.write_bytes(data)
        logger.info(f"Downloaded file: {url[:120]} -> {out_path} ({len(data)} bytes)")
        return str(out_path)
    except httpx.TimeoutException:
        logger.warning(f"File download timed out ({timeout}s): {url}")
        return None
    except Exception as e:
        logger.warning(f"File download error: {e} for {url}")
        return None


async def download_files(
    items: List[dict],
    dest_dir: Optional[str] = None,
    session_id: str = "default",
    decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
) -> List[str]:
    """Download multiple files concurrently.

    Args:
        items: List of dicts with ``url`` and optional ``file_name`` keys.
        dest_dir: Target directory (passed through to :func:`download_file`).
        session_id: Session ID for fallback directory isolation.
        decrypt_fn: Optional decryption function passed to each download.

    Returns:
        List of local file paths (only successful downloads).
    """
    tasks = [
        download_file(
            url=item["url"],
            dest_dir=dest_dir,
            session_id=session_id,
            file_name=item.get("file_name"),
            decrypt_fn=decrypt_fn,
        )
        for item in items
        if item.get("url")
    ]
    if not tasks:
        return []
    results = await asyncio.gather(*tasks, return_exceptions=True)
    paths = []
    for r in results:
        if isinstance(r, str):
            paths.append(r)
        elif isinstance(r, Exception):
            logger.warning(f"File download exception: {r}")
    return paths


def cleanup_old_images(ttl: int = IMAGE_TTL) -> int:
    """Remove image files older than *ttl* seconds. Returns count of removed files."""
    if not FALLBACK_DIR_ROOT.exists():
        return 0
    cutoff = time.time() - ttl
    removed = 0
    for session_dir in FALLBACK_DIR_ROOT.iterdir():
        if not session_dir.is_dir():
            continue
        for f in session_dir.iterdir():
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except Exception:
                pass
        # Remove empty session dirs
        try:
            if not any(session_dir.iterdir()):
                session_dir.rmdir()
        except Exception:
            pass
    if removed:
        logger.info(f"Cleaned up {removed} old image file(s)")
    return removed
