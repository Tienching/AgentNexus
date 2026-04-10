/**
 * CronSchedulerPanel - Manage cron schedules: create, edit, pause, trigger.
 */

class CronSchedulerPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._schedules = [];
        this._showForm = false;
    }

    async refresh() {
        try {
            const data = await this.api.getSchedules({ pageSize: 50 });
            this._schedules = data.schedules || data.items || [];
            this.render(this.container);
        } catch (e) {
            this.showError(e.message);
        }
    }

    render(container) {
        this.container = container;
        const active = this._schedules.filter(s => s.status === 'active').length;
        const paused = this._schedules.filter(s => s.status === 'paused').length;

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                <button class="panel-btn primary" data-action="create-schedule">+ New Schedule</button>
            `})}
            <div class="panel-body">
                <div class="panel-stats">
                    <span class="stat-item stat-ok"><span class="stat-value">${active}</span> Active</span>
                    <span class="stat-item stat-warn"><span class="stat-value">${paused}</span> Paused</span>
                    <span class="stat-item"><span class="stat-value">${this._schedules.length}</span> Total</span>
                </div>
                <div class="panel-list">
                    ${this._schedules.length === 0 ? '<div class="panel-empty">No schedules configured</div>' :
                      this._schedules.map(s => `
                        <div class="panel-list-item" data-schedule-id="${this._escapeHtml(s.id)}">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._escapeHtml(s.name || s.id)}</div>
                                <div class="panel-list-item-sub">${this._escapeHtml(s.cron || s.schedule || '')} &middot; ${this._escapeHtml(s.task_type || '')}</div>
                            </div>
                            <span class="panel-badge ${s.status === 'active' ? 'badge-ok' : s.status === 'paused' ? 'badge-warn' : 'badge-muted'}">${s.status}</span>
                            <div class="panel-list-actions">
                                <button class="panel-btn btn-sm" data-action="trigger" data-id="${this._escapeHtml(s.id)}" title="Trigger now">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="12" height="12">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/>
                                    </svg>
                                </button>
                                <button class="panel-btn btn-sm" data-action="${s.status === 'active' ? 'pause' : 'resume'}" data-id="${this._escapeHtml(s.id)}">
                                    ${s.status === 'active' ? 'Pause' : 'Resume'}
                                </button>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;

        this._bindRefreshBtn();
        container.querySelectorAll('[data-action="trigger"]').forEach(btn => {
            btn.addEventListener('click', async () => {
                try { await this.api.triggerSchedule(btn.dataset.id); this.refresh(); } catch (e) { this.showError(e.message); }
            });
        });
        container.querySelectorAll('[data-action="pause"]').forEach(btn => {
            btn.addEventListener('click', async () => {
                try { await this.api.pauseSchedule(btn.dataset.id); this.refresh(); } catch (e) { this.showError(e.message); }
            });
        });
        container.querySelectorAll('[data-action="resume"]').forEach(btn => {
            btn.addEventListener('click', async () => {
                try { await this.api.resumeSchedule(btn.dataset.id); this.refresh(); } catch (e) { this.showError(e.message); }
            });
        });
    }
}

export { CronSchedulerPanel };
