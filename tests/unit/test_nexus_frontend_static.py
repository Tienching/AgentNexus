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

    assert "js/components/streaming-controller.js?v=35" in index_html
    assert "js/components/task-form-controller.js?v=33" in index_html
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


def test_snapshot_render_preserves_orphaned_stream_tool_calls():
    app_js = read_text("src/server/static/nexus/js/app.js")
    streaming_controller = read_text("src/server/static/nexus/js/components/streaming-controller.js")

    assert "getRenderedToolCallIds(messages, toolCalls)" in app_js
    assert "renderStandaloneToolCallMessages(standaloneToolCalls)" in app_js
    assert "Recovered stream activity" not in app_js
    assert "_finalizeOpenToolCalls('completed')" in streaming_controller
    assert "tools:${toolCalls.length}" in app_js


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


def test_settings_shell_uses_three_top_level_pages_and_single_page_sections():
    index_html = read_text("src/server/static/nexus/index.html")
    app_js = read_text("src/server/static/nexus/js/app.js")
    styles_css = read_text("src/server/static/nexus/css/styles.css")

    assert index_html.count('class="page-nav-btn') == 3
    assert 'data-page="chat"' in index_html
    assert 'data-page="task"' in index_html
    assert 'data-page="settings"' in index_html
    assert 'data-settings-nav="provider"' in index_html
    assert 'data-settings-nav="skills"' in index_html
    assert 'data-settings-nav="runtime"' in index_html
    assert 'class="settings-short-nav' in index_html
    assert 'class="settings-short-nav-btn is-active"' in index_html
    assert 'data-settings-section="basic"' in index_html
    assert 'data-settings-section="skills"' in index_html
    assert 'data-settings-section="safety"' in index_html
    assert 'js/components/settings-basic-section.js?v=2' in index_html
    assert 'js/components/settings-extensions-section.js?v=2' in index_html
    assert 'js/components/settings-safety-section.js?v=1' in index_html
    assert 'js/components/settings-page.js?v=4' in index_html
    assert 'data-settings-subnav="extensions-global"' not in index_html
    assert 'data-settings-subnav="extensions-provider"' not in index_html
    assert 'Global MCP' not in index_html
    assert 'Provider MCP' not in index_html
    assert ".settings-short-nav-btn.is-active" in styles_css
    assert "this.settingsPage = new SettingsPage(this);" in app_js
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
    assert "static async listAgentTemplates(options = {})" in api_js
    assert "static async updateAgentTemplate(name, payload = {})" in api_js
    assert "getCurrentUrlSection()" in settings_page_js
    assert "classList.toggle('is-active', isActive)" in settings_page_js
    assert "syncSettingsSection(" in shell_managers_js
    assert "settingsSection" in shell_managers_js
    assert "if (normalized === 'dashboard') return 'settings';" in shell_managers_js
    assert "if (normalized === 'config' || normalized === 'admin') return 'settings';" in shell_managers_js
    assert "if (normalized === 'extensions') return 'skills';" in shell_managers_js
    assert "return ['provider', 'skills', 'runtime'].includes(normalized) ? normalized : 'provider';" in shell_managers_js
    assert "return ['chat', 'task', 'settings'].includes(normalized) ? normalized : 'chat';" in shell_managers_js


def test_settings_panel_list_renderers_have_supporting_styles():
    shell_views_js = read_text("src/server/static/nexus/js/shell-views.js")
    styles_css = read_text("src/server/static/nexus/css/styles.css")

    # AdminView/SettingsView panel renderers were removed during simplification;
    # the retained shell-views.js only exposes ConfigView and GlobalSearch.
    assert "class ConfigView" in shell_views_js
    assert "class GlobalSearch" in shell_views_js
    assert ".panel-list-item" in styles_css


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
    assert "key: 'cancelled', label: statusLabels.cancelled" in task_summary_strip_js
    assert ".task-board-empty-state" in styles_css
    assert ".task-summary-strip-container[hidden]" in styles_css


def test_task_summary_strip_uses_board_lane_labels_and_metrics():
    task_view_model_js = read_text("src/server/static/nexus/js/components/task-view-model.js")
    task_summary_strip_js = read_text("src/server/static/nexus/js/components/task-summary-strip.js")
    task_board_js = read_text("src/server/static/nexus/js/components/task-board-panel.js")
    styles_css = read_text("src/server/static/nexus/css/styles.css")

    assert "const statusLabels = TaskSummaryStrip._statusLabels();" in task_summary_strip_js
    for key in ["pending", "running", "in_review", "completed", "failed", "cancelled"]:
        assert f"key: '{key}', label: statusLabels.{key}" in task_summary_strip_js
        assert f"{key}: tasks.filter(t => t.lane_status === '{key}').length" in task_view_model_js
        assert f"{key}: ['{key}']" in task_board_js
        css_key = key.replace("_", "-")
        assert f".summary-dot-{css_key}" in styles_css

    assert "key: 'active', label: 'Active'" not in task_summary_strip_js
    assert "key: 'reviewing', label: 'Reviewing'" not in task_summary_strip_js


def test_streaming_renderer_uses_correct_block_identifier():
    streaming_renderer = read_text("src/server/static/nexus/js/components/streaming-renderer.js")
    assert "this._markWithheldInDOM(block_id, reason);" in streaming_renderer


def test_frontend_shell_avoids_inline_style_markup_and_style_mutations():
    frontend_root = ROOT / "src/server/static/nexus"
    targets = [
        frontend_root / "index.html",
        frontend_root / "js/app.js",
        frontend_root / "js/shell-managers.js",
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
    assert "await NexusAPI.updateTask(taskId, { position: newPosition }" in task_board_js
    assert "parsed.protocol === 'https:' || parsed.protocol === 'http:'" in task_board_js
    assert "creator: { label: 'Creator'" not in filters_js
    assert "dueDate: { label: 'Due Date'" not in filters_js
    assert "key === 'creator' || key === 'dueDate'" in filters_js


def test_runtime_session_sidebar_uses_created_time_instead_of_last_activity():
    app_js = read_text("src/server/static/nexus/js/app.js")

    assert "getSessionListTimestamp(session, isHistory = false)" in app_js
    assert "return isHistory ? (session.updated_at || session.created_at) : (session.created_at || session.updated_at);" in app_js
    assert "const timeStr = this.formatTime(this.getSessionListTimestamp(session, isHistory));" in app_js


def test_consecutive_assistant_messages_render_as_a_single_avatar_group():
    app_js = read_text("src/server/static/nexus/js/app.js")
    styles_css = read_text("src/server/static/nexus/css/styles.css")

    assert "buildRenderableMessageGroups(messages)" in app_js
    assert "renderMessageGroup(group, toolCalls)" in app_js
    assert "messageGroups.map(group => this.renderMessageGroup(group, toolCalls)).join('')" in app_js
    assert "group.role === 'assistant'" in app_js
    assert ".message-group-stack" in styles_css
    assert ".message-group-entry" in styles_css
