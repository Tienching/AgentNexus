/**
 * AgentMessagingPanel - Inter-agent messaging view with conversation threads.
 */

class AgentMessagingPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._messages = [];
        this._composing = false;
    }

    async refresh() {
        try {
            // Attempt to load recent broadcast messages
            const data = await this.api.getAuditLog({ action: 'message', limit: 50 });
            this._messages = data.entries || data.logs || [];
            this.render(this.container);
        } catch (e) {
            // If the endpoint doesn't exist yet, show empty state
            this._messages = [];
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                <button class="panel-btn" data-action="compose" title="New Message">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="14" height="14">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                    </svg>
                </button>
            `})}
            <div class="panel-body">
                ${this._messages.length === 0 ? `
                    <div class="panel-empty">No messages yet</div>
                ` : `
                    <div class="panel-message-list">
                        ${this._messages.map(m => `
                            <div class="panel-message">
                                <div class="panel-message-header">
                                    <span class="panel-message-from">${this._escapeHtml(m.from || m.agent_id || 'System')}</span>
                                    <span class="panel-message-time">${m.timestamp ? new Date(m.timestamp).toLocaleTimeString() : ''}</span>
                                </div>
                                <div class="panel-message-body">${this._escapeHtml(m.content || m.message || m.action || '')}</div>
                            </div>
                        `).join('')}
                    </div>
                `}
            </div>
        `;

        this._bindRefreshBtn();
    }

    onRealtimeEvent(eventType, payload) {
        if (eventType === 'agent.message' || eventType === 'activity.log') {
            this._messages.unshift(payload);
            if (this._messages.length > 100) this._messages.length = 100;
            if (this.container) this.render(this.container);
        }
    }
}

export { AgentMessagingPanel };
