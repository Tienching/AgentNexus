/**
 * SecurityAuditPanel - Security audit log and scan results.
 */

class SecurityAuditPanel extends BasePanel {
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
            ? this._entries.filter(e => (e.action || '').toLowerCase().includes(this._filter.toLowerCase()))
            : this._entries;
        const highRisk = entries.filter(e => e.level === 'error' || e.severity === 'high').length;

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                <input type="text" class="panel-input panel-search" placeholder="Filter audit log…" value="${this._escapeHtml(this._filter)}">
            `})}
            <div class="panel-body">
                <div class="panel-stats">
                    <span class="stat-item"><span class="stat-value">${entries.length}</span> Entries</span>
                    <span class="stat-item stat-error"><span class="stat-value">${highRisk}</span> High Risk</span>
                </div>
                <div class="panel-list">
                    ${entries.length === 0 ? '<div class="panel-empty">No audit entries</div>' :
                      entries.map(e => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._escapeHtml(e.action || e.event_type || 'Audit Event')}</div>
                                <div class="panel-list-item-sub">${e.timestamp ? new Date(e.timestamp).toLocaleString() : ''} ${e.username ? '&middot; ' + this._escapeHtml(e.username) : ''}</div>
                            </div>
                            <span class="panel-badge ${e.level === 'error' || e.severity === 'high' ? 'badge-error' : e.level === 'warning' ? 'badge-warn' : 'badge-ok'}">${e.level || e.severity || 'info'}</span>
                        </div>
                    `).join('')}
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
}

export { SecurityAuditPanel };
