from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_no_inline_onclick_in_task_frontend_shell():
    app_js = read_text("src/server/static/nexus/js/app.js")
    task_board_js = read_text("src/server/static/nexus/js/components/task-board-panel.js")
    assert "onclick=" not in app_js
    assert "onclick=" not in task_board_js


def test_task_frontend_loads_shared_stream_and_form_controllers():
    index_html = read_text("src/server/static/nexus/index.html")
    streaming_controller = read_text("src/server/static/nexus/js/components/streaming-controller.js")
    task_form_controller = read_text("src/server/static/nexus/js/components/task-form-controller.js")

    assert "js/components/streaming-controller.js?v=32" in index_html
    assert "js/components/task-form-controller.js?v=32" in index_html
    assert "class NexusStreamingController" in streaming_controller
    assert "class NexusTaskFormController" in task_form_controller
    assert "window.NexusStreamingController = NexusStreamingController;" in streaming_controller
    assert "window.NexusTaskFormController = NexusTaskFormController;" in task_form_controller


def test_live_session_streams_delegate_to_shared_helper():
    app_js = read_text("src/server/static/nexus/js/app.js")

    assert "async _openLiveSessionStream(paneId, sessionId, options = {})" in app_js
    assert "await this._openLiveSessionStream(paneId, sessionId, {" in app_js
    assert "phase: 'task-stream'" in app_js
    assert "phase: 'channel-stream'" in app_js
    assert "NexusStreamingController.bindEventSource(stream, sessionAdapter);" in app_js


def test_chat_shell_uses_css_classes_for_session_visibility_states():
    app_js = read_text("src/server/static/nexus/js/app.js")
    styles_css = read_text("src/server/static/nexus/css/styles.css")

    assert 'style="display:none"' not in app_js
    assert ".is-hidden" in styles_css
    assert ".session-selection-actions.is-visible" in styles_css


def test_history_resume_api_wrappers_exist():
    api_js = read_text("src/server/static/nexus/js/api.js")
    assert "static async resumeHistorySession(" in api_js
    assert "static async bindHistorySession(" in api_js
    assert "continueHistorySession(provider, sessionId, options = {})" in api_js
    assert "return NexusAPI.resumeHistorySession(provider, sessionId, options);" in api_js


def test_settings_shell_uses_four_top_level_pages_and_single_page_sections():
    index_html = read_text("src/server/static/nexus/index.html")
    app_js = read_text("src/server/static/nexus/js/app.js")
    styles_css = read_text("src/server/static/nexus/css/styles.css")

    assert index_html.count('class="page-nav-btn') == 4
    assert 'data-page="chat"' in index_html
    assert 'data-page="task"' in index_html
    assert 'data-page="agents"' in index_html
    assert 'data-page="settings"' in index_html
    assert 'id="agentsView"' in index_html
    assert 'data-settings-nav="overview"' in index_html
    assert 'class="settings-short-nav' in index_html
    assert 'class="settings-short-nav-btn is-active"' in index_html
    assert 'data-settings-section="basic"' in index_html
    assert 'data-settings-section="extensions"' in index_html
    assert 'data-settings-section="safety"' in index_html
    assert 'data-settings-nav="basic"' in index_html
    assert 'data-settings-nav="extensions"' in index_html
    assert 'data-settings-nav="safety"' in index_html
    assert 'js/components/settings-basic-section.js?v=1' in index_html
    assert 'js/components/settings-extensions-section.js?v=1' in index_html
    assert 'js/components/settings-safety-section.js?v=1' in index_html
    assert 'js/components/settings-page.js?v=2' in index_html
    assert 'js/components/agents-store.js?v=2' in index_html
    assert 'js/components/agents-view-shell.js?v=2' in index_html
    assert ".settings-short-nav-btn.is-active" in styles_css
    assert "this.settingsPage = new SettingsPage(this);" in app_js
    assert "this.agentsPage = typeof AgentsViewShell === 'function' ? new AgentsViewShell(this) : new AgentsPage(this);" in app_js
    assert "this.settingsView = new SettingsView(this);" not in app_js


def test_settings_shell_no_longer_exposes_legacy_tab_or_category_markup():
    index_html = read_text("src/server/static/nexus/index.html")
    shell_managers_js = read_text("src/server/static/nexus/js/shell-managers.js")
    shell_views_js = read_text("src/server/static/nexus/js/shell-views.js")
    api_js = read_text("src/server/static/nexus/js/api.js")
    settings_page_js = read_text("src/server/static/nexus/js/components/settings-page.js")

    assert 'class="settings-categories"' not in index_html
    assert 'class="settings-tabs"' not in index_html
    assert 'data-settings-category=' not in index_html
    assert 'data-settings-tab=' not in index_html
    assert 'data-page="admin"' not in index_html
    assert 'data-page="dashboard"' not in index_html
    assert 'id="adminView"' not in index_html
    assert 'id="adminContent"' not in index_html
    assert "workflows: () => this.renderWorkflowsTab()" not in shell_views_js
    assert "workflows: 'workspace'" not in shell_views_js
    assert "async renderWorkflowsTab()" not in shell_views_js
    assert "static async getWorkflowTemplates()" not in api_js
    assert "static async runWorkflowTemplate(" not in api_js
    assert "getCurrentUrlSection()" in settings_page_js
    assert "classList.toggle('is-active', isActive)" in settings_page_js
    assert "syncSettingsSection(" in shell_managers_js
    assert "settingsSection" in shell_managers_js
    assert "if (normalized === 'dashboard') return 'agents';" in shell_managers_js
    assert "if (normalized === 'config' || normalized === 'admin') return 'settings';" in shell_managers_js
    assert "return ['chat', 'task', 'agents', 'settings'].includes(normalized) ? normalized : 'chat';" in shell_managers_js


