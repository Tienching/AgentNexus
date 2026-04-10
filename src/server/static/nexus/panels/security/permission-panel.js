/**
 * PermissionPanel - View and manage agent/user permissions.
 */

class PermissionPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._permissions = [];
    }

    async refresh() {
        try {
            const data = await this.api.getSecurityScan();
            this._permissions = data.permissions || data.acl || [];
            this.render(this.container);
        } catch (e) {
            this._permissions = [];
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;

        container.innerHTML = `
            ${this._headerHtml()}
            <div class="panel-body">
                <div class="panel-list">
                    ${this._permissions.length === 0 ? `
                        <div class="panel-empty">No permission entries</div>
                        <div class="panel-placeholder-hint">Permissions are auto-generated from RBAC configuration</div>
                    ` :
                      this._permissions.map(p => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._escapeHtml(p.subject || p.role || 'Role')}</div>
                                <div class="panel-list-item-sub">${this._escapeHtml(p.resource || p.scope || '')}: ${this._escapeHtml(p.action || p.permission || 'read')}</div>
                            </div>
                            <span class="panel-badge ${p.granted !== false ? 'badge-ok' : 'badge-error'}">${p.granted !== false ? 'Granted' : 'Denied'}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
        this._bindRefreshBtn();
    }
}

export { PermissionPanel };
