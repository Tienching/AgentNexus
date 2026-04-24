/**
 * ExpansionPanels component
 *
 * Bottom monitoring panels for runtime runs:
 * - Claude Code
 * - CodeBuddy
 * - Nexus
 */
class ExpansionPanels {
    static escapeHtml(str) {
        if (str === undefined || str === null) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }

    static classifySessions(sessions = []) {
        const buckets = {
            claude: [],
            codebuddy: [],
            nexus: [],
        };

        (sessions || []).forEach((session) => {
            const provider = String(session?.provider || '').toLowerCase();
            const alias = String(session?.alias || '').toLowerCase();
            const title = String(session?.title || '').toLowerCase();
            const text = `${provider} ${alias} ${title}`;

            if (text.includes('claude')) {
                buckets.claude.push(session);
                return;
            }
            if (text.includes('codebuddy')) {
                buckets.codebuddy.push(session);
                return;
            }
            if (text.includes('hermes') || text.includes('nexus')) {
                buckets.nexus.push(session);
            }
        });

        return buckets;
    }

    static renderPanel(title, key, sessions = []) {
        const rows = sessions.slice(0, 10).map((session) => {
            const sid = String(session?.id || '');
            const sessionTitle = String(session?.title || sid || '(untitled)');
            const status = String(session?.status || 'idle');
            const messageCount = Number(session?.message_count || 0);
            const statusTone = status === 'running' ? 'running' : (status === 'error' ? 'error' : 'idle');

            return `
                <div class="expansion-panel-row">
                    <div class="expansion-panel-session">
                        <span class="expansion-panel-session-title">${this.escapeHtml(sessionTitle)}</span>
                        <span class="expansion-panel-session-id">${this.escapeHtml(sid)}</span>
                    </div>
                    <div class="expansion-panel-session-meta">
                        <span class="expansion-panel-session-status expansion-panel-session-status--${statusTone}">${this.escapeHtml(status)}</span>
                        <span class="expansion-panel-session-count">msgs ${messageCount}</span>
                    </div>
                </div>
            `;
        }).join('');

        const empty = '<div class="expansion-panel-empty">No runs</div>';

        return `
            <details class="expansion-panel" data-expansion-key="${this.escapeHtml(key)}">
                <summary class="expansion-panel-summary">
                    <span>${this.escapeHtml(title)}</span>
                    <span class="expansion-panel-summary-count">${sessions.length}</span>
                </summary>
                <div class="expansion-panel-body">
                    ${rows || empty}
                </div>
            </details>
        `;
    }

    static render(container, sessions = []) {
        if (!container) return;
        const buckets = this.classifySessions(sessions);

        container.innerHTML = `
            <div class="expansion-panels-header">
                <div class="expansion-panels-title">Expansion Panels</div>
                <div class="expansion-panels-subtitle">Run Monitor</div>
            </div>
            <div class="expansion-panels-grid">
                ${this.renderPanel('Claude Code', 'claude', buckets.claude)}
                ${this.renderPanel('CodeBuddy', 'codebuddy', buckets.codebuddy)}
                ${this.renderPanel('Nexus', 'nexus', buckets.nexus)}
            </div>
        `;
    }
}

window.ExpansionPanels = ExpansionPanels;