def test_settings_panel_list_renderers_have_supporting_styles():
    shell_views_js = read_text("src/server/static/nexus/js/shell-views.js")
    styles_css = read_text("src/server/static/nexus/css/styles.css")

    assert "panel-list-item" in shell_views_js
    assert ".panel-list-item" in styles_css
    assert ".panel-list-item-body" in styles_css
    assert ".panel-badge" in styles_css
    assert ".panel-toggle" in styles_css
    assert ".panel-trust-score" in styles_css


def test_task_form_normalizes_relative_workspace_against_server_workdir():
    index_html = read_text("src/server/static/nexus/index.html")
    task_form_controller = read_text("src/server/static/nexus/js/components/task-form-controller.js")

    assert "相对路径会按当前服务工作目录解析" in index_html
    assert "_normalizeWorkspaceInput(workspace)" in task_form_controller
    assert "_getServerCurrentWorkdir()" in task_form_controller


def test_task_board_hides_empty_summary_strip_and_has_empty_state_shell():
    task_board_js = read_text("src/server/static/nexus/js/components/task-board-panel.js")
    task_summary_strip_js = read_text("src/server/static/nexus/js/components/task-summary-strip.js")
    styles_css = read_text("src/server/static/nexus/css/styles.css")

    assert 'id="summaryStrip-${pid}" class="task-summary-strip-container" hidden' in task_board_js
    assert "taskBoardEmptyState-" in task_board_js
    assert "_syncBoardVisibility" in task_board_js
    assert "data-surface=\"workflows\"" not in task_board_js
    assert "_canCancelTaskStatus(status)" in task_board_js
    assert "Only To Do or Doing tasks enter Cancelled." in task_board_js
    assert "container.hidden = !shouldShow;" in task_board_js
    assert "label: 'Cancelled'" in task_summary_strip_js
    assert ".task-board-empty-state" in styles_css
    assert ".task-summary-strip-container[hidden]" in styles_css


def test_streaming_renderer_uses_correct_block_identifier():
    streaming_renderer = read_text("src/server/static/nexus/js/components/streaming-renderer.js")
    assert "this._markWithheldInDOM(block_id, reason);" in streaming_renderer


def test_frontend_shell_avoids_inline_style_markup_and_style_mutations():
    frontend_root = ROOT / "src/server/static/nexus"
    targets = [
        frontend_root / "index.html",
        frontend_root / "js/app.js",
        frontend_root / "js/shell-managers.js",
        frontend_root / "js/components/agents-view-shell.js",
        frontend_root / "js/components/settings-basic-section.js",
        frontend_root / "js/components/settings-extensions-section.js",
        frontend_root / "js/components/settings-safety-section.js",
        frontend_root / "js/components/settings-page.js",
    ]

    offenders = []
    for path in targets:
        text = path.read_text(encoding="utf-8")
        if 'style="' in text or "style='" in text or '.style' in text or 'cssText' in text:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_nexus_frontend_has_no_duplicate_class_attributes_in_touched_shell_files():
    targets = [
        "src/server/static/nexus/index.html",
        "src/server/static/nexus/js/shell-views.js",
    ]

    offenders = []
    for relative_path in targets:
        text = read_text(relative_path)
        for match in re.finditer(r'<[^>]*\bclass="[^"]*"[^>]*\bclass="[^"]*"[^>]*>', text):
            offenders.append(f"{relative_path}:{text[:match.start()].count(chr(10)) + 1}")

    assert offenders == []


def test_frontend_security_cache_and_filter_regressions_are_guarded():
    app_js = read_text("src/server/static/nexus/js/app.js")
    store_js = read_text("src/server/static/nexus/js/app-data-store.js")
    shell_views_js = read_text("src/server/static/nexus/js/shell-views.js")
    task_board_js = read_text("src/server/static/nexus/js/components/task-board-panel.js")
    filters_js = read_text("src/server/static/nexus/js/components/filters.js")

    assert '${this.escapeHtml(session.status || \'idle\')}' in app_js
    assert '@${this.escapeHtml(session.username)}' in app_js
    assert "this._cacheKey(key, fetchOpts)" in store_js
    assert "this._pending.has(cacheKey)" in store_js
    assert "this._stableSerialize" in store_js
    assert "this._esc(JSON.stringify(r, null, 2))" in shell_views_js
    assert "this._esc(JSON.stringify(d, null, 2))" in shell_views_js
    assert "await NexusAPI.updateTask(taskId, { position: newPosition }" in task_board_js
    assert "parsed.protocol === 'https:' || parsed.protocol === 'http:'" in task_board_js
    assert "creator: { label: 'Creator'" not in filters_js
    assert "dueDate: { label: 'Due Date'" not in filters_js
    assert "key === 'creator' || key === 'dueDate'" in filters_js
