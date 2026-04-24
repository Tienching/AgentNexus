/**
 * SlashCompleter — autocompletion for slash commands in chat input
 *
 * Shows a dropdown of matching commands when the user types '/'
 * at the beginning of the chat input.
 */
class SlashCompleter {
    /**
     * @param {HTMLTextAreaElement} inputEl - The chat textarea element
     */
    constructor(inputEl) {
        this.input = inputEl;
        this.commands = [];
        this.dropdown = null;
        this.selectedIndex = -1;
        this._onInput = this._onInput.bind(this);
        this._onKeydown = this._onKeydown.bind(this);
        this._onBlur = this._onBlur.bind(this);
        this._bound = false;
    }

    /**
     * Bind events and load commands. Call once after construction.
     */
    async init() {
        await this._loadCommands();
        if (!this._bound) {
            this.input.addEventListener('input', this._onInput);
            this.input.addEventListener('keydown', this._onKeydown);
            this.input.addEventListener('blur', this._onBlur);
            this._bound = true;
        }
    }

    /** Unbind events and remove dropdown. */
    destroy() {
        if (this._bound) {
            this.input.removeEventListener('input', this._onInput);
            this.input.removeEventListener('keydown', this._onKeydown);
            this.input.removeEventListener('blur', this._onBlur);
            this._bound = false;
        }
        this._hideDropdown();
    }

    async _loadCommands() {
        try {
            this.commands = await NexusAPI.listSlashCommands();
        } catch {
            this.commands = [];
        }
    }

    _onInput() {
        const val = this.input.value;
        // Only trigger autocomplete when '/' is at the start and no space yet
        if (val.startsWith('/') && val.indexOf(' ') === -1) {
            const prefix = val.slice(1).toLowerCase();
            const matches = this.commands.filter(c =>
                c.name.toLowerCase().startsWith(prefix)
            );
            if (matches.length > 0 && prefix.length > 0) {
                this._showDropdown(matches);
            } else if (val === '/') {
                // Show all commands when just '/' is typed
                this._showDropdown(this.commands.slice(0, 8));
            } else {
                this._hideDropdown();
            }
        } else {
            this._hideDropdown();
        }
    }

    _onKeydown(e) {
        if (!this.dropdown || !this.dropdown.parentNode) return;

        const items = this.dropdown.querySelectorAll('.slash-item');
        if (items.length === 0) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            this.selectedIndex = Math.min(this.selectedIndex + 1, items.length - 1);
            this._highlightItem(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            this.selectedIndex = Math.max(this.selectedIndex - 1, 0);
            this._highlightItem(items);
        } else if (e.key === 'Tab' || e.key === 'Enter') {
            if (this.selectedIndex >= 0 && this.selectedIndex < items.length) {
                e.preventDefault();
                const cmd = items[this.selectedIndex].dataset.cmd;
                this._selectCommand(cmd);
            }
        } else if (e.key === 'Escape') {
            e.preventDefault();
            this._hideDropdown();
        }
    }

    _onBlur() {
        // Delay to allow click on dropdown item
        setTimeout(() => this._hideDropdown(), 150);
    }

    _showDropdown(matches) {
        if (!this.dropdown) {
            this.dropdown = document.createElement('div');
            this.dropdown.className = 'slash-completer-dropdown';
        }

        this.selectedIndex = -1;
        this.dropdown.innerHTML = matches.map((cmd, i) =>
            `<div class="slash-item" data-cmd="${this._escapeAttr(cmd.name)}" data-index="${i}">` +
            `<span class="slash-item-name">/${cmd.name}</span>` +
            `<span class="slash-item-desc">${this._escapeHtml(cmd.description || '')}</span>` +
            `</div>`
        ).join('');

        // Click handler for dropdown items
        this.dropdown.querySelectorAll('.slash-item').forEach(item => {
            item.addEventListener('mousedown', (e) => {
                e.preventDefault();
                this._selectCommand(item.dataset.cmd);
            });
        });

        const host = this.input.parentElement || this.input;
        host.classList.add('slash-completer-host');

        if (!this.dropdown.parentNode) {
            host.appendChild(this.dropdown);
        }
    }

    _hideDropdown() {
        if (this.dropdown && this.dropdown.parentNode) {
            this.dropdown.parentNode.removeChild(this.dropdown);
        }
        this.selectedIndex = -1;
    }

    _highlightItem(items) {
        items.forEach((item, i) => {
            item.classList.toggle('selected', i === this.selectedIndex);
        });
    }

    _selectCommand(cmdName) {
        this.input.value = '/' + cmdName + ' ';
        this.input.focus();
        // Move cursor to end
        this.input.setSelectionRange(this.input.value.length, this.input.value.length);
        this._hideDropdown();
        // Trigger input event to resize textarea
        this.input.dispatchEvent(new Event('input'));
    }

    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    _escapeAttr(str) {
        return str.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
}

window.SlashCompleter = SlashCompleter;
