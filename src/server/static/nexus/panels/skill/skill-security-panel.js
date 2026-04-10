/**
 * SkillSecurityPanel - Review and approve/reject skill security permissions.
 */

class SkillSecurityPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._pending = [];
        this._approved = [];
    }

    async refresh() {
        try {
            const data = await this.api.getSecurityScan();
            this._pending = (data.skills?.pending || []).map(s => ({ ...s, _status: 'pending' }));
            this._approved = (data.skills?.approved || []).map(s => ({ ...s, _status: 'approved' }));
            this.render(this.container);
        } catch (e) {
            this._pending = [];
            this._approved = [];
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;
        const all = [...this._pending, ...this._approved];

        container.innerHTML = `
            ${this._headerHtml()}
            <div class="panel-body">
                <div class="panel-stats">
                    <span class="stat-item stat-warn"><span class="stat-value">${this._pending.length}</span> Pending</span>
                    <span class="stat-item stat-ok"><span class="stat-value">${this._approved.length}</span> Approved</span>
                </div>
                <div class="panel-list">
                    ${all.length === 0 ? '<div class="panel-empty">No skill security entries</div>' :
                      all.map(s => `
                        <div class="panel-list-item" data-skill-name="${this._escapeHtml(s.name || s.skill_name)}">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._escapeHtml(s.name || s.skill_name)}</div>
                                <div class="panel-list-item-sub">${this._escapeHtml(s.provider || '')} &middot; ${this._escapeHtml(s.risk_level || 'unknown risk')}</div>
                            </div>
                            <span class="panel-badge ${s._status === 'approved' ? 'badge-ok' : 'badge-warn'}">${s._status}</span>
                            ${s._status === 'pending' ? `
                                <button class="panel-btn" data-action="approve" data-skill="${this._escapeHtml(s.name || s.skill_name)}">Approve</button>
                            ` : ''}
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
        this._bindRefreshBtn();
    }
}

export { SkillSecurityPanel };
