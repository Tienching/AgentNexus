/**
 * AgentQueuePanel - View agent task queues, pending/running counts, and dispatch status.
 */

class AgentQueuePanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._queues = [];
    }

    async refresh() {
        try {
            const data = await this.api.getWorkload();
            this._queues = data.agents || data.queues || [];
            this.render(this.container);
        } catch (e) {
            this.showError(e.message);
        }
    }

    render(container) {
        this.container = container;
        const totalPending = this._queues.reduce((s, q) => s + (q.pending || q.queued || 0), 0);
        const totalRunning = this._queues.reduce((s, q) => s + (q.running || 0), 0);

        container.innerHTML = `
            ${this._headerHtml()}
            <div class="panel-body">
                <div class="panel-stats">
                    <span class="stat-item"><span class="stat-value">${totalPending}</span> Pending</span>
                    <span class="stat-item stat-ok"><span class="stat-value">${totalRunning}</span> Running</span>
                </div>
                <div class="panel-list">
                    ${this._queues.length === 0 ? '<div class="panel-empty">No queue data available</div>' :
                      this._queues.map(q => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._escapeHtml(q.agent_id || q.name || 'Unknown')}</div>
                                <div class="panel-list-item-sub">Pending: ${q.pending || q.queued || 0} &middot; Running: ${q.running || 0}</div>
                            </div>
                            <div class="panel-queue-bar">
                                <div class="queue-bar-fill" style="width: ${Math.min(100, ((q.running || 0) / Math.max(1, (q.capacity || 5))) * 100)}%"></div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
        this._bindRefreshBtn();
    }

    onRealtimeEvent(eventType, payload) {
        if (eventType.startsWith('task.')) this.refresh();
    }
}

export { AgentQueuePanel };
