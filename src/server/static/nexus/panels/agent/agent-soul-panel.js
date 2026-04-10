/**
 * AgentSoulPanel - Configure and inspect agent personality/identity (soul) profiles.
 */

class AgentSoulPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._souls = [];
        this._selected = null;
    }

    async refresh() {
        try {
            const data = await this.api.getAgents();
            this._souls = (data.agents || []).map(a => ({
                id: a.id,
                name: a.display_name || a.id,
                type: a.agent_type,
                soul: a.soul || a.identity || null,
            }));
            this.render(this.container);
        } catch (e) {
            this.showError(e.message);
        }
    }

    render(container) {
        this.container = container;
        const selected = this._souls.find(s => s.id === this._selected);

        container.innerHTML = `
            ${this._headerHtml()}
            <div class="panel-body panel-split">
                <div class="panel-split-left">
                    <div class="panel-list">
                        ${this._souls.map(s => `
                            <div class="panel-list-item ${s.id === this._selected ? 'active' : ''}" data-agent-id="${this._escapeHtml(s.id)}">
                                <div class="panel-list-item-title">${this._escapeHtml(s.name)}</div>
                                <div class="panel-list-item-sub">${this._escapeHtml(s.type)}</div>
                            </div>
                        `).join('')}
                    </div>
                </div>
                <div class="panel-split-right">
                    ${selected ? `
                        <div class="panel-detail">
                            <h4>${this._escapeHtml(selected.name)} — Soul Profile</h4>
                            ${selected.soul ? `
                                <div class="panel-field">
                                    <label>Identity</label>
                                    <pre class="panel-code">${this._escapeHtml(typeof selected.soul === 'string' ? selected.soul : JSON.stringify(selected.soul, null, 2))}</pre>
                                </div>
                            ` : `
                                <div class="panel-empty">No soul profile configured for this agent</div>
                                <button class="panel-btn primary" data-action="create-soul" data-agent-id="${this._escapeHtml(selected.id)}">Create Soul Profile</button>
                            `}
                        </div>
                    ` : '<div class="panel-empty">Select an agent to view its soul profile</div>'}
                </div>
            </div>
        `;

        this._bindRefreshBtn();
        container.querySelectorAll('.panel-list-item[data-agent-id]').forEach(el => {
            el.addEventListener('click', () => {
                this._selected = el.dataset.agentId;
                this.render(container);
            });
        });
    }
}

export { AgentSoulPanel };
