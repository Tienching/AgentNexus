/**
 * ListView - Accordion-based list view for task management.
 *
 * Features:
 * - Tasks grouped by status in collapsible accordion sections
 * - Bulk selection: select all / deselect / batch status change
 * - Table-style task details (title, status, priority, assignee, dates)
 * - Shares AppDataStore data source with Board view
 *
 * Usage:
 *   const lv = new ListView({
 *       container,
 *       tasks,
 *       statusColumns,
 *       onTaskClick,
 *       onBatchStatusChange,
 *       onDeleteTasks,
 *   });
 *   lv.render();
 */
class ListView {
    constructor(options = {}) {
        this.container = options.container;
        this.tasks = options.tasks || [];
        this.statusColumns = options.statusColumns || [];
        this.onTaskClick = options.onTaskClick || (() => {});
        this.onBatchStatusChange = options.onBatchStatusChange || (async () => {});
        this.onDeleteTasks = options.onDeleteTasks || (async () => {});
        this._selectedIds = new Set();
        this._expandedSections = new Set(this.statusColumns.map(c => c.key));
    }

    updateTasks(tasks) {
        this.tasks = tasks;
        this.render();
    }

    get selectedIds() {
        return new Set(this._selectedIds);
    }

    render() {
        if (!this.container) return;
        const grouped = {};
        this.statusColumns.forEach(col => { grouped[col.key] = []; });
        this.tasks.forEach(t => {
            const s = (t.status || 'inbox').toLowerCase();
            (grouped[s] || grouped['inbox']).push(t);
        });

        const hasSelected = this._selectedIds.size > 0;

        this.container.innerHTML = `
            <div class="list-view">
                <div class="list-view-batch-bar" style="${hasSelected ? '' : 'display:none;'}">
                    <span class="list-view-batch-count">${this._selectedIds.size} selected</span>
                    <select class="form-input form-select list-view-batch-status" style="width:150px;height:28px;font-size:12px;">
                        <option value="">Change status...</option>
                        ${this.statusColumns.map(c => `<option value="${c.key}">${this._esc(c.title)}</option>`).join('')}
                    </select>
                    <button class="action-btn danger list-view-batch-delete" style="padding:4px 10px;font-size:12px;">Delete</button>
                    <button class="action-btn list-view-batch-clear" style="padding:4px 10px;font-size:12px;">Clear Selection</button>
                </div>
                <div class="list-view-sections">
                    ${this.statusColumns.map(col => {
                        const items = grouped[col.key] || [];
                        const isExpanded = this._expandedSections.has(col.key);
                        const allSelected = items.length > 0 && items.every(t => this._selectedIds.has(t.id));
                        const someSelected = items.some(t => this._selectedIds.has(t.id));
                        return `
                            <div class="list-view-section" data-status="${col.key}">
                                <div class="list-view-section-header" data-action="toggle-section" data-status="${col.key}">
                                    <div class="list-view-section-header-left">
                                        <input type="checkbox" class="list-view-group-checkbox" data-status="${col.key}"
                                            ${allSelected ? 'checked' : ''} ${someSelected && !allSelected ? 'data-indeterminate="true"' : ''}
                                            title="Select all ${this._esc(col.title)} tasks">
                                        <svg class="list-view-chevron ${isExpanded ? 'expanded' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:16px;height:16px;transition:transform 0.2s;">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                                        </svg>
                                        <span class="list-view-section-dot" style="background:${col.color};"></span>
                                        <span class="list-view-section-title">${this._esc(col.title)}</span>
                                        <span class="list-view-section-count">${items.length}</span>
                                    </div>
                                </div>
                                <div class="list-view-section-body" style="${isExpanded ? '' : 'display:none;'}">
                                    ${items.length === 0 ? '<div class="list-view-empty">No tasks</div>' :
                                    `<table class="list-view-table">
                                        <thead>
                                            <tr>
                                                <th style="width:32px;"></th>
                                                <th>Title</th>
                                                <th style="width:90px;">Priority</th>
                                                <th style="width:120px;">Assignee</th>
                                                <th style="width:100px;">Due Date</th>
                                                <th style="width:100px;">Updated</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            ${items.map(t => this._renderRow(t)).join('')}
                                        </tbody>
                                    </table>`}
                                </div>
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
        `;

        // Set indeterminate state on checkboxes
        this.container.querySelectorAll('.list-view-group-checkbox[data-indeterminate="true"]').forEach(cb => {
            cb.indeterminate = true;
        });

        this._bindEvents();
    }

    _renderRow(task) {
        const checked = this._selectedIds.has(task.id);
        const priorityColors = { critical: 'var(--error)', serious: 'var(--warning)', normal: 'var(--primary-500)' };
        const dueStr = task.due_date ? new Date(task.due_date * 1000).toLocaleDateString() : '-';
        const updatedStr = this._formatTime(task.updated_at || task.created_at);
        const isOverdue = task.due_date && (task.due_date * 1000 < Date.now()) && task.status !== 'done';

        return `
            <tr class="list-view-row ${checked ? 'selected' : ''} ${isOverdue ? 'overdue' : ''}" data-task-id="${task.id}">
                <td><input type="checkbox" class="list-view-row-checkbox" data-task-id="${task.id}" ${checked ? 'checked' : ''}></td>
                <td class="list-view-row-title">
                    <span class="list-view-row-id">#${task.id.slice(0, 8)}</span>
                    <span>${this._esc(task.description || 'No description')}</span>
                </td>
                <td>
                    <span class="list-view-priority" style="color:${priorityColors[task.priority] || priorityColors.normal};">
                        ${this._esc(task.priority || 'normal')}
                    </span>
                </td>
                <td>${this._esc(task.assigned_to || task.alias || '-')}</td>
                <td class="${isOverdue ? 'list-view-overdue' : ''}">${dueStr}</td>
                <td style="color:var(--text-muted);">${updatedStr}</td>
            </tr>
        `;
    }

    _bindEvents() {
        if (!this.container) return;

        // Section toggle
        this.container.querySelectorAll('[data-action="toggle-section"]').forEach(header => {
            header.addEventListener('click', (e) => {
                if (e.target.closest('.list-view-group-checkbox')) return;
                const status = header.dataset.status;
                if (this._expandedSections.has(status)) {
                    this._expandedSections.delete(status);
                } else {
                    this._expandedSections.add(status);
                }
                this.render();
            });
        });

        // Group checkboxes
        this.container.querySelectorAll('.list-view-group-checkbox').forEach(cb => {
            cb.addEventListener('click', (e) => {
                e.stopPropagation();
                const status = cb.dataset.status;
                const statusTasks = this.tasks.filter(t => t.status === status);
                const allChecked = statusTasks.every(t => this._selectedIds.has(t.id));
                statusTasks.forEach(t => {
                    if (allChecked) this._selectedIds.delete(t.id);
                    else this._selectedIds.add(t.id);
                });
                this.render();
            });
        });

        // Row checkboxes
        this.container.querySelectorAll('.list-view-row-checkbox').forEach(cb => {
            cb.addEventListener('click', (e) => {
                e.stopPropagation();
                const taskId = cb.dataset.taskId;
                if (this._selectedIds.has(taskId)) this._selectedIds.delete(taskId);
                else this._selectedIds.add(taskId);
                this.render();
            });
        });

        // Row click → task detail
        this.container.querySelectorAll('.list-view-row').forEach(row => {
            row.addEventListener('click', (e) => {
                if (e.target.closest('.list-view-row-checkbox')) return;
                this.onTaskClick(row.dataset.taskId);
            });
        });

        // Batch status change
        this.container.querySelector('.list-view-batch-status')?.addEventListener('change', async (e) => {
            const newStatus = e.target.value;
            if (!newStatus || this._selectedIds.size === 0) return;
            await this.onBatchStatusChange(Array.from(this._selectedIds), newStatus);
            this._selectedIds.clear();
            this.render();
        });

        // Batch delete
        this.container.querySelector('.list-view-batch-delete')?.addEventListener('click', async () => {
            if (this._selectedIds.size === 0) return;
            await this.onDeleteTasks(Array.from(this._selectedIds));
            this._selectedIds.clear();
            this.render();
        });

        // Clear selection
        this.container.querySelector('.list-view-batch-clear')?.addEventListener('click', () => {
            this._selectedIds.clear();
            this.render();
        });
    }

    _formatTime(timestamp) {
        if (!timestamp) return '';
        const d = new Date(timestamp);
        const diff = Date.now() - d;
        if (diff < 60000) return 'Just now';
        if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
        if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
        return d.toLocaleDateString();
    }

    _esc(str) {
        const d = document.createElement('div');
        d.textContent = str || '';
        return d.innerHTML;
    }
}

window.ListView = ListView;
