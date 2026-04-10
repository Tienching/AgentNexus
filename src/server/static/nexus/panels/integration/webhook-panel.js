/**
 * WebhookPanel - Configure and manage outgoing/incoming webhooks.
 */

class WebhookPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._webhooks = [];
    }

    async refresh() {
        try {
            const data = await this.api.getAuditLog({ action: 'webhook', limit: 30 });
            this._webhooks = data.entries || [];
            this.render(this.container);
        } catch (e) {
            this._webhooks = [];
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                <button class="panel-btn primary" data-action="add-webhook">+ Add Webhook</button>
            `})}
            <div class="panel-body">
                <div class="panel-list">
                    ${this._webhooks.length === 0 ? '<div class="panel-empty">No webhooks configured</div>' :
                      this._webhooks.map(w => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._escapeHtml(w.name || w.url || 'Webhook')}</div>
                                <div class="panel-list-item-sub">${this._escapeHtml(w.url || w.detail || '')} &middot; ${this._escapeHtml(w.events || 'all events')}</div>
                            </div>
                            <span class="panel-badge ${w.active !== false ? 'badge-ok' : 'badge-muted'}">${w.active !== false ? 'Active' : 'Inactive'}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
        this._bindRefreshBtn();
    }
}

export { WebhookPanel };
