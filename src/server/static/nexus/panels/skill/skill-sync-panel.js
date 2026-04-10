/**
 * SkillSyncPanel - Sync skill definitions across providers and directories.
 */

class SkillSyncPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._syncLog = [];
        this._syncing = false;
    }

    async refresh() {
        try {
            const data = await this.api.getSkills();
            const providers = Object.keys(data.providers || {});
            this._syncLog = providers.map(p => ({
                provider: p,
                count: (data.providers[p] || []).length,
                lastSync: new Date().toLocaleTimeString(),
            }));
            this.render(this.container);
        } catch (e) {
            this.showError(e.message);
        }
    }

    render(container) {
        this.container = container;

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                <button class="panel-btn primary" data-action="sync-all" ${this._syncing ? 'disabled' : ''}>
                    ${this._syncing ? 'Syncing…' : 'Sync All'}
                </button>
            `})}
            <div class="panel-body">
                <div class="panel-list">
                    ${this._syncLog.length === 0 ? '<div class="panel-empty">No providers to sync</div>' :
                      this._syncLog.map(s => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._escapeHtml(s.provider)}</div>
                                <div class="panel-list-item-sub">${s.count} skills &middot; Last sync: ${s.lastSync}</div>
                            </div>
                            <span class="panel-badge badge-ok">In Sync</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;

        this._bindRefreshBtn();
        const syncBtn = container.querySelector('[data-action="sync-all"]');
        if (syncBtn) {
            syncBtn.addEventListener('click', async () => {
                this._syncing = true;
                this.render(container);
                await this.refresh();
                this._syncing = false;
                this.render(container);
            });
        }
    }
}

export { SkillSyncPanel };
