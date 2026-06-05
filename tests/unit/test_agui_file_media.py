# -*- coding: utf-8 -*-

from pathlib import Path

import pytest

from src.providers.base import RequestContext
from src.runtime.events.agui import AGUIRequest
from src.server.config import settings
from src.server.services import stream_handler
from src.server.services.stream_handler import StreamHandler


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
