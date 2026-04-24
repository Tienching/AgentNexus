/**
 * InlinePicker - Card-level inline edit popover for status/priority/assignee/due_date/labels.
 *
 * Features:
 * - Click on a property badge -> small floating picker appears
 * - event.stopPropagation() to protect drag and card-click logic
 * - Supports status, priority, assignee, due_date, and labels fields
 * - Keyboard accessible (Escape to close)
 * - Unified popover positioning via _showPicker / _position
 *
 * Usage:
 *   InlinePicker.attachAll(root, {
 *       getStatusColumns: () => [...],
 *       getAssigneeOptions: () => [...],
 *       getAllLabels: () => [...],
 *       onSelect: async (taskId, field, newValue) => { ... },
 *   });
 */
class InlinePicker {
    static _activeInstance = null;

    /**
     * Attach an inline picker trigger to a card element.
     * Finds elements with [data-inline-edit] and binds click handlers.
     */
    static attachAll(root, options = {}) {
        root.querySelectorAll('[data-inline-edit]').forEach(trigger => {
            if (trigger.dataset.inlinePickerBound === '1') return;
            trigger.dataset.inlinePickerBound = '1';
            trigger.addEventListener('click', (e) => {
                e.stopPropagation();
                e.preventDefault();
                const field = trigger.dataset.inlineEdit;
                const taskId = trigger.closest('.task-card')?.dataset.taskId;
                if (!taskId || !field) return;
                InlinePicker.show(trigger, {
                    taskId,
                    field,
                    currentValue: trigger.dataset.currentValue || '',
                    currentLabels: trigger.dataset.currentLabels
                        ? trigger.dataset.currentLabels.split(',').filter(Boolean)
                        : [],
                    ...options,
                });
            });
        });
    }

    /**
     * Show the picker popover anchored to a trigger element.
     */
    static show(anchor, config) {
        InlinePicker.dismiss();

        const picker = new InlinePicker(anchor, config);
        InlinePicker._activeInstance = picker;
        picker.render();
    }

    /**
     * Dismiss the currently active picker.
     */
    static dismiss() {
        if (InlinePicker._activeInstance) {
            InlinePicker._activeInstance.destroy();
            InlinePicker._activeInstance = null;
        }
    }

    constructor(anchor, config) {
        this.anchor = anchor;
        this.taskId = config.taskId;
        this.field = config.field;
        this.currentValue = config.currentValue;
        this.currentLabels = config.currentLabels || [];
        this.onSelect = config.onSelect || (async () => {});
        this.getStatusColumns = config.getStatusColumns || (() => []);
        this.getPriorityOptions = config.getPriorityOptions || (() => [
            { key: 'project', label: 'Project', color: 'var(--error)' },
            { key: 'serious', label: 'Serious', color: 'var(--warning)' },
            { key: 'thought', label: 'Thought', color: 'var(--primary-500)' },
            { key: 'generated', label: 'Generated', color: '#9ca3af' },
        ]);
        this.getAssigneeOptions = config.getAssigneeOptions || (() => []);
        this.getAllLabels = config.getAllLabels || (() => []);
        this.el = null;
        this._onKeydown = this._handleKeydown.bind(this);
        this._onClickOutside = this._handleClickOutside.bind(this);
    }

    render() {
        // Dispatch to specialized renderers for new fields
        if (this.field === 'due_date') {
            this._renderDueDatePicker();
            return;
        }
        if (this.field === 'labels') {
            this._renderLabelPicker();
            return;
        }

        // Original option-list renderer for status/priority/assignee
        const options = this._getOptions();
        const el = document.createElement('div');
        el.className = 'inline-picker-popover';

        // Search for assignee
        if (this.field === 'assignee') {
            const searchInput = document.createElement('input');
            searchInput.type = 'text';
            searchInput.placeholder = 'Search...';
            searchInput.className = 'form-input inline-picker-search';
            el.appendChild(searchInput);
            searchInput.addEventListener('input', () => {
                const q = searchInput.value.toLowerCase();
                el.querySelectorAll('.inline-picker-option').forEach(opt => {
                    const label = opt.dataset.label?.toLowerCase() || '';
                    opt.classList.toggle('is-hidden', !label.includes(q));
                });
            });
            requestAnimationFrame(() => searchInput.focus());
        }

        options.forEach(opt => {
            const item = document.createElement('div');
            item.className = `inline-picker-option ${opt.key === this.currentValue ? 'active' : ''}`;
            item.dataset.value = opt.key;
            item.dataset.label = opt.label;

            if (opt.color) {
                const dot = document.createElement('span');
                dot.className = `inline-picker-dot ${this._getToneClass(this.field, opt.key)}`.trim();
                item.appendChild(dot);
            }

            const label = document.createElement('span');
            label.className = 'inline-picker-option-label';
            label.textContent = opt.label;
            item.appendChild(label);

            if (opt.key === this.currentValue) {
                const check = document.createElement('span');
                check.className = 'inline-picker-option-check';
                check.textContent = '\u2713';
                item.appendChild(check);
            }

            item.addEventListener('click', (e) => {
                e.stopPropagation();
                this._selectValue(opt.key);
            });
            el.appendChild(item);
        });

        this._showPicker(el);
    }

    // ------------------------------------------------------------------
    // DueDatePicker
    // ------------------------------------------------------------------

