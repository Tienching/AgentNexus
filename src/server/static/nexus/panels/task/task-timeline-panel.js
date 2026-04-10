/**
 * TaskTimelinePanel - Chronological view of task state changes and events.
 */

class TaskTimelinePanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._events = [];
    }

    async refresh() {
        try {
            const data = await this.api.getAuditLog({ action: 'task', limit: 50 });
            this._events = data.entries || data.logs || [];
            this.render(this.container);
        } catch (e) {
            this._events = [];
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;

        container.innerHTML = `
            ${this._headerHtml()}
            <div class="panel-body">
                ${this._events.length === 0 ? '<div class="panel-empty">No task events recorded</div>' : `
                <div class="panel-timeline">
                    ${this._events.map(ev => {
                        const time = ev.timestamp ? new Date(ev.timestamp).toLocaleString() : '';
                        const statusClass = ev.action?.includes('fail') ? 'status-offline' :
                                           ev.action?.includes('complet') ? 'status-online' : 'status-warn';
                        return `
                        <div class="timeline-item">
                            <div class="timeline-dot ${statusClass}"></div>
                            <div class="timeline-content">
                                <div class="timeline-title">${this._escapeHtml(ev.action || ev.event_type || 'Event')}</div>
                                <div class="timeline-meta">${time} ${ev.task_id ? '&middot; ' + this._escapeHtml(ev.task_id.slice(0,8)) : ''}</div>
                                ${ev.detail ? `<div class="timeline-detail">${this._escapeHtml(ev.detail)}</div>` : ''}
                            </div>
                        </div>`;
                    }).join('')}
                </div>`}
            </div>
        `;
        this._bindRefreshBtn();
    }

    onRealtimeEvent(eventType, payload) {
        if (eventType.startsWith('task.')) {
            this._events.unshift({ ...payload, timestamp: Date.now() });
            if (this._events.length > 100) this._events.length = 100;
            if (this.container) this.render(this.container);
        }
    }
}

export { TaskTimelinePanel };
