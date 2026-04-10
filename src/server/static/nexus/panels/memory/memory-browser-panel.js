/**
 * MemoryBrowserPanel - Browse agent memory entries with search and filtering.
 */

class MemoryBrowserPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._entries = [];
        this._search = '';
    }

    async refresh() {
        try {
            const data = await this.api.getAgents();
            // Use agent data as a proxy for memory entries
            this._entries = (data.agents || []).map(a => ({
                id: a.id,
                agent: a.display_name || a.id,
                memory_count: a.memory_count || 0,
                last_updated: a.last_active || new Date().toISOString(),
            }));
            this.render(this.container);
        } catch (e) {
            this._entries = [];
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;
        const entries = this._search
            ? this._entries.filter(e => e.agent.toLowerCase().includes(this._search.toLowerCase()))
            : this._entries;

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                <input type="text" class="panel-input panel-search" placeholder="Search memory…" value="${this._escapeHtml(this._search)}">
            `})}
            <div class="panel-body">
                <div class="panel-list">
                    ${entries.length === 0 ? '<div class="panel-empty">No memory entries found</div>' :
                      entries.map(e => `
                        <div class="panel-list-item" data-memory-id="${this._escapeHtml(e.id)}">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._escapeHtml(e.agent)}</div>
                                <div class="panel-list-item-sub">${e.memory_count} entries &middot; Updated ${new Date(e.last_updated).toLocaleString()}</div>
                            </div>
                            <button class="panel-btn btn-sm" data-action="browse" data-id="${this._escapeHtml(e.id)}">Browse</button>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;

        this._bindRefreshBtn();
        const searchInput = container.querySelector('.panel-search');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this._search = e.target.value;
                this.render(container);
            });
        }
    }
}

export { MemoryBrowserPanel };
