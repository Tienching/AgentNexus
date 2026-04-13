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
            { key: 'critical', label: 'Critical', color: 'var(--error)' },
            { key: 'serious', label: 'Serious', color: 'var(--warning)' },
            { key: 'normal', label: 'Normal', color: 'var(--primary-500)' },
            { key: 'low', label: 'Low', color: '#9ca3af' },
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
        this._applyBaseStyles(el);

        // Search for assignee
        if (this.field === 'assignee') {
            const searchInput = document.createElement('input');
            searchInput.type = 'text';
            searchInput.placeholder = 'Search...';
            searchInput.className = 'form-input';
            searchInput.style.cssText = 'font-size:12px;padding:4px 8px;margin:4px;width:calc(100% - 8px);';
            el.appendChild(searchInput);
            searchInput.addEventListener('input', () => {
                const q = searchInput.value.toLowerCase();
                el.querySelectorAll('.inline-picker-option').forEach(opt => {
                    const label = opt.dataset.label?.toLowerCase() || '';
                    opt.style.display = label.includes(q) ? '' : 'none';
                });
            });
            requestAnimationFrame(() => searchInput.focus());
        }

        options.forEach(opt => {
            const item = document.createElement('div');
            item.className = `inline-picker-option ${opt.key === this.currentValue ? 'active' : ''}`;
            item.dataset.value = opt.key;
            item.dataset.label = opt.label;
            item.style.cssText = `
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 6px 10px;
                font-size: 12px;
                cursor: pointer;
                border-radius: 4px;
                color: var(--text-primary);
                background: ${opt.key === this.currentValue ? 'var(--bg-secondary, #2a2a3e)' : 'transparent'};
            `;
            item.addEventListener('mouseenter', () => { item.style.background = 'var(--bg-secondary, #2a2a3e)'; });
            item.addEventListener('mouseleave', () => {
                item.style.background = opt.key === this.currentValue ? 'var(--bg-secondary, #2a2a3e)' : 'transparent';
            });

            if (opt.color) {
                const dot = document.createElement('span');
                dot.style.cssText = `width:8px;height:8px;border-radius:50%;background:${opt.color};flex-shrink:0;`;
                item.appendChild(dot);
            }

            const label = document.createElement('span');
            label.textContent = opt.label;
            label.style.flex = '1';
            item.appendChild(label);

            if (opt.key === this.currentValue) {
                const check = document.createElement('span');
                check.textContent = '\u2713';
                check.style.cssText = 'color:var(--primary-500);font-weight:600;';
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
        this._applyBaseStyles(el);
        el.style.padding = '8px';
        el.style.minWidth = '200px';

        // Header
        const header = document.createElement('div');
        header.textContent = 'Due Date';
        header.style.cssText = 'font-size:12px;font-weight:600;color:var(--text-muted);margin-bottom:8px;';
        el.appendChild(header);

        // Date input
        const input = document.createElement('input');
        input.type = 'date';
        input.className = 'due-date-input';
        // currentValue may be a unix timestamp or ISO string
        if (this.currentValue) {
            let dateVal = this.currentValue;
            // If it looks like a unix timestamp (digits only), convert to ISO
            if (/^\d+$/.test(dateVal)) {
                dateVal = new Date(parseInt(dateVal) * 1000).toISOString().slice(0, 10);
            } else if (dateVal.length > 10) {
                dateVal = dateVal.slice(0, 10);
            }
            input.value = dateVal;
        }
        input.style.cssText = 'width:100%;padding:6px;border:1px solid var(--border,#333);border-radius:4px;background:var(--bg-secondary,#2a2a3e);color:var(--text-primary);font-size:12px;';
        el.appendChild(input);

        // Footer buttons
        const footer = document.createElement('div');
        footer.style.cssText = 'display:flex;gap:6px;margin-top:8px;justify-content:flex-end;';

        const clearBtn = document.createElement('button');
        clearBtn.textContent = 'Clear';
        clearBtn.className = 'picker-btn picker-clear-btn';
        clearBtn.style.cssText = 'padding:4px 12px;font-size:12px;border:1px solid var(--border,#333);border-radius:4px;background:transparent;color:var(--text-primary);cursor:pointer;';
        clearBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this._selectValue(null);
        });
        footer.appendChild(clearBtn);

        const applyBtn = document.createElement('button');
        applyBtn.textContent = 'Apply';
        applyBtn.className = 'picker-btn picker-apply-btn';
        applyBtn.style.cssText = 'padding:4px 12px;font-size:12px;border:none;border-radius:4px;background:var(--primary-500);color:#fff;cursor:pointer;';
        applyBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this._selectValue(input.value || null);
        });
        footer.appendChild(applyBtn);

        el.appendChild(footer);
        this._showPicker(el);
        requestAnimationFrame(() => input.focus());
    }

    // ------------------------------------------------------------------
    // LabelPicker (multi-select)
    // ------------------------------------------------------------------

    _renderLabelPicker() {
        const allLabels = this.getAllLabels();
        const selected = new Set(this.currentLabels);

        const el = document.createElement('div');
        el.className = 'inline-picker-popover label-picker';
        this._applyBaseStyles(el);
        el.style.padding = '8px';
        el.style.minWidth = '200px';
        el.style.maxHeight = '300px';

        // Header
        const header = document.createElement('div');
        header.textContent = 'Labels';
        header.style.cssText = 'font-size:12px;font-weight:600;color:var(--text-muted);margin-bottom:4px;';
        el.appendChild(header);

        // Search input
        const searchInput = document.createElement('input');
        searchInput.type = 'text';
        searchInput.className = 'picker-search';
        searchInput.placeholder = 'Search labels...';
        searchInput.style.cssText = 'width:100%;padding:6px 8px;margin:4px 0;border:1px solid var(--border,#333);border-radius:4px;background:var(--bg-secondary,#2a2a3e);color:var(--text-primary);font-size:12px;box-sizing:border-box;';
        el.appendChild(searchInput);

        // Options list
        const optionsContainer = document.createElement('div');
        optionsContainer.className = 'picker-options';
        optionsContainer.style.cssText = 'max-height:180px;overflow-y:auto;';

        const optionEls = [];
        allLabels.forEach(label => {
            const item = document.createElement('div');
            item.className = `picker-option ${selected.has(label) ? 'checked' : ''}`;
            item.dataset.label = label;
            item.style.cssText = 'display:flex;align-items:center;padding:4px 8px;cursor:pointer;border-radius:4px;font-size:12px;color:var(--text-primary);';

            const checkbox = document.createElement('span');
            checkbox.className = 'picker-checkbox';
            checkbox.textContent = selected.has(label) ? '\u2611' : '\u2610';
            checkbox.style.cssText = 'width:20px;flex-shrink:0;';
            item.appendChild(checkbox);

            const text = document.createElement('span');
            text.className = 'picker-option-text';
            text.textContent = label;
            text.style.flex = '1';
            item.appendChild(text);

            item.addEventListener('mouseenter', () => { item.style.background = 'var(--bg-secondary, #2a2a3e)'; });
            item.addEventListener('mouseleave', () => { item.style.background = 'transparent'; });

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
                el.style.display = label.toLowerCase().includes(q) ? '' : 'none';
            });
        });

        // Footer
        const footer = document.createElement('div');
        footer.style.cssText = 'display:flex;gap:6px;margin-top:8px;justify-content:flex-end;';

        const applyBtn = document.createElement('button');
        applyBtn.textContent = 'Apply';
        applyBtn.className = 'picker-btn picker-apply-btn';
        applyBtn.style.cssText = 'padding:4px 12px;font-size:12px;border:none;border-radius:4px;background:var(--primary-500);color:#fff;cursor:pointer;';
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

    /**
     * Apply base popover styles (shared across all picker types).
     */
    _applyBaseStyles(el) {
        el.style.cssText = `
            position: fixed;
            z-index: 10000;
            background: var(--bg-primary, #1e1e2e);
            border: 1px solid var(--border, #333);
            border-radius: 8px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.3);
            padding: 4px;
            min-width: 140px;
            max-height: 240px;
            overflow-y: auto;
        `;
    }

    /**
     * Show the picker element: append to body, position, wire close handlers.
     */
    _showPicker(el) {
        this.el = el;
        document.body.appendChild(el);
        this._position();

        document.addEventListener('keydown', this._onKeydown, true);
        setTimeout(() => document.addEventListener('click', this._onClickOutside, true), 0);
    }

    /**
     * Position the popover relative to the anchor element.
     * Prefers below the anchor; flips above if viewport space is insufficient.
     */
    _position() {
        if (!this.el || !this.anchor) return;
        const anchorRect = this.anchor.getBoundingClientRect();
        const elRect = this.el.getBoundingClientRect();

        let top = anchorRect.bottom + 4;
        let left = anchorRect.left;

        // Keep within viewport
        if (top + elRect.height > window.innerHeight) {
            top = anchorRect.top - elRect.height - 4;
        }
        if (left + elRect.width > window.innerWidth) {
            left = window.innerWidth - elRect.width - 8;
        }
        if (left < 0) left = 8;

        this.el.style.top = top + 'px';
        this.el.style.left = left + 'px';
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
