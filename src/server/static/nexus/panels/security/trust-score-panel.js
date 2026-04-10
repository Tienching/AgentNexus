/**
 * TrustScorePanel - Agent trust scores and reputation tracking.
 */

class TrustScorePanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._scores = [];
    }

    async refresh() {
        try {
            const data = await this.api.getSecurityScan();
            this._scores = data.trust_scores || data.scores || [];
            this.render(this.container);
        } catch (e) {
            this._scores = [];
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;

        container.innerHTML = `
            ${this._headerHtml()}
            <div class="panel-body">
                <div class="panel-list">
                    ${this._scores.length === 0 ? `
                        <div class="panel-empty">No trust scores available</div>
                        <div class="panel-placeholder-hint">Trust scores are calculated based on task completion rates, quality reviews, and security audits</div>
                    ` :
                      this._scores.map(s => {
                        const score = s.score ?? s.trust_score ?? 0;
                        const level = score >= 80 ? 'high' : score >= 50 ? 'medium' : 'low';
                        return `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._escapeHtml(s.agent_id || s.name || 'Agent')}</div>
                                <div class="panel-list-item-sub">${this._escapeHtml(s.reason || level + ' trust level')}</div>
                            </div>
                            <div class="panel-trust-score score-${level}">
                                <span class="score-value">${score}</span>
                                <span class="score-max">/100</span>
                            </div>
                        </div>`;
                    }).join('')}
                </div>
            </div>
        `;
        this._bindRefreshBtn();
    }
}

export { TrustScorePanel };
