/**
 * MentionTextarea component
 *
 * Adds lightweight @mention autocomplete for a standard <textarea>.
 */
class MentionTextarea {
    constructor(textarea, options = {}) {
        this.textarea = textarea;
        this.candidates = Array.isArray(options.candidates) ? options.candidates : [];
        this.maxItems = Number(options.maxItems || 8);
        this.menu = null;
        this.items = [];
        this.activeIndex = 0;
        this.queryState = null;

        this._onInput = this._onInput.bind(this);
        this._onKeyDown = this._onKeyDown.bind(this);
        this._onBlur = this._onBlur.bind(this);

        if (this.textarea) {
            this.textarea.addEventListener('input', this._onInput);
            this.textarea.addEventListener('keydown', this._onKeyDown);
            this.textarea.addEventListener('blur', this._onBlur);
        }
    }

    static normalizeCandidates(candidates = []) {
        const seen = new Set();
        return candidates
            .map((item) => {
                if (typeof item === 'string') {
                    return { id: item, label: item, type: 'user' };
                }
                if (!item || typeof item !== 'object') return null;
                const label = String(item.label || item.name || item.id || '').trim();
                if (!label) return null;
                return {
                    id: String(item.id || label),
                    label,
                    type: String(item.type || 'user'),
                };
            })
            .filter(Boolean)
            .filter((item) => {
                const key = item.label.toLowerCase();
                if (seen.has(key)) return false;
                seen.add(key);
                return true;
            });
    }

    updateCandidates(candidates = []) {
        this.candidates = Array.isArray(candidates) ? candidates : [];
    }

    destroy() {
        if (this.textarea) {
            this.textarea.removeEventListener('input', this._onInput);
            this.textarea.removeEventListener('keydown', this._onKeyDown);
            this.textarea.removeEventListener('blur', this._onBlur);
        }
        this._hideMenu();
    }

    _onInput() {
        this._refreshMenu();
    }

    _onKeyDown(event) {
        if (!this.menu || this.menu.classList.contains('is-hidden')) return;

        if (event.key === 'ArrowDown') {
            event.preventDefault();
            this.activeIndex = (this.activeIndex + 1) % this.items.length;
            this._renderMenuItems();
            return;
        }
        if (event.key === 'ArrowUp') {
            event.preventDefault();
            this.activeIndex = (this.activeIndex - 1 + this.items.length) % this.items.length;
            this._renderMenuItems();
            return;
        }
        if (event.key === 'Enter' || event.key === 'Tab') {
            event.preventDefault();
            this._applySelection(this.items[this.activeIndex]);
            return;
        }
        if (event.key === 'Escape') {
            event.preventDefault();
            this._hideMenu();
        }
    }

    _onBlur() {
        // Delay so click on menu item can fire first
        setTimeout(() => this._hideMenu(), 120);
    }

    _extractQueryState() {
        if (!this.textarea) return null;
        const value = this.textarea.value || '';
        const pos = this.textarea.selectionStart || 0;
        const textBefore = value.slice(0, pos);
        const match = textBefore.match(/(?:^|\s)@([A-Za-z0-9_.-]{0,64})$/);
        if (!match) return null;

        const query = String(match[1] || '');
        const start = pos - query.length - 1; // includes '@'
        if (start < 0) return null;

        return { query, start, end: pos };
    }

    _filterCandidates(query) {
        const normalized = MentionTextarea.normalizeCandidates(this.candidates);
        const q = String(query || '').toLowerCase();
        const filtered = normalized.filter((item) => item.label.toLowerCase().includes(q));
        return filtered.slice(0, this.maxItems);
    }

    _refreshMenu() {
        const state = this._extractQueryState();
        if (!state) {
            this._hideMenu();
            return;
        }
        const items = this._filterCandidates(state.query);
        if (!items.length) {
            this._hideMenu();
            return;
        }

        this.queryState = state;
        this.items = items;
        this.activeIndex = 0;
        this._showMenu();
        this._renderMenuItems();
    }

    _ensureMenu() {
        if (this.menu) return this.menu;
        const menu = document.createElement('div');
        menu.className = 'mention-textarea-menu is-hidden';
        this._ensureHost().appendChild(menu);
        this.menu = menu;
        return menu;
    }

    _ensureHost() {
        const host = this.textarea?.parentElement || this.textarea;
        if (host) host.classList.add('mention-textarea-host');
        return host;
    }

    _showMenu() {
        this._ensureMenu().classList.remove('is-hidden');
    }

    _hideMenu() {
        if (!this.menu) return;
        this.menu.classList.add('is-hidden');
    }

    _renderMenuItems() {
        const menu = this._ensureMenu();
        menu.innerHTML = this.items.map((item, index) => {
            const active = index === this.activeIndex;
            const type = MentionTextarea.escapeHtml(item.type || 'user');
            const label = MentionTextarea.escapeHtml(item.label || '');
            return `
                <button type="button" class="mention-textarea-item${active ? ' is-active' : ''}" data-mention-index="${index}">
                    <span class="mention-textarea-item-label">@${label}</span>
                    <span class="mention-textarea-item-type">${type}</span>
                </button>
            `;
        }).join('');

        menu.querySelectorAll('[data-mention-index]').forEach((el) => {
            el.addEventListener('mousedown', (event) => {
                event.preventDefault();
                const idx = Number(el.getAttribute('data-mention-index') || '0');
                this._applySelection(this.items[idx]);
            });
        });
    }

    _applySelection(item) {
        if (!item || !this.queryState || !this.textarea) {
            this._hideMenu();
            return;
        }

        const value = this.textarea.value || '';
        const before = value.slice(0, this.queryState.start);
        const after = value.slice(this.queryState.end);
        const mentionText = `@${item.label} `;
        this.textarea.value = `${before}${mentionText}${after}`;

        const nextPos = before.length + mentionText.length;
        this.textarea.focus();
        this.textarea.setSelectionRange(nextPos, nextPos);
        this._hideMenu();

        this.textarea.dispatchEvent(new Event('input', { bubbles: true }));
    }

    static escapeHtml(str) {
        if (str === undefined || str === null) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }
}

window.MentionTextarea = MentionTextarea;
