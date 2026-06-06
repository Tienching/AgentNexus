import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.runtime.executors.base import RequestContext
from src.server.services.stream_handler import StreamHandler


def test_group_history_request_forces_fresh_codebuddy_session():
    handler = StreamHandler.__new__(StreamHandler)
    request = RequestContext(
        content='总结一下这个群的聊天记录\n---\n<context 会话类型="群聊" 群ID="ww115008752732540" />',
        user="jonaszchen",
        session_id="4dbb580a-4099-4c3c-a2d8-1eb041fefcb6",
        cli_session_id="old-codebuddy-session",
        model_changed=False,
    )

    assert handler._prepare_fresh_agenthub_history_request(request) is True

    assert request.cli_session_id is None
    assert request.model_changed is True
    assert request.metadata["force_fresh_agenthub_history"] is True
    assert "必须重新调用 `agenthub-data`" in request.content
    assert "不得复用本会话中任何此前" in request.content
    assert "总结一下这个群的聊天记录" in request.content


def test_non_history_request_keeps_existing_codebuddy_session():
    handler = StreamHandler.__new__(StreamHandler)
    request = RequestContext(
        content="请对这个端口告警做 RCA 诊断",
        cli_session_id="old-codebuddy-session",
        model_changed=False,
    )

    assert handler._prepare_fresh_agenthub_history_request(request) is False

    assert request.cli_session_id == "old-codebuddy-session"
    assert request.model_changed is False
    assert "force_fresh_agenthub_history" not in request.metadata
