import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
JS_ROOT = ROOT / "src/server/static/nexus/js"


def test_streaming_tool_call_ids_are_not_interpolated_into_markup_or_selectors():
    app_source = (JS_ROOT / "app.js").read_text(encoding="utf-8")
    controller_source = (JS_ROOT / "components/streaming-controller.js").read_text(encoding="utf-8")
    task_board_source = (JS_ROOT / "components/task-board-panel.js").read_text(encoding="utf-8")

    assert 'data-streaming-tool-id="${toolCallId}"' not in app_source
    assert "streaming-tool-args-${toolCallId}" not in app_source
    assert 'data-streaming-tool-id="${toolCall.id}"' not in controller_source
    assert "streaming-tool-args-${toolCall.id}" not in controller_source
    assert 'data-streaming-tool-id="${toolCall.id}"' not in task_board_source
    assert "streaming-tool-args-${toolCall.id}" not in task_board_source
    assert "toolCallDomToken" in app_source
    assert "toolCallDomToken" in controller_source
    assert "toolCallDomToken" in task_board_source


def test_tool_call_dom_token_contains_only_selector_safe_characters():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required for the frontend token behavior test")

    controller_path = JS_ROOT / "components/streaming-controller.js"
    malicious_id = '\" onmouseover=\"globalThis.pwned=true\"><script>alert(1)</script>'
    script = f"""
global.window = {{}};
const fs = require('fs');
eval(fs.readFileSync({json.dumps(str(controller_path))}, 'utf8'));
const token = window.NexusStreamingController.toolCallDomToken({json.dumps(malicious_id)});
if (!/^[0-9a-f-]+$/.test(token)) process.exit(2);
if (token.includes('script') || token.includes('onmouseover') || token.includes('"')) process.exit(3);
process.stdout.write(token);
"""
    completed = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

    assert completed.stdout
