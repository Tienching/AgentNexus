"""Regression tests for fenced-code-block handling in the Nexus markdown renderer.

Background
----------
The frontend markdown renderer used to require the closing ``` fence to sit on
its own line (regex ``/^```\\s*$/``). When the LLM stream emitted a fenced block
without a trailing newline before the closer (for example ``}```\\n# Heading``
or ``}```Next sentence``), the parser failed to recognise the close and
swallowed the rest of the document as code, breaking every following heading,
list, and paragraph.

These tests pin two things:

1. **Static guard** — neither renderer source file re-introduces the strict
   ``^```\\s*$`` closing-fence regex.
2. **Runtime behaviour** — when we feed malformed fences through the component
   renderer (executed under Node's ``vm`` module), the rest of the markdown
   document still renders as markdown, not as an unterminated ``<pre>``.

If a future change weakens the tolerance, both of these will fail loudly.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "src/server/static/nexus/js/app.js"
COMPONENT_JS = ROOT / "src/server/static/nexus/js/components/markdown-renderer.js"


# ---------------------------------------------------------------------------
# Static guards
# ---------------------------------------------------------------------------


def test_app_renderer_does_not_use_strict_closing_fence_regex():
    """A regression to the strict ``/^```\\s*$/`` closer would re-introduce
    the bug where a fence without a trailing newline swallows the rest of
    the document."""
    src = APP_JS.read_text(encoding="utf-8")
    # The strict pattern must not appear in the renderer body.
    assert "/^```\\s*$/" not in src, (
        "app.js renderMarkdown re-introduced the strict closing-fence regex; "
        "this regresses the malformed-fence handling fix."
    )
    # The tolerant scan must still be present.
    assert "indexOf('```')" in src, (
        "app.js renderMarkdown lost the tolerant closing-fence scan."
    )


def test_component_renderer_does_not_use_strict_closing_fence_regex():
    src = COMPONENT_JS.read_text(encoding="utf-8")
    assert "/^```\\s*$/" not in src, (
        "markdown-renderer.js renderFallback re-introduced the strict "
        "closing-fence regex; this regresses the malformed-fence handling fix."
    )
    assert "indexOf('```')" in src, (
        "markdown-renderer.js renderFallback lost the tolerant closing-fence scan."
    )


# ---------------------------------------------------------------------------
# Runtime behaviour (component renderer, executed under Node)
# ---------------------------------------------------------------------------


_NODE_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');

const rendererPath = process.argv[2];
const casesPath = process.argv[3];

const src = fs.readFileSync(rendererPath, 'utf8');
const cases = JSON.parse(fs.readFileSync(casesPath, 'utf8'));

// Provide a minimal browser-like sandbox. The component's static escapeHtml
// uses document.createElement; we stub it with a textContent-like escape.
const sandbox = {
    window: {},
    document: {
        createElement: () => {
            let _text = '';
            return {
                set textContent(v) { _text = String(v == null ? '' : v); },
                get innerHTML() {
                    return _text
                        .replace(/&/g, '&amp;')
                        .replace(/</g, '&lt;')
                        .replace(/>/g, '&gt;')
                        .replace(/"/g, '&quot;');
                },
            };
        },
    },
    console,
};
vm.createContext(sandbox);
vm.runInContext(src, sandbox);

const Renderer = sandbox.window.MarkdownRenderer;
const renderer = new Renderer();

const out = {};
for (const [name, input] of Object.entries(cases)) {
    out[name] = renderer.render(input);
}
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def rendered():
    if shutil.which("node") is None:
        pytest.skip("node binary not available; skipping runtime renderer test")

    cases = {
        # Closing fence on its own line — baseline good case.
        "well_formed": "```json\n{\"a\": 1}\n```\n# After\n",
        # Closing fence glued to the previous code line (no newline before ```).
        "closer_glued_to_code": "```json\n{\"a\": 1}```\n# After\n",
        # Closing fence followed immediately by next markdown block on same line.
        "closer_glued_to_next_block": "```json\n{\"a\": 1}\n```# After\n",
        # Both glued: classic streaming artefact described in the bug report.
        "fully_glued": "```json\n{\"a\": 1}```# After\n",
        # No closing fence at all — should not eat the document; renders what it has.
        "unterminated": "```json\n{\"a\": 1}\nstill code line\n",
    }

    proc = None
    with tempfile.TemporaryDirectory() as tmp:
        harness_path = Path(tmp) / "harness.js"
        cases_path = Path(tmp) / "cases.json"
        harness_path.write_text(_NODE_HARNESS, encoding="utf-8")
        cases_path.write_text(json.dumps(cases), encoding="utf-8")
        proc = subprocess.run(
            ["node", str(harness_path), str(COMPONENT_JS), str(cases_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    if proc.returncode != 0:
        pytest.fail(
            "renderer harness failed:\nstdout=%s\nstderr=%s"
            % (proc.stdout, proc.stderr)
        )
    return json.loads(proc.stdout)


def test_well_formed_fence_renders_heading_after_block(rendered):
    html = rendered["well_formed"]
    assert "<pre" in html and "</pre>" in html
    assert "<h1>After</h1>" in html


def test_closer_glued_to_code_still_ends_block(rendered):
    """``}``` on the same line should close the fence, not be treated as code."""
    html = rendered["closer_glued_to_code"]
    # The heading after the fence must render as a heading.
    assert "<h1>After</h1>" in html, html
    # Exactly one <pre> block — the heading wasn't sucked into code.
    assert html.count("<pre") == 1, html


def test_closer_glued_to_next_block_still_ends_block(rendered):
    """``\\n```# After`` — no trailing newline before the next block."""
    html = rendered["closer_glued_to_next_block"]
    assert "<h1>After</h1>" in html, html
    assert html.count("<pre") == 1, html
    # The literal "```# After" must not appear in the rendered output.
    assert "```# After" not in html, html


def test_fully_glued_fence_recovers(rendered):
    """The exact pattern from the bug report: closer glued on both sides."""
    html = rendered["fully_glued"]
    assert "<h1>After</h1>" in html, html
    assert html.count("<pre") == 1, html


def test_unterminated_fence_does_not_swallow_document(rendered):
    """An unterminated fence at end-of-input must still render as a code block;
    importantly we want the renderer to not crash and to produce a <pre>."""
    html = rendered["unterminated"]
    assert "<pre" in html and "</pre>" in html, html
