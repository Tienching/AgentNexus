/**
 * ClaudeCodePanel - Claude Code integration status and session management.
 */

class ClaudeCodePanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._sessions = [];
    }

    async refresh() {
        try {
            const data = await this.api.getAgentRuntimes('claude');
            const runtime = data.runtimes?.claude || data.runtime || {};
            this._sessions = runtime.sessions || runtime.processes || [];
            this._runtimeInfo = runtime;
            this.render(this.container);
        } catch (e) {
            this._sessions = [];
            this._runtimeInfo = null;
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;
        const info = this._runtimeInfo;

        container.innerHTML = `
            ${this._headerHtml()}
            <div class="panel-body">
                ${info ? `
                    <div class="panel-detail-section">
                        <h4>Runtime Status</h4>
                        <div class="panel-field">
                            <label>Version</label>
                            <span>${this._escapeHtml(info.version || 'Unknown')}</span>
                        </div>
                        <div class="panel-field">
                            <label>Path</label>
                            <code class="panel-code">${this._escapeHtml(info.path || 'Not found')}</code>
                        </div>
                        <div class="panel-field">
                            <label>Status</label>
                            <span class="panel-badge ${info.available ? 'badge-ok' : 'badge-error'}">${info.available ? 'Available' : 'Not Found'}</span>
                        </div>
                    </div>
                ` : '<div class="panel-empty">No Claude Code runtime detected</div>'}
                <div class="panel-detail-section">
                    <h4>Active Sessions</h4>
                    <div class="panel-list">
                        ${this._sessions.length === 0 ? '<div class="panel-empty">No active sessions</div>' :
                          this._sessions.map(s => `
                            <div class="panel-list-item">
                                <div class="panel-list-item-body">
                                    <div class="panel-list-item-title">${this._escapeHtml(s.id || s.session_id || 'Session')}</div>
                                    <div class="panel-list-item-sub">${this._escapeHtml(s.project || s.cwd || '')}</div>
                                </div>
                                <span class="panel-badge badge-ok">Running</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>
        `;
        this._bindRefreshBtn();
    }
}

export { ClaudeCodePanel };
