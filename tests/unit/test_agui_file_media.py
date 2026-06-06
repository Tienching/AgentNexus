# -*- coding: utf-8 -*-

from pathlib import Path

import pytest

from src.providers.base import RequestContext
from src.runtime.events.agui import AGUIRequest
from src.server.config import settings
from src.server.routers.chat import _has_agui_media_debug_signal
from src.server.services import stream_handler
from src.server.services.stream_handler import StreamHandler


def test_agui_media_debug_signal_detects_message_binary_url():
    assert _has_agui_media_debug_signal(
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "分析附件"},
                        {
                            "type": "binary",
                            "mimeType": "application/gzip",
                            "url": "http://127.0.0.1:18080/diag.gz",
                            "fileName": "diag.gz",
                        },
                    ],
                }
            ]
        }
    )


def test_agui_binary_file_part_preserves_file_name():
    request = AGUIRequest.model_validate(
        {
            "threadId": "thread-file-name",
            "runId": "run-file-name",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "分析这个文件"},
                        {
                            "type": "binary",
                            "mimeType": "application/pdf",
                            "url": "https://example.com/report.pdf",
                            "fileName": "report.pdf",
                        },
                    ],
                }
            ],
        }
    )

    assert request.get_user_content_parts() == [
        {"type": "text", "content": "分析这个文件"},
        {
            "type": "file",
            "url": "https://example.com/report.pdf",
            "mime_type": "application/pdf",
            "file_name": "report.pdf",
        },
    ]


@pytest.mark.asyncio
async def test_agui_file_url_is_downloaded_and_replaced_with_local_path(tmp_path, monkeypatch):
    local_file = tmp_path / "report.pdf"
    local_file.write_bytes(b"%PDF-1.4 test")
    captured = {}

    async def fake_download_files_with_sources(items, **kwargs):
        captured["items"] = items
        captured["dest_dir"] = kwargs.get("dest_dir")
        captured["session_id"] = kwargs.get("session_id")
        return [(items[0], str(local_file))]

    monkeypatch.setattr(settings, "user_home_base", str(tmp_path))
    monkeypatch.setattr(
        stream_handler,
        "download_files_with_sources",
        fake_download_files_with_sources,
        raising=False,
    )

    request = RequestContext(
        content="请总结附件",
        user="tester",
        session_id="agui-file-session",
        exec_user="tester",
        content_parts=[
            {"type": "text", "content": "请总结附件"},
            {
                "type": "file",
                "url": "https://example.com/report.pdf",
                "mime_type": "application/pdf",
                "file_name": "report.pdf",
            },
        ],
    )

    handler = StreamHandler.__new__(StreamHandler)
    await handler._localize_agui_image_parts(request, "agui-file-session", "tester")

    assert captured["items"] == [
        {
            "url": "https://example.com/report.pdf",
            "mime_type": "application/pdf",
            "file_name": "report.pdf",
        }
    ]
    assert Path(captured["dest_dir"]).name == "agui-file-session"
    assert captured["session_id"] == "agui-file-session"
    assert request.content_parts == [
        {"type": "text", "content": "请总结附件"},
        {
            "type": "file",
            "url": "https://example.com/report.pdf",
            "mime_type": "application/pdf",
            "file_name": "report.pdf",
            "path": str(local_file),
        },
    ]
    assert request.file_paths == [str(local_file)]


@pytest.mark.asyncio
async def test_agui_top_level_binary_content_part_is_downloaded(tmp_path, monkeypatch):
    local_file = tmp_path / "DEBUG_STAT_COUN.1780578903.94.core.gz"
    local_file.write_bytes(b"gzip data")
    captured = {}

    async def fake_download_files_with_sources(items, **kwargs):
        captured["items"] = items
        captured["dest_dir"] = kwargs.get("dest_dir")
        return [(items[0], str(local_file))]

    monkeypatch.setattr(settings, "user_home_base", str(tmp_path))
    monkeypatch.setattr(
        stream_handler,
        "download_files_with_sources",
        fake_download_files_with_sources,
        raising=False,
    )

    agui_request = AGUIRequest.model_validate(
        {
            "threadId": "agui-top-level-file-session",
            "runId": "run-top-level-file",
            "messages": [{"role": "user", "content": "请分析附件"}],
            "content_parts": [
                {"type": "text", "content": "请分析附件"},
                {
                    "type": "binary",
                    "mimeType": "application/gzip",
                    "url": "https://example.com/DEBUG_STAT_COUN.1780578903.94.core.gz",
                    "fileName": "DEBUG_STAT_COUN.1780578903.94.core.gz",
                },
            ],
        }
    )

    request = RequestContext(
        content=agui_request.get_user_content(),
        user="tester",
        session_id=agui_request.threadId,
        exec_user="tester",
        content_parts=list(agui_request.content_parts),
    )

    handler = StreamHandler.__new__(StreamHandler)
    await handler._localize_agui_image_parts(request, agui_request.threadId, "tester")

    assert captured["items"] == [
        {
            "url": "https://example.com/DEBUG_STAT_COUN.1780578903.94.core.gz",
            "mime_type": "application/gzip",
            "file_name": "DEBUG_STAT_COUN.1780578903.94.core.gz",
        }
    ]
    assert Path(captured["dest_dir"]).name == "agui-top-level-file-session"
    assert request.file_paths == [str(local_file)]


