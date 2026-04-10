/**
 * TaskBoardPanel - Kanban-style task board with drag-and-drop status updates.
 */

class TaskBoardPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._tasks = [];
        this._filter = '';
    }

    async refresh() {
        try {
            const data = await this.api.getTasks({ pageSize: 100 });
            this._tasks = data.tasks || [];
            this.render(this.container);
        } catch (e) {
            this.showError(e.message);
        }
    }

    render(container) {
        this.container = container;
        const statuses = ['todo', 'doing', 'done', 'failed', 'cancelled'];
        const tasks = this._filter
            ? this._tasks.filter(t => (t.title || t.description || '').toLowerCase().includes(this._filter.toLowerCase()))
            : this._tasks;

        const byStatus = {};
        for (const s of statuses) byStatus[s] = tasks.filter(t => t.status === s);

        container.innerHTML = `
            ${this._headerHtml({ actions: `
                <input type="text" class="panel-input panel-search" placeholder="Filter tasks…" value="${this._escapeHtml(this._filter)}">
            `})}
            <div class="panel-body">
                <div class="panel-kanban">
                    ${statuses.map(s => `
                        <div class="kanban-col" data-status="${s}">
                            <div class="kanban-col-header">
                                <span class="kanban-col-title">${s.charAt(0).toUpperCase() + s.slice(1)}</span>
                                <span class="kanban-col-count">${byStatus[s].length}</span>
                            </div>
                            <div class="kanban-col-items" data-status="${s}">
                                ${byStatus[s].map(t => `
                                    <div class="kanban-card" data-task-id="${this._escapeHtml(t.id)}" draggable="true">
                                        <div class="kanban-card-title">${this._escapeHtml(t.title || t.id)}</div>
                                        <div class="kanban-card-meta">${this._escapeHtml(t.agent_type || '')} ${t.priority ? '&middot; P' + t.priority : ''}</div>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;

        this._bindRefreshBtn();
        this._bindKanbanDnD(container);

        const searchInput = container.querySelector('.panel-search');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this._filter = e.target.value;
                this.render(container);
            });
        }
    }

    _bindKanbanDnD(container) {
        const cards = container.querySelectorAll('.kanban-card[draggable]');
        const columns = container.querySelectorAll('.kanban-col-items');

        cards.forEach(card => {
            card.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', card.dataset.taskId);
                card.classList.add('dragging');
            });
            card.addEventListener('dragend', () => card.classList.remove('dragging'));
        });

        columns.forEach(col => {
            col.addEventListener('dragover', (e) => e.preventDefault());
            col.addEventListener('drop', async (e) => {
                e.preventDefault();
                const taskId = e.dataTransfer.getData('text/plain');
                const newStatus = col.dataset.status;
                if (taskId && newStatus) {
                    try {
                        await this.api.updateTaskStatus(taskId, newStatus);
                        this.refresh();
                    } catch (err) {
                        console.error('Failed to update task status:', err);
                    }
                }
            });
        });
    }

    onRealtimeEvent(eventType, payload) {
        if (eventType.startsWith('task.')) this.refresh();
    }
}

export { TaskBoardPanel };
