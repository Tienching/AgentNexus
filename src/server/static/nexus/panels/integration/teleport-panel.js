/**
 * TeleportPanel - Teleport/proxy connection management for remote agent access.
 */

class TeleportPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._connections = [];
    }

    async refresh() {
        try {
            const data = await this.api.getDiagnostics();
            this._connections = data.teleport_connections || data.connections || [];
            this.render(this.container);
        } catch (e) {
            this._connections = [];
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;
        const active = this._connections.filter(c => c.status === 'connected' || c.active).length;

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                <button class="panel-btn primary" data-action="add-connection">+ Add Connection</button>
            `})}
            <div class="panel-body">
                <div class="panel-stats">
                    <span class="stat-item stat-ok"><span class="stat-value">${active}</span> Active</span>
                    <span class="stat-item"><span class="stat-value">${this._connections.length}</span> Total</span>
                </div>
                <div class="panel-list">
                    ${this._connections.length === 0 ? '<div class="panel-empty">No teleport connections</div>' :
                      this._connections.map(c => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._escapeHtml(c.name || c.host || 'Connection')}</div>
                                <div class="panel-list-item-sub">${this._escapeHtml(c.host || '')} ${c.port ? ':' + c.port : ''} &middot; Latency: ${c.latency_ms ?? '—'}ms</div>
                            </div>
                            <span class="panel-badge ${c.status === 'connected' || c.active ? 'badge-ok' : 'badge-muted'}">${c.status || (c.active ? 'Active' : 'Inactive')}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
        this._bindRefreshBtn();
    }
}

export { TeleportPanel };
