# -*- coding: utf-8 -*-

from pathlib import Path

import pytest
from PIL import Image

from src.server.services import media_downloader
from src.server.services.media_downloader import prepare_image_for_cli


def _large_noise_png(path: Path) -> None:
    image = Image.effect_noise((1800, 1800), 100).convert("RGB")
    image.save(path, format="PNG")


def test_prepare_image_for_cli_compresses_large_image_under_reference_limit(tmp_path):
    source = tmp_path / "large.png"
    _large_noise_png(source)
    assert source.stat().st_size > 1024 * 1024

    prepared = Path(
        prepare_image_for_cli(
            str(source),
            target_max_size=900 * 1024,
            reference_max_size=1024 * 1024,
            max_dimension=1600,
        )
    )

    assert prepared.exists()
    assert prepared != source
    assert prepared.name.startswith("img_cli_")
    assert prepared.suffix == ".jpg"
    assert prepared.stat().st_size <= 1024 * 1024
    assert source.exists()


def test_prepare_image_for_cli_keeps_small_safe_image_path(tmp_path):
    source = tmp_path / "small.png"
    Image.new("RGB", (64, 64), "white").save(source, format="PNG")

    prepared = prepare_image_for_cli(str(source), reference_max_size=1024 * 1024)

    assert prepared == str(source)


def test_prepare_image_for_cli_copies_small_path_with_whitespace(tmp_path):
    source = tmp_path / "screen shot.png"
    Image.new("RGB", (64, 64), "white").save(source, format="PNG")

    prepared = Path(prepare_image_for_cli(str(source), reference_max_size=1024 * 1024))

    assert prepared.exists()
    assert prepared != source
    assert " " not in prepared.name


@pytest.mark.asyncio
async def test_download_images_with_sources_keeps_url_mapping_when_some_downloads_fail(monkeypatch):
    items = [
        {"url": "https://example.com/first.png", "mime_type": "image/png"},
        {"url": "https://example.com/second.png", "mime_type": "image/png"},
        {"url": "https://example.com/third.png", "mime_type": "image/png"},
    ]

    async def fake_download_image(url, **_kwargs):
        return {
            "https://example.com/first.png": None,
            "https://example.com/second.png": "/tmp/second.png",
            "https://example.com/third.png": "/tmp/third.png",
        }[url]

    monkeypatch.setattr(media_downloader, "download_image", fake_download_image)

    assert await media_downloader.download_images_with_sources(items) == [
        (items[1], "/tmp/second.png"),
        (items[2], "/tmp/third.png"),
    ]


@pytest.mark.asyncio
async def test_download_files_with_sources_uses_agui_media_resolver_for_wecom_reference(monkeypatch):
    item = {
        "url": "wecom://media/abc123",
        "mime_type": "application/octet-stream",
        "file_name": "diag.tar",
    }
    calls = []

    async def fake_resolver(url, **kwargs):
        calls.append((url, kwargs))
        return "/tmp/diag.tar"

    monkeypatch.setattr(media_downloader, "_download_file_via_agui_media_resolver", fake_resolver)

    assert await media_downloader.download_files_with_sources([item], dest_dir="/tmp/session", session_id="sess") == [
        (item, "/tmp/diag.tar")
    ]
    assert calls == [
        (
            "wecom://media/abc123",
            {
                "dest_dir": "/tmp/session",
                "session_id": "sess",
                "file_name": "diag.tar",
                "mime_type": "application/octet-stream",
                "timeout": media_downloader.DOWNLOAD_TIMEOUT,
                "max_size": media_downloader.MAX_IMAGE_SIZE,
            },
        )
    ]


def test_write_file_bytes_improves_generic_drawio_filename(tmp_path):
    path = media_downloader._write_file_bytes(
        b"<mxfile host=\"app.diagrams.net\"></mxfile>",
        dest_dir=str(tmp_path),
        session_id="sess",
        source_url="https://example.com/file.bin",
        file_name="file.bin",
        max_size=media_downloader.MAX_IMAGE_SIZE,
    )

    assert path is not None
    assert Path(path).name == "file.drawio"
