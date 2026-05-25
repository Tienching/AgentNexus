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
CODEBUDDY_REFERENCE_MAX_IMAGE_SIZE = 1024 * 1024  # CodeBuddy @file pre-read limit
CLI_IMAGE_TARGET_MAX_SIZE = 900 * 1024  # Leave headroom below the CodeBuddy limit
CLI_IMAGE_MAX_DIMENSION = 1800
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


def _has_whitespace_path(path: Path) -> bool:
    return any(ch.isspace() for ch in str(path))


def _safe_cli_image_path(path: Path, suffix: str) -> Path:
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:10]
    safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return path.with_name(f"img_cli_{digest}{safe_suffix.lower()}")


def _copy_to_safe_cli_path(path: Path) -> str:
    suffix = path.suffix or ".png"
    target = _safe_cli_image_path(path, suffix)
    if target == path:
        return str(path)
    target.write_bytes(path.read_bytes())
    return str(target)


def _resample_lanczos():
    from PIL import Image

    return getattr(getattr(Image, "Resampling", Image), "LANCZOS")


def _image_to_rgb(image):
    from PIL import Image

    has_alpha = image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    )
    if not has_alpha:
        return image.convert("RGB")

    rgba = image.convert("RGBA")
    background = Image.new("RGB", rgba.size, (255, 255, 255))
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background


def _resize_to_max_dimension(image, max_dimension: int):
    if max_dimension <= 0:
        return image
    width, height = image.size
    largest = max(width, height)
    if largest <= max_dimension:
        return image
    scale = max_dimension / float(largest)
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(new_size, _resample_lanczos())


def prepare_image_for_cli(
    path: str,
    *,
    target_max_size: int = CLI_IMAGE_TARGET_MAX_SIZE,
    reference_max_size: int = CODEBUDDY_REFERENCE_MAX_IMAGE_SIZE,
    max_dimension: int = CLI_IMAGE_MAX_DIMENSION,
) -> str:
    """Prepare an image path so CodeBuddy can consume it via native @path input.

    This only rewrites the local image file. It does not OCR, summarize, or turn
    the image into text; the returned path is still passed to CodeBuddy as an
    image reference.
    """
    source = Path(path)
    try:
        source_size = source.stat().st_size
    except OSError:
        return path

    needs_safe_path = _has_whitespace_path(source)
    if source_size <= reference_max_size and not needs_safe_path:
        return str(source)

    if source.suffix.lower() == ".svg":
        return _copy_to_safe_cli_path(source) if needs_safe_path else str(source)

    try:
        from PIL import Image, ImageOps
    except Exception:
        logger.warning("Pillow unavailable; cannot compress image for CLI: %s", source)
        return _copy_to_safe_cli_path(source) if needs_safe_path else str(source)

    output = _safe_cli_image_path(source, ".jpg")
    try:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()
        working = _resize_to_max_dimension(_image_to_rgb(image), max_dimension)

        qualities = (85, 75, 65, 55, 45)
        for _ in range(10):
            for quality in qualities:
                working.save(output, "JPEG", quality=quality, optimize=True, progressive=True)
                output_size = output.stat().st_size
                if output_size <= target_max_size:
                    logger.info(
                        "Prepared image for CLI: %s -> %s (%d bytes)",
                        source,
                        output,
                        output_size,
                    )
                    return str(output)

            width, height = working.size
            if max(width, height) <= 512:
                break
            working = working.resize(
                (max(1, int(width * 0.85)), max(1, int(height * 0.85))),
                _resample_lanczos(),
            )

        if output.exists() and output.stat().st_size < source_size:
            logger.warning(
                "Image remains above CLI target after compression: %s -> %s (%d bytes)",
                source,
                output,
                output.stat().st_size,
            )
            return str(output)
    except Exception as exc:
        logger.warning("Image compression failed for %s: %s", source, exc)

    return _copy_to_safe_cli_path(source) if needs_safe_path else str(source)


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
        prepared_path = await asyncio.to_thread(prepare_image_for_cli, str(out_path))
        logger.info(f"Downloaded image: {url} -> {prepared_path} ({len(data)} bytes)")
        return prepared_path
    except httpx.TimeoutException:
        logger.warning(f"Image download timed out ({timeout}s): {url}")
        return None
    except Exception as e:
        logger.warning(f"Image download error: {e} for {url}")
        return None


async def download_images_with_sources(
    urls: List[dict],
    dest_dir: Optional[str] = None,
    session_id: str = "default",
    decrypt_fn: Optional[Callable[[bytes], bytes]] = None,
) -> list[tuple[dict, str]]:
    """Download multiple images while preserving each successful source item."""
    items = [item for item in urls if item.get("url")]
    tasks = [
        download_image(
            url=item["url"],
            dest_dir=dest_dir,
            session_id=session_id,
            mime_type=item.get("mime_type"),
            decrypt_fn=decrypt_fn,
        )
        for item in items
    ]
    if not tasks:
        return []

    results = await asyncio.gather(*tasks, return_exceptions=True)
    pairs: list[tuple[dict, str]] = []
    for item, result in zip(items, results):
        if isinstance(result, str):
            pairs.append((item, result))
        elif isinstance(result, Exception):
            logger.warning(f"Image download exception: {result}")
    return pairs


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
    pairs = await download_images_with_sources(
        urls, dest_dir=dest_dir, session_id=session_id, decrypt_fn=decrypt_fn
    )
    return [path for _, path in pairs]


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
