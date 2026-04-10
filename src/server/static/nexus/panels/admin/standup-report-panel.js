/**
 * StandupReportPanel - Daily standup report aggregation.
 */

class StandupReportPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._report = null;
    }

    async refresh() {
        try {
            const data = await this.api.getStandup();
            this._report = data;
            this.render(this.container);
        } catch (e) {
            this._report = null;
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;
        const report = this._report;

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                <button class="panel-btn" data-action="generate">Generate Report</button>
            `})}
            <div class="panel-body">
                ${!report ? '<div class="panel-empty">No standup report available. Click "Generate Report" to create one.</div>' : `
                    <div class="panel-detail-section">
                        <h4>Summary</h4>
                        <div class="panel-field">
                            <label>Tasks Completed</label>
                            <span>${report.tasks_completed ?? report.completed ?? 0}</span>
                        </div>
                        <div class="panel-field">
                            <label>Tasks In Progress</label>
                            <span>${report.tasks_in_progress ?? report.in_progress ?? 0}</span>
                        </div>
                        <div class="panel-field">
                            <label>Agents Active</label>
                            <span>${report.agents_active ?? report.active_agents ?? 0}</span>
                        </div>
                    </div>
                    ${report.recent_completions?.length ? `
                        <div class="panel-detail-section">
                            <h4>Recent Completions</h4>
                            <div class="panel-list">
                                ${report.recent_completions.map(t => `
                                    <div class="panel-list-item">
                                        <div class="panel-list-item-body">
                                            <div class="panel-list-item-title">${this._escapeHtml(t.title || t.id)}</div>
                                            <div class="panel-list-item-sub">${this._escapeHtml(t.agent_type || '')}</div>
                                        </div>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    ` : ''}
                    ${report.blockers?.length ? `
                        <div class="panel-detail-section">
                            <h4>Blockers</h4>
                            <div class="panel-list">
                                ${report.blockers.map(b => `
                                    <div class="panel-list-item">
                                        <div class="panel-list-item-body">
                                            <div class="panel-list-item-title">${this._escapeHtml(b.title || b.description)}</div>
                                        </div>
                                        <span class="panel-badge badge-warn">Blocked</span>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    ` : ''}
                `}
            </div>
        `;

        this._bindRefreshBtn();
    }
}

export { StandupReportPanel };
