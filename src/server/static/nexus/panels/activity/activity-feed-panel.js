/**
 * ActivityFeedPanel - Real-time activity feed with filtering.
 */

class ActivityFeedPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._entries = [];
        this._filter = '';
    }

    async refresh() {
        try {
            const data = await this.api.getAuditLog({ limit: 50 });
            this._entries = data.entries || data.logs || [];
            this.render(this.container);
        } catch (e) {
            this._entries = [];
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;
        const entries = this._filter
            ? this._entries.filter(e => (e.action || e.event_type || '').toLowerCase().includes(this._filter.toLowerCase()))
            : this._entries;

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                <input type="text" class="panel-input panel-search" placeholder="Filter activity…" value="${this._escapeHtml(this._filter)}">
            `})}
            <div class="panel-body">
                <div class="panel-feed">
                    ${entries.length === 0 ? '<div class="panel-empty">No activity recorded</div>' :
                      entries.map(e => {
                        const time = e.timestamp ? new Date(e.timestamp).toLocaleString() : '';
                        const icon = e.action?.includes('task') ? 'task' :
                                    e.action?.includes('agent') ? 'agent' :
                                    e.action?.includes('skill') ? 'skill' : 'activity';
                        return `
                        <div class="feed-item">
                            <div class="feed-icon feed-icon-${icon}">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="14" height="14">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
                                </svg>
                            </div>
                            <div class="feed-body">
                                <div class="feed-title">${this._escapeHtml(e.action || e.event_type || 'Activity')}</div>
                                <div class="feed-meta">${time} ${e.username ? '&middot; ' + this._escapeHtml(e.username) : ''}</div>
                            </div>
                        </div>`;
                    }).join('')}
                </div>
            </div>
        `;

        this._bindRefreshBtn();
        const searchInput = container.querySelector('.panel-search');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this._filter = e.target.value;
                this.render(container);
            });
        }
    }

    onRealtimeEvent(eventType, payload) {
        this._entries.unshift({ ...payload, action: eventType, timestamp: Date.now() });
        if (this._entries.length > 200) this._entries.length = 200;
        if (this.container) this.render(this.container);
    }
}

export { ActivityFeedPanel };
