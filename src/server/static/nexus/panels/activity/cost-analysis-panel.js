/**
 * CostAnalysisPanel - Aggregated cost analysis with breakdowns by provider/model/user.
 */

class CostAnalysisPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._data = null;
    }

    async refresh() {
        try {
            const data = await this.api.getDiagnostics();
            this._data = data.cost_analysis || data.billing || { total: 0, breakdown: [] };
            this.render(this.container);
        } catch (e) {
            this._data = { total: 0, breakdown: [] };
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;
        const breakdown = this._data?.breakdown || [];
        const total = this._data?.total || 0;

        container.innerHTML = `
            ${this._headerHtml()}
            <div class="panel-body">
                <div class="panel-stats">
                    <span class="stat-item"><span class="stat-value">$${total.toFixed(2)}</span> Total Cost</span>
                </div>
                <div class="panel-chart-placeholder">
                    ${breakdown.length === 0 ? '<div class="panel-empty">No cost data available</div>' :
                      breakdown.map(b => {
                        const pct = total > 0 ? ((b.cost / total) * 100).toFixed(1) : 0;
                        return `
                        <div class="panel-bar-row">
                            <div class="panel-bar-label">${this._escapeHtml(b.provider || b.model || b.label)}</div>
                            <div class="panel-bar-track">
                                <div class="panel-bar-fill" style="width: ${pct}%"></div>
                            </div>
                            <div class="panel-bar-value">$${(b.cost || 0).toFixed(2)} (${pct}%)</div>
                        </div>`;
                    }).join('')}
                </div>
            </div>
        `;
        this._bindRefreshBtn();
    }
}

export { CostAnalysisPanel };
