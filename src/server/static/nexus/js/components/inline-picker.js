/**
 * InlinePicker - Card-level inline edit popover for status/priority/assignee.
 *
 * Features:
 * - Click on a property badge → small floating picker appears
 * - event.stopPropagation() to protect drag and card-click logic
 * - Supports status, priority, and assignee fields
 * - Keyboard accessible (Escape to close)
 *
 * Usage:
 *   InlinePicker.attach(cardElement, {
 *       taskId: '...',
 *       field: 'status',         // 'status' | 'priority' | 'assignee'
 *       currentValue: 'inbox',
 *       options: [{ key: 'inbox', label: 'Inbox', color: '...' }, ...],
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
        this.onSelect = config.onSelect || (async () => {});
        this.getStatusColumns = config.getStatusColumns || (() => []);
        this.getPriorityOptions = config.getPriorityOptions || (() => [
            { key: 'critical', label: 'Critical', color: 'var(--error)' },
            { key: 'serious', label: 'Serious', color: 'var(--warning)' },
            { key: 'normal', label: 'Normal', color: 'var(--primary-500)' },
        ]);
        this.getAssigneeOptions = config.getAssigneeOptions || (() => []);
        this.el = null;
        this._onKeydown = this._handleKeydown.bind(this);
        this._onClickOutside = this._handleClickOutside.bind(this);
    }

    render() {
        const options = this._getOptions();
        const el = document.createElement('div');
        el.className = 'inline-picker-popover';
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
            // Focus search
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

        this.el = el;
        document.body.appendChild(el);
        this._position();

        // Listen for Escape and outside clicks
        document.addEventListener('keydown', this._onKeydown, true);
        setTimeout(() => document.addEventListener('click', this._onClickOutside, true), 0);
    }

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
        if (value === this.currentValue) {
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
