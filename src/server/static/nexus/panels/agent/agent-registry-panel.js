/**
 * AgentRegistryPanel - Displays all registered agents with status, type, and details.
 */

class AgentRegistryPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._agents = [];
        this._filter = '';
    }

    async init() {
        await super.init();
    }

    async refresh() {
        try {
            const data = await this.api.getAgents();
            this._agents = data.agents || [];
            this.render(this.container);
        } catch (e) {
            this.showError(e.message);
        }
    }

    render(container) {
        this.container = container;
        const agents = this._filter
            ? this._agents.filter(a => (a.display_name || a.id || '').toLowerCase().includes(this._filter.toLowerCase()))
            : this._agents;

        const online = agents.filter(a => a.available).length;
        const offline = agents.length - online;

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                <input type="text" class="panel-input panel-search" placeholder="Filter agents…" value="${this._escapeHtml(this._filter)}" data-panel-id="${this.id}">
            `})}
            <div class="panel-body">
                <div class="panel-stats">
                    <span class="stat-item"><span class="stat-value">${agents.length}</span> Total</span>
                    <span class="stat-item stat-ok"><span class="stat-value">${online}</span> Online</span>
                    <span class="stat-item stat-muted"><span class="stat-value">${offline}</span> Offline</span>
                </div>
                <div class="panel-list">
                    ${agents.length === 0 ? '<div class="panel-empty">No agents found</div>' :
                      agents.map(a => `
                        <div class="panel-list-item" data-agent-id="${this._escapeHtml(a.id)}">
                            <div class="panel-list-item-icon ${a.available ? 'status-online' : 'status-offline'}">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="16" height="16">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                          d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
                                </svg>
                            </div>
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._escapeHtml(a.display_name || a.id)}</div>
                                <div class="panel-list-item-sub">${this._escapeHtml(a.agent_type || '')} &middot; ${this._escapeHtml(a.username || '')}</div>
                            </div>
                            <span class="panel-badge ${a.available ? 'badge-ok' : 'badge-muted'}">${a.available ? 'Online' : 'Offline'}</span>
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

    onRealtimeEvent(eventType, payload) {
        if (eventType === 'agent.registered' || eventType === 'agent.offline') {
            this.refresh();
        }
    }
}

export { AgentRegistryPanel };
