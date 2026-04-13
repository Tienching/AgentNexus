/**
 * FilterBar - Toolbar dropdown filter system for the task board.
 *
 * Features:
 * - 5 dimensions: Status, Priority, Assignee, Creator, Due Date
 * - Toolbar button group with active count badges
 * - Dropdown menus with search, checkboxes, and real-time counts
 * - localStorage persistence
 * - Integrates with TaskBoardPanel
 *
 * Usage:
 *   const fb = new FilterBar(taskBoardPanel);
 *   fb.render(toolbarContainer);
 *   fb.updateCounts(tasks);
 *   const filtered = fb.applyFilter(tasks);
 */
class FilterBar {
    constructor(taskBoardPanel) {
        this.panel = taskBoardPanel;
        this.filters = {
            status: { label: 'Status', values: new Set(), options: [] },
            priority: { label: 'Priority', values: new Set(), options: [] },
            assignee: { label: 'Assignee', values: new Set(), options: [] },
            creator: { label: 'Creator', values: new Set(), options: [] },
            dueDate: { label: 'Due Date', values: new Set(), options: [] },
        };
        this._counts = { status: {}, priority: {}, assignee: {}, creator: {}, dueDate: {} };
        this._openDropdown = null;
        this._dropdownEl = null;
        this._container = null;
        this._loadPersisted();
    }

    /** Static option definitions */
    static STATUS_OPTIONS = [
        { key: 'inbox', label: 'Inbox', color: 'var(--status-inbox)' },
        { key: 'in_progress', label: 'In Progress', color: 'var(--status-in-progress)' },
        { key: 'in_review', label: 'In Review', color: 'var(--status-in-review)' },
        { key: 'done', label: 'Done', color: 'var(--status-done)' },
        { key: 'failed', label: 'Failed', color: 'var(--status-failed)' },
        { key: 'archived', label: 'Archived', color: 'var(--status-archived)' },
    ];

    /** Normalize legacy status values to 6-status model */
    static STATUS_MAP = {
        'todo': 'inbox', 'pending': 'inbox',
        'assigned': 'in_progress', 'awaiting_owner': 'in_progress', 'doing': 'in_progress',
        'review': 'in_review', 'quality_review': 'in_review',
        'completed': 'done', 'cancelled': 'archived',
    };

    static _normalizeStatus(status) {
        const s = String(status || '').trim().toLowerCase();
        return FilterBar.STATUS_MAP[s] || (['inbox','in_progress','in_review','done','failed','archived'].includes(s) ? s : 'inbox');
    }

    static PRIORITY_OPTIONS = [
        { key: 'critical', label: 'Critical', color: 'var(--error, #ef4444)' },
        { key: 'serious', label: 'Serious', color: 'var(--warning, #f59e0b)' },
        { key: 'normal', label: 'Normal', color: 'var(--primary-500)' },
        { key: 'low', label: 'Low', color: 'var(--text-muted)' },
    ];

    static DUE_DATE_OPTIONS = [
        { key: 'overdue', label: 'Overdue' },
        { key: 'today', label: 'Today' },
        { key: 'this_week', label: 'This week' },
        { key: 'no_due_date', label: 'No due date' },
    ];

    /** Dimensions that support search in dropdown */
    static SEARCHABLE = new Set(['assignee', 'creator']);

    hasActiveFilters() {
        return Object.values(this.filters).some(f => f.values.size > 0);
    }

    getActiveFilterSummary() {
        const parts = [];
        for (const [key, f] of Object.entries(this.filters)) {
            if (f.values.size > 0) {
                parts.push(`${f.label}: ${f.values.size}`);
            }
        }
        return parts.join(', ');
    }

    resetAll() {
        for (const f of Object.values(this.filters)) {
            f.values.clear();
        }
        this._persist();
        this._renderButtons();
        this._closeDropdown();
    }

    /**
     * Update option lists and counts from current task list.
     * @param {Array} tasks - full (unfiltered) task list
     */
    updateCounts(tasks) {
        this._counts = { status: {}, priority: {}, assignee: {}, creator: {}, dueDate: {} };
        const assigneeSet = new Set();
        const creatorSet = new Set();

        tasks.forEach(t => {
            // Status
            const s = FilterBar._normalizeStatus(t.status);
            this._counts.status[s] = (this._counts.status[s] || 0) + 1;

            // Priority
            const p = t.priority || 'normal';
            this._counts.priority[p] = (this._counts.priority[p] || 0) + 1;

            // Assignee
            const a = t.assigned_to || t.alias || '';
            if (a) {
                assigneeSet.add(a);
                this._counts.assignee[a] = (this._counts.assignee[a] || 0) + 1;
            }
            this._counts.assignee['__none__'] = (this._counts.assignee['__none__'] || 0) + (a ? 0 : 1);

            // Creator
            const c = t.created_by || '';
            if (c) {
                creatorSet.add(c);
                this._counts.creator[c] = (this._counts.creator[c] || 0) + 1;
            }

            // Due Date
            this._computeDueDateCount(t);
        });

        // Set static options
        this.filters.status.options = FilterBar.STATUS_OPTIONS;
        this.filters.priority.options = FilterBar.PRIORITY_OPTIONS;
        this.filters.dueDate.options = FilterBar.DUE_DATE_OPTIONS;

        // Set dynamic options
        this.filters.assignee.options = [
            { key: '__none__', label: 'No assignee' },
            ...Array.from(assigneeSet).sort().map(a => ({ key: a, label: a })),
        ];
        this.filters.creator.options = Array.from(creatorSet).sort().map(c => ({ key: c, label: c }));

        this._renderButtons();
    }

