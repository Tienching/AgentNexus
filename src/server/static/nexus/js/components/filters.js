/**
 * FilterPanel - Advanced multi-dimensional filtering system for the task board.
 *
 * Features:
 * - Status / Priority / Assignee multi-select filters
 * - Real-time option counts (e.g. "In Progress (5)")
 * - Search to narrow filter options
 * - Reset all button
 * - Integrates with AppDataStore for data
 *
 * Usage:
 *   const fp = new FilterPanel({ container, onFilterChange, getStatusColumns });
 *   fp.render();
 *   fp.updateCounts(tasks);
 */
class FilterPanel {
    constructor(options = {}) {
        this.container = options.container;
        this.onFilterChange = options.onFilterChange || (() => {});
        this.getStatusColumns = options.getStatusColumns || (() => []);
        this._filters = {
            status: new Set(),
            priority: new Set(),
            assignee: new Set(),
        };
        this._search = '';
        this._counts = { status: {}, priority: {}, assignee: {} };
        this._expanded = { status: true, priority: false, assignee: false };
        this._allAssignees = [];
    }

    get filters() {
        return {
            status: new Set(this._filters.status),
            priority: new Set(this._filters.priority),
            assignee: new Set(this._filters.assignee),
        };
    }

    get hasActiveFilters() {
        return this._filters.status.size > 0 ||
               this._filters.priority.size > 0 ||
               this._filters.assignee.size > 0;
    }

    /**
     * Apply filters to a task list.
     * @param {Array} tasks
     * @returns {Array} filtered tasks
     */
    apply(tasks) {
        return tasks.filter(t => {
            if (this._filters.status.size > 0 && !this._filters.status.has(t.status)) return false;
            if (this._filters.priority.size > 0 && !this._filters.priority.has(t.priority || 'normal')) return false;
            if (this._filters.assignee.size > 0) {
                const assignee = t.assigned_to || t.alias || '';
                if (!this._filters.assignee.has(assignee)) return false;
            }
            return true;
        });
    }

    /**
     * Update option counts from current task list.
     * @param {Array} tasks - full (unfiltered) task list
     */
    updateCounts(tasks) {
        this._counts = { status: {}, priority: {}, assignee: {} };
        const assigneeSet = new Set();
        tasks.forEach(t => {
            const s = t.status || 'inbox';
            this._counts.status[s] = (this._counts.status[s] || 0) + 1;
            const p = t.priority || 'normal';
            this._counts.priority[p] = (this._counts.priority[p] || 0) + 1;
            const a = t.assigned_to || t.alias || '';
            if (a) {
                assigneeSet.add(a);
                this._counts.assignee[a] = (this._counts.assignee[a] || 0) + 1;
            }
        });
        this._allAssignees = Array.from(assigneeSet).sort();
        this._updateCountLabels();
    }

    reset() {
        this._filters.status.clear();
        this._filters.priority.clear();
        this._filters.assignee.clear();
        this._search = '';
        this.render();
        this.onFilterChange(this.filters);
    }

    render() {
        if (!this.container) return;
        const statusCols = this.getStatusColumns();
        const priorities = [
            { key: 'critical', label: 'Critical', color: 'var(--error)' },
            { key: 'serious', label: 'Serious', color: 'var(--warning)' },
            { key: 'normal', label: 'Normal', color: 'var(--primary-500)' },
        ];

        this.container.innerHTML = `
            <div class="filter-panel">
                <div class="filter-panel-header">
                    <span class="filter-panel-title">Filters</span>
                    <button class="action-btn filter-reset-btn" data-action="filter-reset" style="font-size:11px;padding:2px 8px;${this.hasActiveFilters ? '' : 'display:none;'}">Reset</button>
                </div>
                <div class="filter-search">
                    <input type="text" class="form-input filter-search-input" placeholder="Search filters..." value="${this._esc(this._search)}" style="font-size:12px;padding:4px 8px;">
                </div>
                <div class="filter-sections">
                    ${this._renderSection('status', 'Status', statusCols.map(c => ({
                        key: c.key,
                        label: c.title,
                        color: c.color,
                    })))}
                    ${this._renderSection('priority', 'Priority', priorities)}
                    ${this._renderSection('assignee', 'Assignee', this._allAssignees.map(a => ({
                        key: a,
                        label: a,
                        color: null,
                    })))}
                </div>
            </div>
        `;

        this._bindEvents();
    }

