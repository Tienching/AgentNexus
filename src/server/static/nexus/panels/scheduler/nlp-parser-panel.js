/**
 * NLPParserPanel - Natural language to cron/schedule parser.
 */

class NLPParserPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._lastResult = null;
        this._input = '';
    }

    render(container) {
        this.container = container;

        container.innerHTML = `
            ${this._headerHtml()}
            <div class="panel-body">
                <div class="panel-form">
                    <label class="panel-label">Describe the schedule in natural language</label>
                    <div class="panel-input-row">
                        <input type="text" class="panel-input" placeholder='e.g. "every weekday at 9am"' value="${this._escapeHtml(this._input)}" data-role="nlp-input">
                        <button class="panel-btn primary" data-action="parse">Parse</button>
                    </div>
                </div>
                ${this._lastResult ? `
                    <div class="panel-result">
                        <div class="panel-field">
                            <label>Cron Expression</label>
                            <code class="panel-code">${this._escapeHtml(this._lastResult.cron || '')}</code>
                        </div>
                        <div class="panel-field">
                            <label>Human Readable</label>
                            <p>${this._escapeHtml(this._lastResult.human || this._lastResult.description || '')}</p>
                        </div>
                        ${this._lastResult.next_runs ? `
                            <div class="panel-field">
                                <label>Next Runs</label>
                                <ul class="panel-list-plain">
                                    ${this._lastResult.next_runs.map(r => `<li>${this._escapeHtml(r)}</li>`).join('')}
                                </ul>
                            </div>
                        ` : ''}
                    </div>
                ` : ''}
            </div>
        `;

        this._bindRefreshBtn();
        const input = container.querySelector('[data-role="nlp-input"]');
        const parseBtn = container.querySelector('[data-action="parse"]');
        if (input && parseBtn) {
            input.addEventListener('input', (e) => { this._input = e.target.value; });
            input.addEventListener('keydown', (e) => { if (e.key === 'Enter') parseBtn.click(); });
            parseBtn.addEventListener('click', async () => {
                if (!this._input.trim()) return;
                try {
                    const result = await this.api.parseSchedule(this._input);
                    this._lastResult = result;
                    this.render(container);
                } catch (e) {
                    this.showError(e.message);
                }
            });
        }
    }
}

export { NLPParserPanel };
