/**
 * FeatureFlagPanel - Toggle feature flags on/off for controlled rollouts.
 */

class FeatureFlagPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._flags = [];
    }

    async refresh() {
        try {
            const data = await this.api.getDiagnostics();
            this._flags = data.feature_flags || data.flags || [];
            this.render(this.container);
        } catch (e) {
            this._flags = [];
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;
        const enabled = this._flags.filter(f => f.enabled).length;

        container.innerHTML = `
            ${this._headerHtml()}
            <div class="panel-body">
                <div class="panel-stats">
                    <span class="stat-item stat-ok"><span class="stat-value">${enabled}</span> Enabled</span>
                    <span class="stat-item"><span class="stat-value">${this._flags.length - enabled}</span> Disabled</span>
                </div>
                <div class="panel-list">
                    ${this._flags.length === 0 ? '<div class="panel-empty">No feature flags configured</div>' :
                      this._flags.map(f => `
                        <div class="panel-list-item" data-flag="${this._escapeHtml(f.name || f.key)}">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._escapeHtml(f.name || f.key)}</div>
                                <div class="panel-list-item-sub">${this._escapeHtml(f.description || '')}</div>
                            </div>
                            <label class="panel-toggle">
                                <input type="checkbox" ${f.enabled ? 'checked' : ''} data-flag-key="${this._escapeHtml(f.name || f.key)}">
                                <span class="toggle-slider"></span>
                            </label>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;

        this._bindRefreshBtn();
        container.querySelectorAll('.panel-toggle input').forEach(input => {
            input.addEventListener('change', (e) => {
                const key = e.target.dataset.flagKey;
                const enabled = e.target.checked;
                // Optimistically update
                const flag = this._flags.find(f => (f.name || f.key) === key);
                if (flag) flag.enabled = enabled;
                console.log(`Feature flag "${key}" ${enabled ? 'enabled' : 'disabled'}`);
            });
        });
    }
}

export { FeatureFlagPanel };