    _renderSection(dimension, title, options) {
        const isExpanded = this._expanded[dimension];
        const search = this._search.toLowerCase();
        const filtered = search
            ? options.filter(o => o.label.toLowerCase().includes(search) || o.key.toLowerCase().includes(search))
            : options;
        const activeCount = this._filters[dimension].size;

        return `
            <div class="filter-section" data-dimension="${dimension}">
                <div class="filter-section-header" data-action="toggle-section" data-dimension="${dimension}">
                    <span class="filter-section-title">${title}${activeCount > 0 ? ` <span class="filter-active-count">(${activeCount})</span>` : ''}</span>
                    <svg class="filter-section-chevron ${isExpanded ? 'expanded' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:14px;height:14px;transition:transform 0.2s;">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </div>
                <div class="filter-section-body" style="${isExpanded ? '' : 'display:none;'}">
                    ${filtered.length === 0 ? '<div style="font-size:11px;color:var(--text-muted);padding:4px 0;">No matches</div>' :
                    filtered.map(o => {
                        const checked = this._filters[dimension].has(o.key);
                        const count = this._counts[dimension]?.[o.key] || 0;
                        return `
                            <label class="filter-option ${checked ? 'active' : ''}" data-dimension="${dimension}" data-value="${this._esc(o.key)}">
                                <input type="checkbox" ${checked ? 'checked' : ''} style="display:none;">
                                <span class="filter-option-check">${checked ? '&#10003;' : ''}</span>
                                ${o.color ? `<span class="filter-option-dot" style="background:${o.color};"></span>` : ''}
                                <span class="filter-option-label">${this._esc(o.label)}</span>
                                <span class="filter-option-count" data-count-key="${dimension}-${this._esc(o.key)}">${count}</span>
                            </label>
                        `;
                    }).join('')}
                </div>
            </div>
        `;
    }

    _bindEvents() {
        if (!this.container) return;

        // Reset button
        this.container.querySelector('[data-action="filter-reset"]')?.addEventListener('click', () => this.reset());

        // Search input
        const searchInput = this.container.querySelector('.filter-search-input');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this._search = e.target.value;
                this.render();
            });
        }

        // Section toggles
        this.container.querySelectorAll('[data-action="toggle-section"]').forEach(header => {
            header.addEventListener('click', () => {
                const dim = header.dataset.dimension;
                this._expanded[dim] = !this._expanded[dim];
                this.render();
            });
        });

        // Filter option clicks
        this.container.querySelectorAll('.filter-option').forEach(label => {
            label.addEventListener('click', (e) => {
                e.preventDefault();
                const dim = label.dataset.dimension;
                const val = label.dataset.value;
                if (this._filters[dim].has(val)) {
                    this._filters[dim].delete(val);
                } else {
                    this._filters[dim].add(val);
                }
                this.render();
                this.onFilterChange(this.filters);
            });
        });
    }

    _updateCountLabels() {
        if (!this.container) return;
        for (const [dim, counts] of Object.entries(this._counts)) {
            for (const [key, count] of Object.entries(counts)) {
                const el = this.container.querySelector(`[data-count-key="${dim}-${key}"]`);
                if (el) el.textContent = count;
            }
        }
        // Show/hide reset button
        const resetBtn = this.container.querySelector('[data-action="filter-reset"]');
        if (resetBtn) resetBtn.style.display = this.hasActiveFilters ? '' : 'none';
    }

    _esc(str) {
        const d = document.createElement('div');
        d.textContent = str || '';
        return d.innerHTML;
    }
}

window.FilterPanel = FilterPanel;
