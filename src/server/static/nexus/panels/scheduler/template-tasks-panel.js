/**
 * TemplateTasksPanel - Browse and use predefined task templates.
 */

class TemplateTasksPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._templates = [];
        this._filter = '';
    }

    async refresh() {
        try {
            const data = await this.api.getTasks({ pageSize: 20 });
            // Use completed tasks as template suggestions
            const done = (data.tasks || []).filter(t => t.status === 'done');
            this._templates = done.slice(0, 20);
            this.render(this.container);
        } catch (e) {
            this._templates = [];
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;
        const filtered = this._filter
            ? this._templates.filter(t => (t.title || '').toLowerCase().includes(this._filter.toLowerCase()))
            : this._templates;

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                <input type="text" class="panel-input panel-search" placeholder="Search templates…" value="${this._escapeHtml(this._filter)}">
            `})}
            <div class="panel-body">
                <div class="panel-grid">
                    ${filtered.length === 0 ? '<div class="panel-empty">No templates available</div>' :
                      filtered.map(t => `
                        <div class="panel-card" data-template-id="${this._escapeHtml(t.id)}">
                            <div class="panel-card-title">${this._escapeHtml(t.title || t.id)}</div>
                            <div class="panel-card-meta">${this._escapeHtml(t.agent_type || 'any')} &middot; ${this._escapeHtml(t.priority || 'normal')}</div>
                            <div class="panel-card-actions">
                                <button class="panel-btn btn-sm" data-action="use-template" data-title="${this._escapeHtml(t.title || '')}">Use Template</button>
                            </div>
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
}

export { TemplateTasksPanel };