@pytest.mark.asyncio
async def test_agui_file_part_filename_alias_is_passed_to_downloader(tmp_path, monkeypatch):
    local_file = tmp_path / "report.pdf"
    local_file.write_bytes(b"%PDF-1.4 test")
    captured = {}

    async def fake_download_files_with_sources(items, **kwargs):
        captured["items"] = items
        return [(items[0], str(local_file))]

    monkeypatch.setattr(settings, "user_home_base", str(tmp_path))
    monkeypatch.setattr(
        stream_handler,
        "download_files_with_sources",
        fake_download_files_with_sources,
        raising=False,
    )

    request = RequestContext(
        content="请总结附件",
        user="tester",
        session_id="agui-file-session",
        exec_user="tester",
        content_parts=[
            {"type": "text", "content": "请总结附件"},
            {
                "type": "file",
                "url": "https://example.com/report.pdf",
                "mime_type": "application/pdf",
                "filename": "report.pdf",
            },
        ],
    )

    handler = StreamHandler.__new__(StreamHandler)
    await handler._localize_agui_image_parts(request, "agui-file-session", "tester")

    assert captured["items"] == [
        {
            "url": "https://example.com/report.pdf",
            "mime_type": "application/pdf",
            "file_name": "report.pdf",
        }
    ]


@pytest.mark.asyncio
async def test_agui_wecom_media_reference_can_be_resolved_to_local_path(tmp_path, monkeypatch):
    local_file = tmp_path / "diag.tar"
    local_file.write_bytes(b"tar data")
    captured = {}

    async def fake_download_files_with_sources(items, **kwargs):
        captured["items"] = items
        captured["dest_dir"] = kwargs.get("dest_dir")
        captured["session_id"] = kwargs.get("session_id")
        return [(items[0], str(local_file))]

    monkeypatch.setattr(settings, "user_home_base", str(tmp_path))
    monkeypatch.setattr(
        stream_handler,
        "download_files_with_sources",
        fake_download_files_with_sources,
        raising=False,
    )

    request = RequestContext(
        content="列一下附件里的文件",
        user="tester",
        session_id="agui-wecom-file-session",
        exec_user="tester",
        content_parts=[
            {"type": "text", "content": "列一下附件里的文件"},
            {
                "type": "file",
                "url": "wecom://media/abc123",
                "mime_type": "application/octet-stream",
                "file_name": "diag.tar",
            },
        ],
    )

    handler = StreamHandler.__new__(StreamHandler)
    await handler._localize_agui_image_parts(request, "agui-wecom-file-session", "tester")

    assert captured["items"] == [
        {
            "url": "wecom://media/abc123",
            "mime_type": "application/octet-stream",
            "file_name": "diag.tar",
        }
    ]
    assert Path(captured["dest_dir"]).name == "agui-wecom-file-session"
    assert captured["session_id"] == "agui-wecom-file-session"
    assert request.content_parts == [
        {"type": "text", "content": "列一下附件里的文件"},
        {
            "type": "file",
            "url": "wecom://media/abc123",
            "mime_type": "application/octet-stream",
            "file_name": "diag.tar",
            "path": str(local_file),
        },
    ]
    assert request.file_paths == [str(local_file)]


@pytest.mark.asyncio
async def test_agui_wecom_media_reference_without_resolver_is_not_treated_as_local_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "user_home_base", str(tmp_path))

    request = RequestContext(
        content="列一下附件里的文件",
        user="tester",
        session_id="agui-wecom-file-session",
        exec_user="tester",
        content_parts=[
            {"type": "text", "content": "列一下附件里的文件"},
            {
                "type": "file",
                "url": "wecom://media/abc123",
                "mime_type": "application/octet-stream",
                "file_name": "diag.tar",
            },
        ],
    )

    handler = StreamHandler.__new__(StreamHandler)
    await handler._localize_agui_image_parts(request, "agui-wecom-file-session", "tester")

    assert request.file_paths == []
    assert all(
        part.get("path") != "wecom://media/abc123"
        for part in request.content_parts
        if isinstance(part, dict)
    )
    assert request.content_parts == [
        {"type": "text", "content": "列一下附件里的文件"},
        {
            "type": "text",
            "content": (
                '[附件未落地] 用户上传的文件 "diag.tar" 只包含 wecom://media 引用，'
                "当前服务未配置该协议解析器或解析失败，因此还没有本地文件可读。"
                "请不要改用设备远程 DIAG 兜底，应要求上游提供可下载 URL/本地路径后再处理该附件。"
            ),
        },
    ]
