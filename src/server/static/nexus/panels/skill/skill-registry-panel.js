/**
 * SkillRegistryPanel - Browse and manage all registered skills across providers.
 */

class SkillRegistryPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._skills = {};
        this._expandedProvider = null;
    }

    async refresh() {
        try {
            const data = await this.api.getSkills();
            this._skills = data.providers || {};
            this.render(this.container);
        } catch (e) {
            this.showError(e.message);
        }
    }

    render(container) {
        this.container = container;
        const providers = Object.keys(this._skills);
        const totalSkills = providers.reduce((s, p) => s + (this._skills[p]?.length || 0), 0);

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                <button class="panel-btn" data-action="create-skill">+ New Skill</button>
            `})}
            <div class="panel-body">
                <div class="panel-stats">
                    <span class="stat-item"><span class="stat-value">${providers.length}</span> Providers</span>
                    <span class="stat-item"><span class="stat-value">${totalSkills}</span> Skills</span>
                </div>
                <div class="panel-accordion">
                    ${providers.map(p => {
                        const skills = this._skills[p] || [];
                        const isExpanded = this._expandedProvider === p;
                        return `
                        <div class="accordion-section">
                            <div class="accordion-header ${isExpanded ? 'open' : ''}" data-provider="${this._escapeHtml(p)}">
                                <svg class="accordion-chevron" fill="none" stroke="currentColor" viewBox="0 0 24 24" width="16" height="16">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
                                </svg>
                                <span>${this._escapeHtml(p)}</span>
                                <span class="panel-badge">${skills.length}</span>
                            </div>
                            ${isExpanded ? `
                            <div class="accordion-body">
                                ${skills.map(sk => `
                                    <div class="panel-list-item">
                                        <div class="panel-list-item-body">
                                            <div class="panel-list-item-title">${this._escapeHtml(sk.skill_name || sk.name)}</div>
                                            <div class="panel-list-item-sub">${this._escapeHtml(sk.description || '')}</div>
                                        </div>
                                    </div>
                                `).join('')}
                            </div>` : ''}
                        </div>`;
                    }).join('')}
                </div>
            </div>
        `;

        this._bindRefreshBtn();
        container.querySelectorAll('.accordion-header').forEach(el => {
            el.addEventListener('click', () => {
                this._expandedProvider = this._expandedProvider === el.dataset.provider ? null : el.dataset.provider;
                this.render(container);
            });
        });
    }
}

export { SkillRegistryPanel };
