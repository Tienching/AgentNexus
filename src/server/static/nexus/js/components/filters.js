/**
 * FilterBar - Toolbar dropdown filter system for the task board.
 *
 * Features:
 * - 3 dimensions: Status, Priority, Assignee
 * - SortButton: Sort field + direction dropdown
 * - ProjectButton: Project filter dropdown
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
        };
        this._counts = { status: {}, priority: {}, assignee: {} };
        this._openDropdown = null;
        this._dropdownEl = null;
        this._container = null;
        this._sortBtn = null;
        this._projectBtn = null;
        this._loadPersisted();
    }

    /** Static option definitions */
    static STATUS_OPTIONS = [
        { key: 'pending',   label: 'To Do',     color: 'var(--status-pending)' },
        { key: 'running',   label: 'Doing',     color: 'var(--status-running)' },
        { key: 'in_review', label: 'In Review', color: 'var(--status-in-review)' },
        { key: 'completed', label: 'Done',      color: 'var(--status-completed)' },
        { key: 'failed',    label: 'Failed',    color: 'var(--status-failed)' },
        { key: 'cancelled', label: 'Cancelled', color: 'var(--status-cancelled)' },
        { key: 'archived',  label: 'Archived',  color: 'var(--status-archived)' },
    ];

    /** Normalize legacy status values to the new 7-status model */
    static STATUS_MAP = {
        // Old 10-status model → new 7-status model
        'inbox':          'pending',
        'assigned':       'pending',
        'awaiting_owner': 'pending',
        'todo':           'pending',
        'doing':          'running',
        'in_progress':    'running',
        'running':        'running',  // pass-through
        'review':         'in_review',
        'quality_review': 'in_review',
        'in_review':      'in_review',  // pass-through
        'done':           'completed',
        'completed':      'completed',  // pass-through
        'orphaned':       'pending',
    };

    static KNOWN_STATUS_KEYS = new Set(FilterBar.STATUS_OPTIONS.map(option => option.key));

    static _normalizeStatus(status) {
        const s = String(status || '').trim().toLowerCase();
        const normalized = FilterBar.STATUS_MAP[s] || s;
        return FilterBar.KNOWN_STATUS_KEYS.has(normalized) ? normalized : 'pending';
    }

    static PRIORITY_OPTIONS = [
        { key: 'project', label: 'Project', color: 'var(--error, #ef4444)' },
        { key: 'serious', label: 'Serious', color: 'var(--warning, #f59e0b)' },
        { key: 'thought', label: 'Thought', color: 'var(--primary-500)' },
        { key: 'generated', label: 'Generated', color: 'var(--text-muted)' },
    ];

    static KNOWN_PRIORITY_KEYS = new Set(FilterBar.PRIORITY_OPTIONS.map(option => option.key));

    static _normalizePriority(priority) {
        const normalized = String(priority || '').trim().toLowerCase();
        return FilterBar.KNOWN_PRIORITY_KEYS.has(normalized) ? normalized : 'thought';
    }

    static _getDueDateDate(rawDueDate) {
        if (!rawDueDate) return null;
        if (rawDueDate instanceof Date) return Number.isNaN(rawDueDate.getTime()) ? null : rawDueDate;
        if (typeof rawDueDate === 'number') {
            const millis = rawDueDate < 1e12 ? rawDueDate * 1000 : rawDueDate;
            const date = new Date(millis);
            return Number.isNaN(date.getTime()) ? null : date;
        }
        const value = String(rawDueDate).trim();
        if (!value) return null;
        if (/^-?\d+(\.\d+)?$/.test(value)) {
            const numeric = Number(value);
            const millis = numeric < 1e12 ? numeric * 1000 : numeric;
            const date = new Date(millis);
            return Number.isNaN(date.getTime()) ? null : date;
        }
        const parsed = new Date(value);
        return Number.isNaN(parsed.getTime()) ? null : parsed;
    }

    static DUE_DATE_OPTIONS = [
        { key: 'overdue', label: 'Overdue' },
        { key: 'today', label: 'Today' },
        { key: 'this_week', label: 'This week' },
        { key: 'no_due_date', label: 'No due date' },
    ];

    static SORT_OPTIONS = [
        { key: 'position', label: 'Position' },
        { key: 'priority', label: 'Priority' },
        { key: 'due_date', label: 'Due Date' },
        { key: 'created_at', label: 'Created Date' },
    ];

    /** Dimensions that support search in dropdown */
    static SEARCHABLE = new Set(['assignee']);

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
        this._counts = { status: {}, priority: {}, assignee: {} };
        const assigneeSet = new Set();

        tasks.forEach(t => {
            // Status
            const s = FilterBar._normalizeStatus(t.status);
            this._counts.status[s] = (this._counts.status[s] || 0) + 1;

            // Priority
            const p = FilterBar._normalizePriority(t.priority);
            this._counts.priority[p] = (this._counts.priority[p] || 0) + 1;

            // Assignee
            const a = t.assigned_to || t.alias || '';
            if (a) {
                assigneeSet.add(a);
                this._counts.assignee[a] = (this._counts.assignee[a] || 0) + 1;
            }
            this._counts.assignee['__none__'] = (this._counts.assignee['__none__'] || 0) + (a ? 0 : 1);
        });

        // Set static options
        this.filters.status.options = FilterBar.STATUS_OPTIONS;
        this.filters.priority.options = FilterBar.PRIORITY_OPTIONS;

        // Set dynamic options
        this.filters.assignee.options = [
            { key: '__none__', label: 'No assignee' },
            ...Array.from(assigneeSet).sort().map(a => ({ key: a, label: a })),
        ];

        this._renderButtons();
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
                if (!this.filters.priority.values.has(FilterBar._normalizePriority(t.priority))) return false;
            }

            // Assignee
            if (this.filters.assignee.values.size > 0) {
                const a = t.assigned_to || t.alias || '';
                const key = a || '__none__';
                if (!this.filters.assignee.values.has(key)) return false;
            }

            return true;
        });
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
        const keys = ['status', 'priority', 'assignee'];
        keys.forEach(key => {
            const f = this.filters[key];
            const activeCount = f.values.size;
            const wrap = document.createElement('div');
            wrap.className = 'filter-btn-wrap';
            const btn = document.createElement('button');
            btn.className = `filter-btn${activeCount > 0 ? ' has-filter' : ''}`;
            btn.dataset.filterKey = key;
            btn.innerHTML = `${this._esc(f.label)}${activeCount > 0 ? ` <span class="filter-btn-count">(${activeCount})</span>` : ''} <span class="filter-btn-arrow">&#9662;</span>`;

            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this._toggleDropdown(key, btn);
            });

            wrap.appendChild(btn);
            this._container.appendChild(wrap);
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

        const searchable = FilterBar.SEARCHABLE.has(filterKey);
        let searchHtml = '';
        if (searchable) {
            searchHtml = `
                <div class="filter-dropdown-search">
                    <input type="text" class="form-input filter-dropdown-search-input" placeholder="Search ${f.label.toLowerCase()}...">
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

        (anchorEl.parentElement || this._container).appendChild(dropdown);
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
            const toneClass = o.color ? this._dotToneClass(filterKey, o.key) : '';
            const colorDot = o.color ? `<span class="filter-option-dot ${toneClass}"></span>` : '';
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
            let removedHiddenFilters = false;
            for (const [key, arr] of Object.entries(data)) {
                if (this.filters[key] && Array.isArray(arr)) {
                    const values = key === 'status'
                        ? arr.map(v => FilterBar._normalizeStatus(v))
                        : arr;
                    this.filters[key].values = new Set(values);
                } else if (key === 'creator' || key === 'dueDate') {
                    removedHiddenFilters = true;
                }
            }
            if (removedHiddenFilters) this._persist();
        } catch {}
    }

    _esc(str) {
        const d = document.createElement('div');
        d.textContent = str || '';
        return d.innerHTML;
    }

    _dotToneClass(filterKey, optionKey) {
        const safeKey = String(optionKey || '').toLowerCase().replace(/[^a-z0-9_-]+/g, '-');
        return `filter-option-dot--${filterKey}-${safeKey}`;
    }
}

// =====================================================================
// SortButton - Dropdown button for sort field and direction
// =====================================================================

class SortButton {
    constructor(taskBoardPanel) {
        this.panel = taskBoardPanel;
        this._btnEl = null;
        this._dropdownEl = null;
        this._open = false;

        this._sortField = this.panel._sortField || 'position';
        this._sortDirection = this.panel._sortDirection || 'asc';

        // Close on outside click
        document.addEventListener('click', (e) => {
            if (this._dropdownEl && !this._dropdownEl.contains(e.target) &&
                this._btnEl && !this._btnEl.contains(e.target)) {
                this._close();
            }
        });
    }

    _fieldLabel(key) {
        const opt = FilterBar.SORT_OPTIONS.find(o => o.key === key);
        return opt ? opt.label : key;
    }

    render(container) {
        const wrap = document.createElement('div');
        wrap.className = 'toolbar-btn-wrap';
        const btn = document.createElement('button');
        btn.className = 'toolbar-btn';
        btn.innerHTML = `Sort: ${this._esc(this._fieldLabel(this._sortField))} <span class="filter-btn-arrow">&#9662;</span>`;
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            this._toggle();
        });
        wrap.appendChild(btn);
        container.appendChild(wrap);
        this._btnEl = btn;
    }

    _toggle() {
        if (this._open) {
            this._close();
        } else {
            this._openDropdown();
        }
    }

    _openDropdown() {
        this._close();
        this._open = true;

        const dropdown = document.createElement('div');
        dropdown.className = 'filter-dropdown';

        // Sort field options
        const fieldsHtml = FilterBar.SORT_OPTIONS.map(o => {
            const active = o.key === this._sortField;
            return `<div class="filter-option${active ? ' checked' : ''}" data-sort-field="${this._esc(o.key)}">
                <span class="filter-option-check">${active ? '&#10003;' : ''}</span>
                <span class="filter-option-label">${this._esc(o.label)}</span>
            </div>`;
        }).join('');

        // Direction toggle
        const ascActive = this._sortDirection === 'asc';
        const descActive = this._sortDirection === 'desc';
        const dirHtml = `
            <div class="filter-dropdown-separator"></div>
            <div class="filter-option${ascActive ? ' checked' : ''}" data-sort-dir="asc">
                <span class="filter-option-check">${ascActive ? '&#10003;' : ''}</span>
                <span class="filter-option-label">Ascending</span>
            </div>
            <div class="filter-option${descActive ? ' checked' : ''}" data-sort-dir="desc">
                <span class="filter-option-check">${descActive ? '&#10003;' : ''}</span>
                <span class="filter-option-label">Descending</span>
            </div>`;

        dropdown.innerHTML = `
            <div class="filter-dropdown-options">${fieldsHtml}${dirHtml}</div>`;

        this._btnEl.parentElement.appendChild(dropdown);
        this._dropdownEl = dropdown;

        // Bind field clicks
        dropdown.querySelectorAll('[data-sort-field]').forEach(el => {
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                const field = el.dataset.sortField;
                this._sortField = field;
                this.panel._sortField = field;
                localStorage.setItem('nexus-kanban-sortField', field);
                this._updateBtnLabel();
                this._close();
                this.panel._renderKanban();
            });
        });

        // Bind direction clicks
        dropdown.querySelectorAll('[data-sort-dir]').forEach(el => {
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                const dir = el.dataset.sortDir;
                this._sortDirection = dir;
                this.panel._sortDirection = dir;
                localStorage.setItem('nexus-kanban-sortDir', dir);
                this._updateBtnLabel();
                this._close();
                this.panel._renderKanban();
            });
        });
    }

    _close() {
        if (this._dropdownEl) {
            this._dropdownEl.remove();
            this._dropdownEl = null;
        }
        this._open = false;
    }

    _updateBtnLabel() {
        if (this._btnEl) {
            this._btnEl.innerHTML = `Sort: ${this._esc(this._fieldLabel(this._sortField))} <span class="filter-btn-arrow">&#9662;</span>`;
        }
    }

    _esc(str) {
        const d = document.createElement('div');
        d.textContent = str || '';
        return d.innerHTML;
    }
}

