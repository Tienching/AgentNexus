/**
 * ExpansionPanels component
 *
 * Bottom monitoring panels for runtime sessions:
 * - Claude Code
 * - CodeBuddy
 * - Hermes
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
            hermes: [],
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
            if (text.includes('hermes') || text.includes('nanobot')) {
                buckets.hermes.push(session);
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
            const statusColor = status === 'running' ? 'var(--success)' : (status === 'error' ? 'var(--error)' : 'var(--text-muted)');

            return `
                <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;padding:6px 8px;border:1px solid var(--border);border-radius:6px;background:var(--bg-secondary);">
                    <div style="min-width:0;display:flex;flex-direction:column;gap:2px;">
                        <span style="font-size:12px;color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${this.escapeHtml(sessionTitle)}</span>
                        <span style="font-size:10px;color:var(--text-muted);font-family:var(--font-mono);">${this.escapeHtml(sid)}</span>
                    </div>
                    <div style="display:flex;flex-direction:column;align-items:flex-end;gap:2px;flex-shrink:0;">
                        <span style="font-size:10px;color:${statusColor};">${this.escapeHtml(status)}</span>
                        <span style="font-size:10px;color:var(--text-muted);">msgs ${messageCount}</span>
                    </div>
                </div>
            `;
        }).join('');

        const empty = '<div style="font-size:11px;color:var(--text-muted);padding:4px 2px;">No sessions</div>';

        return `
            <details class="expansion-panel" data-expansion-key="${this.escapeHtml(key)}" style="border:1px solid var(--border);border-radius:8px;background:var(--bg-primary);">
                <summary style="cursor:pointer;list-style:none;padding:10px 12px;display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--text-primary);">
                    <span>${this.escapeHtml(title)}</span>
                    <span style="font-size:11px;color:var(--text-muted);">${sessions.length}</span>
                </summary>
                <div style="display:flex;flex-direction:column;gap:6px;padding:0 10px 10px;">
                    ${rows || empty}
                </div>
            </details>
        `;
    }

    static render(container, sessions = []) {
        if (!container) return;
        const buckets = this.classifySessions(sessions);

        container.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
                <div style="font-size:12px;color:var(--text-secondary);font-weight:600;">Expansion Panels</div>
                <div style="font-size:11px;color:var(--text-muted);">Session Monitor</div>
            </div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;">
                ${this.renderPanel('Claude Code', 'claude', buckets.claude)}
                ${this.renderPanel('CodeBuddy', 'codebuddy', buckets.codebuddy)}
                ${this.renderPanel('Hermes', 'hermes', buckets.hermes)}
            </div>
        `;
    }
}

window.ExpansionPanels = ExpansionPanels;
