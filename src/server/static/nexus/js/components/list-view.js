/**
 * ListView - Accordion-based list view for task management.
 *
 * Features:
 * - Tasks grouped by status in collapsible accordion sections
 * - Hover-to-show row checkboxes (visible on hover or when selected)
 * - Floating batch action toolbar (status, priority, assign, delete)
 * - Group header checkboxes with indeterminate state
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
 *       onBatchPriorityChange,
 *       onBatchAssign,
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
        this.onBatchPriorityChange = options.onBatchPriorityChange || (async () => {});
        this.onBatchAssign = options.onBatchAssign || (async () => {});
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
                ${this._renderBatchToolbar()}
                <div class="list-view-sections">
                    ${this.statusColumns.map(col => {
                        const items = grouped[col.key] || [];
                        const isExpanded = this._expandedSections.has(col.key);
                        return this._renderGroupSection(col, items, isExpanded);
                    }).join('')}
                </div>
            </div>
        `;

        // Set indeterminate state on group checkboxes
        this.container.querySelectorAll('.list-view-group-checkbox[data-indeterminate="true"]').forEach(cb => {
            cb.indeterminate = true;
        });

        this._bindEvents();
    }

    // ── Batch Toolbar ──────────────────────────────────────────────

    _renderBatchToolbar() {
        const count = this._selectedIds.size;
        const display = count > 0 ? 'flex' : 'none';
        return `
            <div class="batch-toolbar" style="display:${display}">
                <span class="batch-count">${count} selected</span>
                <div class="batch-actions">
                    <select class="form-input form-select batch-status-select" style="width:140px;height:28px;font-size:12px;">
                        <option value="">Change Status...</option>
                        ${this.statusColumns.map(c => `<option value="${c.key}">${this._esc(c.title)}</option>`).join('')}
                    </select>
                    <select class="form-input form-select batch-priority-select" style="width:130px;height:28px;font-size:12px;">
                        <option value="">Change Priority...</option>
                        <option value="critical">Critical</option>
                        <option value="serious">Serious</option>
                        <option value="normal">Normal</option>
                        <option value="low">Low</option>
                    </select>
                    <button class="action-btn batch-assign-btn" style="padding:4px 10px;font-size:12px;" title="Assign to...">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:14px;height:14px;vertical-align:middle;margin-right:2px;">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
                        </svg>
                        Assign
                    </button>
                    <button class="action-btn danger batch-delete-btn" style="padding:4px 10px;font-size:12px;">Delete</button>
                    <button class="action-btn batch-clear-btn" style="padding:4px 10px;font-size:12px;">Clear</button>
                </div>
            </div>
        `;
    }

    // ── Group Section ──────────────────────────────────────────────

    _renderGroupSection(col, items, isExpanded) {
        const selectedInGroup = items.filter(t => this._selectedIds.has(t.id)).length;
        const allSelected = items.length > 0 && selectedInGroup === items.length;
        const someSelected = selectedInGroup > 0 && !allSelected;

        return `
            <div class="list-view-section" data-status="${col.key}">
                <div class="list-view-section-header" data-action="toggle-section" data-status="${col.key}">
                    <div class="list-view-section-header-left">
                        <input type="checkbox" class="list-view-group-checkbox" data-status="${col.key}"
                            ${allSelected ? 'checked' : ''} ${someSelected ? 'data-indeterminate="true"' : ''}
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
    }

    // ── Row ────────────────────────────────────────────────────────

    _renderRow(task) {
        const checked = this._selectedIds.has(task.id);
        const priorityColors = { critical: 'var(--error)', serious: 'var(--warning)', normal: 'var(--primary-500)' };
        const dueStr = task.due_date ? new Date(task.due_date * 1000).toLocaleDateString() : '-';
        const updatedStr = this._formatTime(task.updated_at || task.created_at);
        const isOverdue = task.due_date && (task.due_date * 1000 < Date.now()) && task.status !== 'done';

        return `
            <tr class="list-view-row ${checked ? 'selected' : ''} ${isOverdue ? 'overdue' : ''}" data-task-id="${task.id}">
                <td class="list-row-checkbox-cell">
                    <div class="list-row-checkbox ${checked ? 'visible' : ''}">
                        <input type="checkbox" class="list-view-row-checkbox" data-task-id="${task.id}" ${checked ? 'checked' : ''}>
                    </div>
                </td>
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

    // ── Assignee Picker Dropdown ───────────────────────────────────

    _showAssigneePicker(anchorEl) {
        // Collect unique assignees from current tasks
        const assignees = [...new Set(this.tasks.map(t => t.assigned_to || t.alias).filter(Boolean))];

        let dropdown = this.container.querySelector('.batch-assignee-dropdown');
        if (dropdown) dropdown.remove();

        dropdown = document.createElement('div');
        dropdown.className = 'batch-assignee-dropdown';
        dropdown.innerHTML = `
            <div class="batch-assignee-dropdown-inner">
                <input type="text" class="form-input batch-assignee-search" placeholder="Type assignee name..." style="width:100%;height:28px;font-size:12px;box-sizing:border-box;">
                <div class="batch-assignee-list">
                    ${assignees.map(a => `<div class="batch-assignee-option" data-assignee="${this._esc(a)}">${this._esc(a)}</div>`).join('')}
                </div>
            </div>
        `;

        // Position near the button
        const rect = anchorEl.getBoundingClientRect();
        const containerRect = this.container.getBoundingClientRect();
        dropdown.style.position = 'absolute';
        dropdown.style.top = `${rect.bottom - containerRect.top + 4}px`;
        dropdown.style.left = `${rect.left - containerRect.left}px`;
        dropdown.style.zIndex = '100';

        this.container.querySelector('.list-view').appendChild(dropdown);

        // Focus search
        const searchInput = dropdown.querySelector('.batch-assignee-search');
        searchInput.focus();

        // Filter on search
        searchInput.addEventListener('input', () => {
            const q = searchInput.value.toLowerCase();
            dropdown.querySelectorAll('.batch-assignee-option').forEach(opt => {
                opt.style.display = opt.dataset.assignee.toLowerCase().includes(q) ? '' : 'none';
            });
        });

        // Select assignee
        dropdown.querySelectorAll('.batch-assignee-option').forEach(opt => {
            opt.addEventListener('click', async () => {
                const assignee = opt.dataset.assignee;
                await this.onBatchAssign(Array.from(this._selectedIds), assignee);
                this._selectedIds.clear();
                dropdown.remove();
                this.render();
            });
        });

        // Close on outside click
        const closeHandler = (e) => {
            if (!dropdown.contains(e.target) && e.target !== anchorEl) {
                dropdown.remove();
                document.removeEventListener('click', closeHandler, true);
            }
        };
        setTimeout(() => document.addEventListener('click', closeHandler, true), 0);
    }

    // ── Event Binding ──────────────────────────────────────────────

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

        // Group checkboxes (with indeterminate support)
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

        // Row click -> task detail
        this.container.querySelectorAll('.list-view-row').forEach(row => {
            row.addEventListener('click', (e) => {
                if (e.target.closest('.list-view-row-checkbox')) return;
                this.onTaskClick(row.dataset.taskId);
            });
        });

        // Batch status change
        this.container.querySelector('.batch-status-select')?.addEventListener('change', async (e) => {
            const newStatus = e.target.value;
            if (!newStatus || this._selectedIds.size === 0) return;
            await this.onBatchStatusChange(Array.from(this._selectedIds), newStatus);
            this._selectedIds.clear();
            this.render();
        });

        // Batch priority change
        this.container.querySelector('.batch-priority-select')?.addEventListener('change', async (e) => {
            const newPriority = e.target.value;
            if (!newPriority || this._selectedIds.size === 0) return;
            await this.onBatchPriorityChange(Array.from(this._selectedIds), newPriority);
            this._selectedIds.clear();
            this.render();
        });

        // Batch assign
        this.container.querySelector('.batch-assign-btn')?.addEventListener('click', () => {
            if (this._selectedIds.size === 0) return;
            this._showAssigneePicker(this.container.querySelector('.batch-assign-btn'));
        });

        // Batch delete
        this.container.querySelector('.batch-delete-btn')?.addEventListener('click', async () => {
            if (this._selectedIds.size === 0) return;
            await this.onDeleteTasks(Array.from(this._selectedIds));
            this._selectedIds.clear();
            this.render();
        });

        // Clear selection
        this.container.querySelector('.batch-clear-btn')?.addEventListener('click', () => {
            this._selectedIds.clear();
            this.render();
        });
    }

    // ── Helpers ────────────────────────────────────────────────────

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
