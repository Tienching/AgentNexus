/**
 * NotificationPanel - User notifications and alerts.
 */

class NotificationPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._notifications = [];
    }

    async refresh() {
        try {
            const data = await this.api.getAuditLog({ action: 'notification', limit: 30 });
            this._notifications = data.entries || data.logs || [];
            this.render(this.container);
        } catch (e) {
            this._notifications = [];
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;
        const unread = this._notifications.filter(n => !n.read).length;

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                ${unread > 0 ? `<button class="panel-btn" data-action="mark-all-read">Mark All Read</button>` : ''}
            `})}
            <div class="panel-body">
                ${unread > 0 ? `<div class="panel-stats"><span class="stat-item stat-warn"><span class="stat-value">${unread}</span> Unread</span></div>` : ''}
                <div class="panel-list">
                    ${this._notifications.length === 0 ? '<div class="panel-empty">No notifications</div>' :
                      this._notifications.map(n => `
                        <div class="panel-list-item ${n.read ? '' : 'unread'}">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._escapeHtml(n.action || n.title || 'Notification')}</div>
                                <div class="panel-list-item-sub">${this._escapeHtml(n.detail || n.message || '')}</div>
                            </div>
                            <span class="panel-badge ${n.level === 'error' ? 'badge-error' : n.level === 'warning' ? 'badge-warn' : 'badge-ok'}">${n.level || 'info'}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;

        this._bindRefreshBtn();
    }

    onRealtimeEvent(eventType, payload) {
        if (eventType === 'notification') {
            this._notifications.unshift({ ...payload, read: false });
            if (this.container) this.render(this.container);
        }
    }
}

export { NotificationPanel };
