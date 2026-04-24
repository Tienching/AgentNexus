/**
 * TaskSummaryStrip - Summary Metrics Strip for the task workbench (TV-007).
 *
 * Displays metric cards at the top of the workbench showing counts for:
 * All (total), Active, Doing, Reviewing, Failed, Cancelled, Scheduled.
 *
 * Features:
 * - Colored indicator dots per metric (Running dot pulses)
 * - Clickable cards that notify parent via onMetricClick callback
 * - Active card highlighted with border
 * - getStyles() static method for component CSS
 *
 * Usage:
 *   const strip = new TaskSummaryStrip({
 *       onMetricClick: (key) => console.log('metric', key)
 *   });
 *   strip.render(container, { total: 42, active: 10, running: 3, ... });
 *   strip.setActiveMetric('running');
 */

class TaskSummaryStrip {
    constructor(options = {}) {
        this._container = null;
        this._onMetricClick = options.onMetricClick || (() => {});
        this._activeMetric = null;
        this._metrics = { total: 0, active: 0, running: 0, reviewing: 0, failed: 0, cancelled: 0, scheduled: 0 };
    }

    /**
     * Render the summary strip into the given container.
     * @param {HTMLElement} container - Target DOM element
     * @param {Object} metrics - Metric counts { total, active, running, reviewing, failed, cancelled, scheduled }
     */
    render(container, metrics) {
        this._container = container;
        if (metrics) this._metrics = metrics;
        container.innerHTML = this._buildHTML();
        this._bindEvents();
    }

    /**
     * Update metrics and re-render.
     * @param {Object} metrics - New metric counts
     */
    update(metrics) {
        this._metrics = metrics;
        if (this._container) {
            this._container.innerHTML = this._buildHTML();
            this._bindEvents();
        }
    }

    /**
     * Set the currently active (highlighted) metric card.
     * @param {string|null} key - Metric key to highlight, or null to clear
     */
    setActiveMetric(key) {
        this._activeMetric = key;
        if (this._container) {
            this._container.querySelectorAll('.summary-card').forEach(card => {
                if (card.dataset.metric === key) {
                    card.classList.add('summary-card-active');
                } else {
                    card.classList.remove('summary-card-active');
                }
            });
        }
    }

    /**
     * Build the HTML for the summary strip.
     * @returns {string} HTML string
     * @private
     */
    _buildHTML() {
        const cards = [
            { key: 'total', label: 'All', dotClass: 'summary-dot-gray' },
            { key: 'active', label: 'Active', dotClass: 'summary-dot-blue' },
            { key: 'running', label: 'Doing', dotClass: 'summary-dot-green' },
            { key: 'reviewing', label: 'Reviewing', dotClass: 'summary-dot-yellow' },
            { key: 'failed', label: 'Failed', dotClass: 'summary-dot-red' },
            { key: 'cancelled', label: 'Cancelled', dotClass: 'summary-dot-gray' },
            { key: 'scheduled', label: 'Scheduled', dotClass: 'summary-dot-purple' },
        ];
        return `<div class="task-summary-strip">
            ${cards.map(c => `
                <div class="summary-card ${this._activeMetric === c.key ? 'summary-card-active' : ''}" data-metric="${c.key}">
                    <span class="summary-dot ${c.dotClass} ${c.key === 'running' ? 'summary-dot-pulse' : ''}"></span>
                    <span class="summary-value">${this._metricValue(c.key)}</span>
                    <span class="summary-label">${c.label}</span>
                </div>
            `).join('')}
        </div>`;
    }

    _metricValue(key) {
        if (key === 'total') {
            return this._metrics.total ?? this._metrics.all ?? 0;
        }
        return this._metrics[key] ?? 0;
    }

    /**
     * Bind click events to summary cards.
     * @private
     */
    _bindEvents() {
        if (!this._container) return;
        this._container.querySelectorAll('.summary-card').forEach(card => {
            card.addEventListener('click', () => {
                const key = card.dataset.metric;
                this.setActiveMetric(key);
                this._onMetricClick(key);
            });
        });
    }

    /**
     * Return the CSS styles for this component.
     * @returns {string} CSS string
     */
    static getStyles() {
        return `
            .task-summary-strip { display: flex; gap: 12px; padding: 8px 16px; background: var(--bg-secondary, #1e1e2e); border-radius: 8px; margin-bottom: 8px; }
            .summary-card { display: flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 6px; cursor: pointer; transition: background 0.15s; background: var(--bg-primary, #2a2a3e); border: 1px solid transparent; }
            .summary-card:hover { background: var(--bg-hover, #363650); }
            .summary-card-active { border: 1px solid var(--primary-500, #6366f1); }
            .summary-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
            .summary-dot-gray { background: #6b7280; }
            .summary-dot-blue { background: #3b82f6; }
            .summary-dot-green { background: #10b981; }
            .summary-dot-yellow { background: #f59e0b; }
            .summary-dot-red { background: #ef4444; }
            .summary-dot-purple { background: #8b5cf6; }
            .summary-dot-pulse { animation: summary-pulse 1.5s ease-in-out infinite; }
            @keyframes summary-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
            .summary-value { font-weight: 600; font-size: 16px; color: var(--text-primary, #e2e8f0); }
            .summary-label { font-size: 12px; color: var(--text-secondary, #94a3b8); }
        `;
    }
}

window.TaskSummaryStrip = TaskSummaryStrip;
