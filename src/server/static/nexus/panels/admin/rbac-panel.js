/**
 * RBACPanel - Role-Based Access Control management.
 */

class RBACPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._roles = [];
        this._selectedRole = null;
    }

    async refresh() {
        try {
            const data = await this.api.getSecurityScan();
            this._roles = data.rbac || data.roles || [
                { name: 'admin', permissions: ['*'], users: [] },
                { name: 'operator', permissions: ['task:read', 'task:write', 'agent:read'], users: [] },
                { name: 'viewer', permissions: ['task:read', 'agent:read'], users: [] },
            ];
            this.render(this.container);
        } catch (e) {
            this._roles = [];
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;
        const selected = this._roles.find(r => r.name === this._selectedRole);

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                <button class="panel-btn" data-action="add-role">+ Add Role</button>
            `})}
            <div class="panel-body panel-split">
                <div class="panel-split-left">
                    <div class="panel-list">
                        ${this._roles.map(r => `
                            <div class="panel-list-item ${r.name === this._selectedRole ? 'active' : ''}" data-role="${this._escapeHtml(r.name)}">
                                <div class="panel-list-item-title">${this._escapeHtml(r.name)}</div>
                                <div class="panel-list-item-sub">${(r.permissions || []).length} permissions</div>
                            </div>
                        `).join('')}
                    </div>
                </div>
                <div class="panel-split-right">
                    ${selected ? `
                        <div class="panel-detail">
                            <h4>Role: ${this._escapeHtml(selected.name)}</h4>
                            <div class="panel-field">
                                <label>Permissions</label>
                                <div class="panel-tag-list">
                                    ${(selected.permissions || []).map(p => `
                                        <span class="panel-tag">${this._escapeHtml(p)}</span>
                                    `).join('')}
                                </div>
                            </div>
                            <div class="panel-field">
                                <label>Assigned Users</label>
                                <div class="panel-list-plain">
                                    ${(selected.users || []).length === 0 ? '<span class="panel-empty">No users assigned</span>' :
                                      (selected.users || []).map(u => `<div>${this._escapeHtml(u)}</div>`).join('')}
                                </div>
                            </div>
                        </div>
                    ` : '<div class="panel-empty">Select a role to view details</div>'}
                </div>
            </div>
        `;

        this._bindRefreshBtn();
        container.querySelectorAll('.panel-list-item[data-role]').forEach(el => {
            el.addEventListener('click', () => {
                this._selectedRole = el.dataset.role;
                this.render(container);
            });
        });
    }
}

export { RBACPanel };