    _computeDueDateCount(t) {
        const due = t.due_date;
        if (!due) {
            this._counts.dueDate['no_due_date'] = (this._counts.dueDate['no_due_date'] || 0) + 1;
            return;
        }
        const d = new Date(due);
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const endOfWeek = new Date(today);
        endOfWeek.setDate(endOfWeek.getDate() + (7 - endOfWeek.getDay()));

        if (d < today) {
            this._counts.dueDate['overdue'] = (this._counts.dueDate['overdue'] || 0) + 1;
        } else if (d.toDateString() === today.toDateString()) {
            this._counts.dueDate['today'] = (this._counts.dueDate['today'] || 0) + 1;
        } else if (d <= endOfWeek) {
            this._counts.dueDate['this_week'] = (this._counts.dueDate['this_week'] || 0) + 1;
        }
    }

    /**
     * Apply filters to a task list.
     * @param {Array} tasks
     * @returns {Array} filtered tasks
     */
    applyFilter(tasks) {
        return tasks.filter(t => {
            // Status
            if (this.filters.status.values.size > 0) {
                if (!this.filters.status.values.has(FilterBar._normalizeStatus(t.status))) return false;
            }

            // Priority
            if (this.filters.priority.values.size > 0) {
                if (!this.filters.priority.values.has(t.priority || 'normal')) return false;
            }

            // Assignee
            if (this.filters.assignee.values.size > 0) {
                const a = t.assigned_to || t.alias || '';
                const key = a || '__none__';
                if (!this.filters.assignee.values.has(key)) return false;
            }

            // Creator
            if (this.filters.creator.values.size > 0) {
                const c = t.created_by || '';
                if (!this.filters.creator.values.has(c)) return false;
            }

            // Due Date
            if (this.filters.dueDate.values.size > 0) {
                const key = this._getDueDateKey(t);
                if (!this.filters.dueDate.values.has(key)) return false;
            }

            return true;
        });
    }

    _getDueDateKey(t) {
        const due = t.due_date;
        if (!due) return 'no_due_date';
        const d = new Date(due);
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const endOfWeek = new Date(today);
        endOfWeek.setDate(endOfWeek.getDate() + (7 - endOfWeek.getDay()));

        if (d < today) return 'overdue';
        if (d.toDateString() === today.toDateString()) return 'today';
        if (d <= endOfWeek) return 'this_week';
        return null; // beyond this week, not in any bucket
    }

    /**
     * Render filter bar into a toolbar container.
     * @param {HTMLElement} toolbarContainer
     */
    render(toolbarContainer) {
        this._container = toolbarContainer;
        this._container.innerHTML = '';
        this._container.className = 'filter-bar';
        this._renderButtons();

        // Close dropdown on outside click
        document.addEventListener('click', (e) => {
            if (this._dropdownEl && !this._dropdownEl.contains(e.target) &&
                !this._container.contains(e.target)) {
                this._closeDropdown();
            }
        });
    }

