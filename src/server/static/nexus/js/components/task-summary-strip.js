/**
 * TaskSummaryStrip - Summary Metrics Strip for the task workbench (TV-007).
 *
 * Displays metric cards at the top of the workbench showing counts for:
 * All plus each visible Kanban lane: To Do, Doing, In Review, Done, Failed, Cancelled, Scheduled.
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
        this._metrics = { total: 0, pending: 0, running: 0, in_review: 0, completed: 0, failed: 0, cancelled: 0, scheduled: 0 };
    }

    /**
     * Render the summary strip into the given container.
     * @param {HTMLElement} container - Target DOM element
     * @param {Object} metrics - Metric counts { total, pending, running, in_review, completed, failed, cancelled, scheduled }
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

    static _statusLabels() {
        if (typeof TaskViewModel !== 'undefined' && TaskViewModel.STATUS_LABELS) {
            return TaskViewModel.STATUS_LABELS;
        }
        return {
            pending: 'To Do',
            running: 'Doing',
            in_review: 'In Review',
            completed: 'Done',
            failed: 'Failed',
            cancelled: 'Cancelled',
        };
    }

    /**
     * Build the HTML for the summary strip.
     * @returns {string} HTML string
     * @private
     */
    _buildHTML() {
        const statusLabels = TaskSummaryStrip._statusLabels();
        const cards = [
            { key: 'total', label: 'All', dotClass: 'summary-dot-gray' },
            { key: 'pending', label: statusLabels.pending, dotClass: 'summary-dot-pending' },
            { key: 'running', label: statusLabels.running, dotClass: 'summary-dot-running' },
            { key: 'in_review', label: statusLabels.in_review, dotClass: 'summary-dot-in-review' },
            { key: 'completed', label: statusLabels.completed, dotClass: 'summary-dot-completed' },
            { key: 'failed', label: statusLabels.failed, dotClass: 'summary-dot-failed' },
            { key: 'cancelled', label: statusLabels.cancelled, dotClass: 'summary-dot-cancelled' },
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
            .summary-dot-pending { background: var(--status-pending, #f59e0b); }
            .summary-dot-running { background: var(--status-running, #3b82f6); }
            .summary-dot-in-review { background: var(--status-in-review, #8b5cf6); }
            .summary-dot-completed { background: var(--status-completed, #10b981); }
            .summary-dot-failed { background: var(--status-failed, #ef4444); }
            .summary-dot-cancelled { background: var(--status-cancelled, #9ca3af); }
            .summary-dot-purple { background: #8b5cf6; }
            .summary-dot-pulse { animation: summary-pulse 1.5s ease-in-out infinite; }
            @keyframes summary-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
            .summary-value { font-weight: 600; font-size: 16px; color: var(--text-primary, #e2e8f0); }
            .summary-label { font-size: 12px; color: var(--text-secondary, #94a3b8); }
        `;
    }
}

window.TaskSummaryStrip = TaskSummaryStrip;
