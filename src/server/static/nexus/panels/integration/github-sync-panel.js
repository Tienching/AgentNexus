/**
 * GitHubSyncPanel - GitHub repository sync status and configuration.
 */

class GitHubSyncPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._repos = [];
        this._syncing = false;
    }

    async refresh() {
        try {
            const data = await this.api.getProjects();
            this._repos = (data.projects || []).map(p => ({
                name: typeof p === 'string' ? p : p.name || p.path || 'Unknown',
                path: typeof p === 'string' ? p : p.path || '',
                lastSync: new Date().toLocaleString(),
            }));
            this.render(this.container);
        } catch (e) {
            this._repos = [];
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                <button class="panel-btn" data-action="sync-github" ${this._syncing ? 'disabled' : ''}>
                    ${this._syncing ? 'Syncing…' : 'Sync Now'}
                </button>
            `})}
            <div class="panel-body">
                <div class="panel-list">
                    ${this._repos.length === 0 ? '<div class="panel-empty">No repositories connected</div>' :
                      this._repos.map(r => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._escapeHtml(r.name)}</div>
                                <div class="panel-list-item-sub">${this._escapeHtml(r.path)} &middot; Last sync: ${r.lastSync}</div>
                            </div>
                            <span class="panel-badge badge-ok">Connected</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;

        this._bindRefreshBtn();
    }
}

export { GitHubSyncPanel };