    _renderButtons() {
        if (!this._container) return;

        this._container.innerHTML = '';
        const keys = ['status', 'priority', 'assignee', 'creator', 'dueDate'];
        keys.forEach(key => {
            const f = this.filters[key];
            const activeCount = f.values.size;
            const btn = document.createElement('button');
            btn.className = `filter-btn${activeCount > 0 ? ' has-filter' : ''}`;
            btn.dataset.filterKey = key;
            btn.innerHTML = `${this._esc(f.label)}${activeCount > 0 ? ` <span class="filter-btn-count">(${activeCount})</span>` : ''} <span class="filter-btn-arrow">&#9662;</span>`;

            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this._toggleDropdown(key, btn);
            });

            this._container.appendChild(btn);
        });
    }

    _toggleDropdown(filterKey, anchorEl) {
        if (this._openDropdown === filterKey) {
            this._closeDropdown();
            return;
        }
        this._closeDropdown();
        this._openDropdown = filterKey;
        this._renderDropdown(filterKey, anchorEl);
    }

    _closeDropdown() {
        if (this._dropdownEl) {
            this._dropdownEl.remove();
            this._dropdownEl = null;
        }
        this._openDropdown = null;
    }

    _renderDropdown(filterKey, anchorEl) {
        const f = this.filters[filterKey];
        const dropdown = document.createElement('div');
        dropdown.className = 'filter-dropdown';

        // Position below the button
        const rect = anchorEl.getBoundingClientRect();
        const containerRect = this._container.getBoundingClientRect();
        dropdown.style.position = 'absolute';
        dropdown.style.top = `${rect.bottom - containerRect.top + 4}px`;
        dropdown.style.left = `${rect.left - containerRect.left}px`;

        const searchable = FilterBar.SEARCHABLE.has(filterKey);
        let searchHtml = '';
        if (searchable) {
            searchHtml = `
                <div class="filter-dropdown-search">
                    <input type="text" class="form-input filter-dropdown-search-input" placeholder="Search ${f.label.toLowerCase()}..." style="width:100%;font-size:12px;padding:4px 8px;">
                </div>`;
        }

        const optionsHtml = this._renderOptions(filterKey, f.options);

        dropdown.innerHTML = `
            ${searchHtml}
            <div class="filter-dropdown-options">${optionsHtml}</div>
            <div class="filter-dropdown-footer">
                <button class="filter-dropdown-reset-btn" ${!this.hasActiveFilters() && f.values.size === 0 ? 'disabled' : ''}>Reset</button>
            </div>
        `;

        this._container.style.position = 'relative';
        this._container.appendChild(dropdown);
        this._dropdownEl = dropdown;

        // Bind search
        if (searchable) {
            const input = dropdown.querySelector('.filter-dropdown-search-input');
            if (input) {
                input.addEventListener('input', () => {
                    const search = input.value.toLowerCase();
                    const filtered = f.options.filter(o => o.label.toLowerCase().includes(search) || o.key.toLowerCase().includes(search));
                    const optsContainer = dropdown.querySelector('.filter-dropdown-options');
                    optsContainer.innerHTML = this._renderOptions(filterKey, filtered);
                    this._bindOptionEvents(dropdown, filterKey);
                });
                input.focus();
            }
        }

        // Bind option clicks
        this._bindOptionEvents(dropdown, filterKey);

        // Bind reset
        const resetBtn = dropdown.querySelector('.filter-dropdown-reset-btn');
        resetBtn.addEventListener('click', () => {
            f.values.clear();
            this._persist();
            this._closeDropdown();
            this._renderButtons();
            this._notifyChange();
        });
    }

    _renderOptions(filterKey, options) {
        return options.map(o => {
            const checked = this.filters[filterKey].values.has(o.key);
            const count = this._counts[filterKey]?.[o.key] || 0;
            const colorDot = o.color ? `<span class="filter-option-dot" style="background:${o.color};"></span>` : '';
            return `
                <label class="filter-option${checked ? ' checked' : ''}" data-key="${this._esc(o.key)}">
                    <span class="filter-option-check">${checked ? '&#10003;' : ''}</span>
                    ${colorDot}
                    <span class="filter-option-label">${this._esc(o.label)}</span>
                    <span class="filter-option-count">${count}</span>
                </label>`;
        }).join('');
    }

    _bindOptionEvents(dropdown, filterKey) {
        dropdown.querySelectorAll('.filter-option').forEach(label => {
            label.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const key = label.dataset.key;
                const values = this.filters[filterKey].values;
                if (values.has(key)) {
                    values.delete(key);
                } else {
                    values.add(key);
                }
                this._persist();

                // Re-render just the options and button
                const optsContainer = dropdown.querySelector('.filter-dropdown-options');
                optsContainer.innerHTML = this._renderOptions(filterKey, this.filters[filterKey].options);
                this._bindOptionEvents(dropdown, filterKey);
                this._renderButtons();
                this._notifyChange();

                // Re-open the same dropdown
                const btn = this._container.querySelector(`[data-filter-key="${filterKey}"]`);
                if (btn && this._openDropdown === filterKey) {
                    this._closeDropdown();
                    this._openDropdown = filterKey;
                    this._renderDropdown(filterKey, btn);
                }
            });
        });
    }

    _notifyChange() {
        // Trigger re-render in the panel
        if (this.panel) {
            this.panel._renderKanban();
            if (this.panel._viewMode === 'list' && this.panel._listView) {
                this.panel._listView.updateTasks(this.panel._getFilteredTasks());
            }
        }
    }

    _persist() {
        try {
            const data = {};
            for (const [key, f] of Object.entries(this.filters)) {
                if (f.values.size > 0) {
                    data[key] = Array.from(f.values);
                }
            }
            localStorage.setItem('nexus-filterbar', JSON.stringify(data));
        } catch {}
    }

    _loadPersisted() {
        try {
            const raw = localStorage.getItem('nexus-filterbar');
            if (!raw) return;
            const data = JSON.parse(raw);
            for (const [key, arr] of Object.entries(data)) {
                if (this.filters[key] && Array.isArray(arr)) {
                    this.filters[key].values = new Set(arr);
                }
            }
        } catch {}
    }

    _esc(str) {
        const d = document.createElement('div');
        d.textContent = str || '';
        return d.innerHTML;
    }
}

window.FilterBar = FilterBar;
