/**
 * TokenUsagePanel - Track token usage across sessions and providers.
 */

class TokenUsagePanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._usage = [];
    }

    async refresh() {
        try {
            const data = await this.api.getDiagnostics();
            this._usage = data.token_usage || data.usage || [];
            this.render(this.container);
        } catch (e) {
            this._usage = [];
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;
        const totalTokens = this._usage.reduce((s, u) => s + (u.total_tokens || u.tokens || 0), 0);
        const totalCost = this._usage.reduce((s, u) => s + (u.cost || 0), 0);

        container.innerHTML = `
            ${this._headerHtml()}
            <div class="panel-body">
                <div class="panel-stats">
                    <span class="stat-item"><span class="stat-value">${(totalTokens / 1000).toFixed(1)}k</span> Tokens</span>
                    <span class="stat-item"><span class="stat-value">$${totalCost.toFixed(2)}</span> Cost</span>
                </div>
                <div class="panel-list">
                    ${this._usage.length === 0 ? '<div class="panel-empty">No token usage data</div>' :
                      this._usage.map(u => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._escapeHtml(u.provider || u.model || 'Unknown')}</div>
                                <div class="panel-list-item-sub">
                                    Prompt: ${(u.prompt_tokens || 0).toLocaleString()} &middot;
                                    Completion: ${(u.completion_tokens || 0).toLocaleString()} &middot;
                                    Total: ${(u.total_tokens || u.tokens || 0).toLocaleString()}
                                </div>
                            </div>
                            <span class="panel-badge">${u.cost != null ? '$' + u.cost.toFixed(4) : ''}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
        this._bindRefreshBtn();
    }
}

export { TokenUsagePanel };