    _renderDueDatePicker() {
        const el = document.createElement('div');
        el.className = 'inline-picker-popover due-date-picker';

        // Header
        const header = document.createElement('div');
        header.textContent = 'Due Date';
        header.className = 'inline-picker-header';
        el.appendChild(header);

        // Date input
        const input = document.createElement('input');
        input.type = 'date';
        input.className = 'due-date-input';
        if (this.currentValue) {
            input.value = this._toDateInputValue(this.currentValue);
        }
        el.appendChild(input);

        // Footer buttons
        const footer = document.createElement('div');
        footer.className = 'inline-picker-footer';

        const clearBtn = document.createElement('button');
        clearBtn.textContent = 'Clear';
        clearBtn.className = 'picker-btn picker-clear-btn';
        clearBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this._selectValue(null);
        });
        footer.appendChild(clearBtn);

        const applyBtn = document.createElement('button');
        applyBtn.textContent = 'Apply';
        applyBtn.className = 'picker-btn picker-apply-btn';
        applyBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this._selectValue(input.value || null);
        });
        footer.appendChild(applyBtn);

        el.appendChild(footer);
        this._showPicker(el);
        requestAnimationFrame(() => input.focus());
    }

    _toDateInputValue(rawValue) {
        const value = String(rawValue || '').trim();
        if (!value) return '';
        if (/^-?\d+(\.\d+)?$/.test(value)) {
            const numeric = Number(value);
            const millis = numeric < 1e12 ? numeric * 1000 : numeric;
            const date = new Date(millis);
            return Number.isNaN(date.getTime()) ? '' : date.toISOString().slice(0, 10);
        }
        return value.length > 10 ? value.slice(0, 10) : value;
    }

    // ------------------------------------------------------------------
    // LabelPicker (multi-select)
    // ------------------------------------------------------------------

    _renderLabelPicker() {
        const allLabels = this.getAllLabels();
        const selected = new Set(this.currentLabels);

        const el = document.createElement('div');
        el.className = 'inline-picker-popover label-picker';

        // Header
        const header = document.createElement('div');
        header.textContent = 'Labels';
        header.className = 'inline-picker-header';
        el.appendChild(header);

        // Search input
        const searchInput = document.createElement('input');
        searchInput.type = 'text';
        searchInput.className = 'picker-search';
        searchInput.placeholder = 'Search labels...';
        el.appendChild(searchInput);

        // Options list
        const optionsContainer = document.createElement('div');
        optionsContainer.className = 'picker-options';

        const optionEls = [];
        allLabels.forEach(label => {
            const item = document.createElement('div');
            item.className = `picker-option ${selected.has(label) ? 'checked' : ''}`;
            item.dataset.label = label;

            const checkbox = document.createElement('span');
            checkbox.className = 'picker-checkbox';
            checkbox.textContent = selected.has(label) ? '\u2611' : '\u2610';
            item.appendChild(checkbox);

            const text = document.createElement('span');
            text.className = 'picker-option-text';
            text.textContent = label;
            item.appendChild(text);

            item.addEventListener('click', (e) => {
                e.stopPropagation();
                if (selected.has(label)) {
                    selected.delete(label);
                    checkbox.textContent = '\u2610';
                    item.classList.remove('checked');
                } else {
                    selected.add(label);
                    checkbox.textContent = '\u2611';
                    item.classList.add('checked');
                }
            });
            optionsContainer.appendChild(item);
            optionEls.push({ el: item, label });
        });
        el.appendChild(optionsContainer);

        // Search filter
        searchInput.addEventListener('input', () => {
            const q = searchInput.value.toLowerCase();
            optionEls.forEach(({ el, label }) => {
                el.classList.toggle('is-hidden', !label.toLowerCase().includes(q));
            });
        });

        // Footer
        const footer = document.createElement('div');
        footer.className = 'inline-picker-footer';

        const applyBtn = document.createElement('button');
        applyBtn.textContent = 'Apply';
        applyBtn.className = 'picker-btn picker-apply-btn';
        applyBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this._selectValue(Array.from(selected));
        });
        footer.appendChild(applyBtn);

        el.appendChild(footer);
        this._showPicker(el);
        requestAnimationFrame(() => searchInput.focus());
    }

    // ------------------------------------------------------------------
    // Unified popover helpers
    // ------------------------------------------------------------------

    _showPicker(el) {
        this.el = el;
        this.anchor.classList.add('inline-picker-anchor');
        this.anchor.appendChild(el);

        document.addEventListener('keydown', this._onKeydown, true);
        setTimeout(() => document.addEventListener('click', this._onClickOutside, true), 0);
    }

    _getToneClass(field, key) {
        const normalizedField = String(field || '').toLowerCase();
        const normalizedKey = String(key || '').toLowerCase().replace(/[^a-z0-9_-]+/g, '-');
        if (!normalizedField || !normalizedKey) return '';
        return `inline-picker-dot--${normalizedField}-${normalizedKey}`;
    }

    _getOptions() {
        switch (this.field) {
            case 'status': return this.getStatusColumns();
            case 'priority': return this.getPriorityOptions();
            case 'assignee': return this.getAssigneeOptions();
            default: return [];
        }
    }

    async _selectValue(value) {
        // For single-select fields, skip if unchanged
        if (this.field !== 'labels' && value === this.currentValue) {
            InlinePicker.dismiss();
            return;
        }
        try {
            await this.onSelect(this.taskId, this.field, value);
        } catch (e) {
            console.error('[InlinePicker] select error:', e);
        }
        InlinePicker.dismiss();
    }

    _handleKeydown(e) {
        if (e.key === 'Escape') {
            e.stopPropagation();
            InlinePicker.dismiss();
        }
    }

    _handleClickOutside(e) {
        if (this.el && !this.el.contains(e.target) && !this.anchor.contains(e.target)) {
            InlinePicker.dismiss();
        }
    }

    destroy() {
        document.removeEventListener('keydown', this._onKeydown, true);
        document.removeEventListener('click', this._onClickOutside, true);
        if (this.el) {
            this.el.remove();
            this.el = null;
        }
    }
}

window.InlinePicker = InlinePicker;
