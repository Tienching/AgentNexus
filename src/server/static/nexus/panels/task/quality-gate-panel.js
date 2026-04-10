/**
 * QualityGatePanel - Task quality review and gate management.
 */

class QualityGatePanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._taskId = opts.taskId || null;
        this._reviews = [];
    }

    async refresh() {
        if (!this._taskId) { this.showEmpty('Select a task to view quality reviews'); return; }
        try {
            const data = await this.api.getTaskQualityReviews(this._taskId);
            this._reviews = data.reviews || [];
            this.render(this.container);
        } catch (e) {
            this.showError(e.message);
        }
    }

    render(container) {
        this.container = container;
        if (!this._taskId) { this.showEmpty('Select a task to view quality reviews'); return; }

        const avgScore = this._reviews.length
            ? (this._reviews.reduce((s, r) => s + (r.score || 0), 0) / this._reviews.length).toFixed(1)
            : '—';

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                <button class="panel-btn" data-action="submit-review">Submit Review</button>
            `})}
            <div class="panel-body">
                <div class="panel-stats">
                    <span class="stat-item"><span class="stat-value">${this._reviews.length}</span> Reviews</span>
                    <span class="stat-item"><span class="stat-value">${avgScore}</span> Avg Score</span>
                </div>
                <div class="panel-list">
                    ${this._reviews.map(r => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._escapeHtml(r.reviewer || 'Reviewer')}</div>
                                <div class="panel-list-item-sub">${this._escapeHtml(r.comment || '')}</div>
                            </div>
                            <span class="panel-badge ${r.score >= 7 ? 'badge-ok' : r.score >= 4 ? 'badge-warn' : 'badge-error'}">${r.score ?? '—'}/10</span>
                        </div>
                    `).join('')}
                    ${this._reviews.length === 0 ? '<div class="panel-empty">No quality reviews yet</div>' : ''}
                </div>
            </div>
        `;

        this._bindRefreshBtn();
    }
}

export { QualityGatePanel };
