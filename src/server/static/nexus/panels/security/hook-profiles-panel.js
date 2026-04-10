/**
 * HookProfilesPanel - Configure and inspect hook profiles for security enforcement.
 */

class HookProfilesPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._profiles = [];
    }

    async refresh() {
        try {
            const data = await this.api.getSecurityScan();
            this._profiles = data.hook_profiles || data.hooks || [];
            this.render(this.container);
        } catch (e) {
            this._profiles = [];
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                <button class="panel-btn" data-action="add-hook">+ Add Hook</button>
            `})}
            <div class="panel-body">
                <div class="panel-list">
                    ${this._profiles.length === 0 ? '<div class="panel-empty">No hook profiles configured</div>' :
                      this._profiles.map(h => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._escapeHtml(h.name || h.id || 'Hook')}</div>
                                <div class="panel-list-item-sub">${this._escapeHtml(h.type || h.event || '')} &middot; ${this._escapeHtml(h.action || 'log')}</div>
                            </div>
                            <span class="panel-badge ${h.enabled !== false ? 'badge-ok' : 'badge-muted'}">${h.enabled !== false ? 'Active' : 'Disabled'}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
        this._bindRefreshBtn();
    }
}

export { HookProfilesPanel };