// =====================================================================
// ProjectButton - Dropdown button for project filter
// =====================================================================

class ProjectButton {
    constructor(taskBoardPanel) {
        this.panel = taskBoardPanel;
        this._btnEl = null;
        this._dropdownEl = null;
        this._open = false;
        this._selectedProjectId = '';
        this._projects = [];

        // Close on outside click
        document.addEventListener('click', (e) => {
            if (this._dropdownEl && !this._dropdownEl.contains(e.target) &&
                this._btnEl && !this._btnEl.contains(e.target)) {
                this._close();
            }
        });
    }

    setProjects(projects) {
        this._projects = projects || [];
    }

    setSelectedProject(projectId) {
        this._selectedProjectId = projectId || '';
        this._updateBtnLabel();
    }

    render(container) {
        const wrap = document.createElement('div');
        wrap.className = 'toolbar-btn-wrap';
        const btn = document.createElement('button');
        btn.className = 'toolbar-btn';
        btn.innerHTML = `Project: All <span class="filter-btn-arrow">&#9662;</span>`;
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            this._toggle();
        });
        wrap.appendChild(btn);
        container.appendChild(wrap);
        this._btnEl = btn;
    }

    _toggle() {
        if (this._open) {
            this._close();
        } else {
            this._openDropdown();
        }
    }

    _openDropdown() {
        this._close();
        this._open = true;

        const dropdown = document.createElement('div');
        dropdown.className = 'filter-dropdown';

        // "All Projects" option
        const allActive = !this._selectedProjectId;
        let html = `<div class="filter-option${allActive ? ' checked' : ''}" data-project-id="">
            <span class="filter-option-check">${allActive ? '&#10003;' : ''}</span>
            <span class="filter-option-label">All Projects</span>
        </div>`;

        // Separator + project list
        if (this._projects.length > 0) {
            html += '<div class="filter-dropdown-separator"></div>';
            html += this._projects.map(p => {
                const label = p.project_name || p.project_id;
                const active = p.project_id === this._selectedProjectId;
                const count = (p.todo || 0) + (p.doing || 0);
                return `<div class="filter-option${active ? ' checked' : ''}" data-project-id="${this._esc(p.project_id)}">
                    <span class="filter-option-check">${active ? '&#10003;' : ''}</span>
                    <span class="filter-option-label">${this._esc(label)}</span>
                    <span class="filter-option-count">${count > 0 ? count : ''}</span>
                </div>`;
            }).join('');
        }

        dropdown.innerHTML = `<div class="filter-dropdown-options">${html}</div>`;

        this._btnEl.parentElement.appendChild(dropdown);
        this._dropdownEl = dropdown;

        // Bind project clicks
        dropdown.querySelectorAll('[data-project-id]').forEach(el => {
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                const projectId = el.dataset.projectId;
                this._selectedProjectId = projectId;
                this._updateBtnLabel();
                this._close();
                // Call panel's project filter method
                this.panel._setProjectFilter(projectId);
            });
        });
    }

    _close() {
        if (this._dropdownEl) {
            this._dropdownEl.remove();
            this._dropdownEl = null;
        }
        this._open = false;
    }

    _updateBtnLabel() {
        if (this._btnEl) {
            const label = this._selectedProjectId
                ? this._projects.find(p => p.project_id === this._selectedProjectId)?.project_name || this._selectedProjectId
                : 'All';
            this._btnEl.innerHTML = `Project: ${this._esc(label)} <span class="filter-btn-arrow">&#9662;</span>`;
            // Highlight when a project is selected
            this._btnEl.classList.toggle('has-filter', !!this._selectedProjectId);
        }
    }

    _esc(str) {
        const d = document.createElement('div');
        d.textContent = str || '';
        return d.innerHTML;
    }
}

window.FilterBar = FilterBar;
window.SortButton = SortButton;
window.ProjectButton = ProjectButton;
