/**
 * Nexus shell manager modules
 * Extracted from app.js to keep the shell bootstrap smaller and easier to evolve.
 */
(function initNexusShellManagers(global) {
    const existing = global.NexusShellManagers || {};

// ============================================================
// Theme Manager
// ============================================================
class ThemeManager {
    constructor() {
        this.theme = localStorage.getItem('nexus-theme') || 'dark';
        this.apply();
    }

    apply() {
        document.documentElement.setAttribute('data-theme', this.theme);
    }

    toggle() {
        this.theme = this.theme === 'dark' ? 'light' : 'dark';
        localStorage.setItem('nexus-theme', this.theme);
        this.apply();
    }

    get current() {
        return this.theme;
    }
}

// ============================================================
// Page Manager - Handles Chat / Task / Agents / Settings switching
// ============================================================
class PageManager {
    constructor(app) {
        this.app = app;

        const rawPage = this._readRawPageFromUrl() || localStorage.getItem('nexus-page') || 'chat';
        const normalizedPage = this._normalizePage(rawPage);
        this.currentPage = normalizedPage;
        this.pendingSettingsSection = this._readSettingsSectionFromUrl() || this._getLegacySettingsSection(rawPage);

        localStorage.setItem('nexus-page', normalizedPage);

        this.chatView = document.getElementById('chatView');
        this.taskPageView = document.getElementById('taskView');
        this.agentsView = document.getElementById('agentsView');
        this.settingsView = document.getElementById('settingsView');
        this.projectHeaderCenter = document.getElementById('projectHeaderCenter');
        this.projectHeaderRight = document.getElementById('projectHeaderRight');
        this.globalUserFilter = document.getElementById('globalUserFilter');

        this.bindEvents();
        this.apply();

        if (this._readRawPageFromUrl() && this._readRawPageFromUrl() !== normalizedPage) {
            this._syncPageToUrl(normalizedPage, { replace: true, preserveTaskState: normalizedPage === 'task' });
        }
    }

    bindEvents() {
        document.querySelectorAll('.page-nav-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.setPage(btn.dataset.page);
            });
        });

        window.addEventListener('popstate', () => {
            const rawPage = this._readRawPageFromUrl() || 'chat';
            const nextPage = this._normalizePage(rawPage);
            this.pendingSettingsSection = this._readSettingsSectionFromUrl() || this._getLegacySettingsSection(rawPage);

            if (rawPage !== nextPage) {
                this._syncPageToUrl(nextPage, { replace: true, preserveTaskState: nextPage === 'task' });
            }

            if (nextPage === this.currentPage) {
                this._refreshCurrentPage();
                return;
            }

            const prevPage = this.currentPage;
            this.currentPage = nextPage;
            localStorage.setItem('nexus-page', nextPage);
            this.apply();
            this._handlePageTransition(prevPage);
            this._refreshCurrentPage();
        });
    }

    _normalizePage(page) {
        const normalized = String(page || '').trim().toLowerCase();
        if (normalized === 'project') return 'chat';
        if (normalized === 'dashboard') return 'agents';
        if (normalized === 'config' || normalized === 'admin') return 'settings';
        return ['chat', 'task', 'agents', 'settings'].includes(normalized) ? normalized : 'chat';
    }

    _getLegacySettingsSection(page) {
        const normalized = String(page || '').trim().toLowerCase();
        if (normalized === 'admin') return 'safety';
        if (normalized === 'config') return 'basic';
        return null;
    }

    _readRawPageFromUrl() {
        try {
            const params = new URLSearchParams(window.location.search);
            return params.get('page');
        } catch {
            return null;
        }
    }

    _normalizeSettingsSection(section) {
        const normalized = String(section || '').trim().toLowerCase();
        return ['basic', 'extensions', 'safety'].includes(normalized) ? normalized : null;
    }

    _readSettingsSectionFromUrl() {
        try {
            const params = new URLSearchParams(window.location.search);
            return this._normalizeSettingsSection(params.get('settingsSection'));
        } catch {
            return null;
        }
    }

    _syncPageToUrl(page, { replace = false, preserveTaskState = false, settingsSection = undefined } = {}) {
        try {
            const normalizedPage = this._normalizePage(page);
            const url = new URL(window.location.href);
            url.searchParams.set('page', normalizedPage);
            if (normalizedPage !== 'task' && !preserveTaskState) {
                url.searchParams.delete('task');
                url.searchParams.delete('taskTab');
            }
            if (normalizedPage === 'settings') {
                const normalizedSection = settingsSection === undefined
                    ? this._readSettingsSectionFromUrl()
                    : this._normalizeSettingsSection(settingsSection);
                if (normalizedSection) {
                    url.searchParams.set('settingsSection', normalizedSection);
                } else {
                    url.searchParams.delete('settingsSection');
                }
            } else {
                url.searchParams.delete('settingsSection');
            }
            const method = replace ? 'replaceState' : 'pushState';
            window.history[method]({}, '', url);
        } catch {
            // Best-effort URL sync only.
        }
    }

    _handlePageTransition(prevPage) {
        if (prevPage === 'task' && this.currentPage !== 'task' && this.app.taskBoardPanel) {
            this.app.taskBoardPanel.stopAutoPolling();
            this.app.taskBoardPanel.closeAllTaskStreams?.();
        }
    }

    _refreshCurrentPage() {
        if (this.currentPage === 'settings' && this.app.settingsPage) {
            this.app.settingsPage.refresh();
            const section = this.pendingSettingsSection || 'overview';
            window.setTimeout(() => this.app.settingsPage?.scrollToSection?.(section, { syncUrl: false, replaceUrl: true }), 0);
            this.pendingSettingsSection = null;
            return;
        }

        if (this.currentPage === 'agents' && this.app.agentsPage) {
            this.app.agentsPage.refresh();
            return;
        }

        if (this.currentPage === 'task' && this.app.taskBoardPanel) {
            this.app._mountTaskBoard();
            return;
        }

        if (this.currentPage === 'chat' && this.app.refreshChatProviders) {
            this.app.refreshChatProviders();
        }
    }

    setPage(page, options = {}) {
        const prevPage = this.currentPage;
        this.currentPage = this._normalizePage(page);
        this.pendingSettingsSection = this._normalizeSettingsSection(options.settingsSection) || null;
        localStorage.setItem('nexus-page', this.currentPage);

        if (!options.skipUrlSync) {
            this._syncPageToUrl(this.currentPage, {
                replace: !!options.replaceUrl,
                preserveTaskState: !!options.preserveTaskState,
                settingsSection: this.pendingSettingsSection,
            });
        }

        this.apply();
        this._handlePageTransition(prevPage);
        this._refreshCurrentPage();
    }

    syncSettingsSection(section, { replace = false } = {}) {
        if (this.currentPage !== 'settings') return;
        this.pendingSettingsSection = this._normalizeSettingsSection(section) || null;
        this._syncPageToUrl('settings', {
            replace,
            settingsSection: this.pendingSettingsSection,
        });
    }

    apply() {
        document.querySelectorAll('.page-nav-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.page === this.currentPage);
        });

        if (this.chatView) {
            this.chatView.classList.toggle('active', this.currentPage === 'chat');
        }
        if (this.taskPageView) {
            this.taskPageView.classList.toggle('active', this.currentPage === 'task');
        }
        if (this.agentsView) {
            this.agentsView.classList.toggle('active', this.currentPage === 'agents');
        }
        if (this.settingsView) {
            this.settingsView.classList.toggle('active', this.currentPage === 'settings');
        }

        const isChatPage = this.currentPage === 'chat';
        if (this.projectHeaderCenter) {
            this.projectHeaderCenter.hidden = !isChatPage;
        }
        if (this.projectHeaderRight) {
            this.projectHeaderRight.hidden = false;
        }
        if (this.globalUserFilter) {
            this.globalUserFilter.hidden = !isChatPage;
        }
    }
}

// ============================================================
// Layout Manager
// ============================================================
class LayoutManager {
    constructor(app) {
        this.app = app;
        this.mode = localStorage.getItem('nexus-layout') || 'single';
        this.wrapper = document.getElementById('layoutWrapper');
        this.panes = [
            document.getElementById('pane-0'),
            document.getElementById('pane-1'),
            document.getElementById('pane-2'),
            document.getElementById('pane-3'),
        ];
        this.bindEvents();
    }

    bindEvents() {
        document.querySelectorAll('.layout-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.setMode(btn.dataset.mode);
            });
        });
    }

    setMode(mode) {
        this.mode = mode;
        localStorage.setItem('nexus-layout', mode);
        this.wrapper.setAttribute('data-mode', mode);

        // Update button states
        document.querySelectorAll('.layout-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });

        // Show/hide panes based on mode
        const panesNeeded = { single: 1, horizontal: 2, vertical: 2, quad: 4 }[mode];
        this.panes.forEach((pane, i) => {
            pane.hidden = i >= panesNeeded;
        });

        // Initialize panes that don't have tabs yet
        for (let i = 0; i < panesNeeded; i++) {
            if (!this.app.tabManager.panes[i] || this.app.tabManager.panes[i].tabs.length === 0) {
                this.app.tabManager.initPane(i);
            }
        }
    }

    getPanesCount() {
        return { single: 1, horizontal: 2, vertical: 2, quad: 4 }[this.mode];
    }
}

// ============================================================
// Tab Manager
// ============================================================
class TabManager {
    constructor(app) {
        this.app = app;
        this.panes = {}; // { paneId: { tabs: [], activeTabId: '' } }
        this.tabIdCounter = 0;
        this.bindEvents();
    }

    bindEvents() {
        // Use event delegation on document for tab-add buttons
        // This ensures buttons work even after layout changes show/hide panes
        document.addEventListener('click', (e) => {
            const btn = e.target.closest('.tab-add');
            if (btn) {
                e.stopPropagation();
                const paneId = parseInt(btn.dataset.pane);
                this.app.showAddTabDropdown(btn, paneId);
            }
        });
    }

    initPane(paneId) {
        if (!this.panes[paneId]) {
            this.panes[paneId] = { tabs: [], activeTabId: null };
        }
        if (this.panes[paneId].tabs.length === 0) {
            // All new panes default to Chat view
            this.addTab(paneId, 'chat');
        }
    }

    generateTabId() {
        return `tab-${++this.tabIdCounter}`;
    }

    addTab(paneId, type = 'chat', title = null) {
        const pane = this.panes[paneId] || { tabs: [], activeTabId: null };
        this.panes[paneId] = pane;

        const tabId = this.generateTabId();
        const tab = {
            id: tabId,
            type: type,
            title: title || (type === 'chat' ? 'Chat' : 'Task'),
            data: {}
        };

        pane.tabs.push(tab);
        pane.activeTabId = tabId;

        this.renderTabs(paneId);
        this.renderContent(paneId);
        return tabId;
    }

    removeTab(paneId, tabId) {
        const pane = this.panes[paneId];
        if (!pane) return;

        const index = pane.tabs.findIndex(t => t.id === tabId);
        if (index === -1) return;

        pane.tabs.splice(index, 1);

        // If no tabs left, create a new default one
        if (pane.tabs.length === 0) {
            this.addTab(paneId, 'chat');
            return;
        }

        // Update active tab if needed
        if (pane.activeTabId === tabId) {
            pane.activeTabId = pane.tabs[Math.max(0, index - 1)]?.id || pane.tabs[0]?.id;
        }

        this.renderTabs(paneId);
        this.renderContent(paneId);
    }

    setActiveTab(paneId, tabId) {
        const pane = this.panes[paneId];
        if (!pane) return;

        pane.activeTabId = tabId;
        this.renderTabs(paneId);
        this.renderContent(paneId);
    }

    getActiveTab(paneId) {
        const pane = this.panes[paneId];
        if (!pane) return null;
        return pane.tabs.find(t => t.id === pane.activeTabId);
    }

    renameTab(paneId, tabId, newTitle) {
        const pane = this.panes[paneId];
        if (!pane) return;

        const tab = pane.tabs.find(t => t.id === tabId);
        if (tab) {
            tab.title = newTitle;
            this.renderTabs(paneId);
        }
    }

    renderTabs(paneId) {
        const pane = this.panes[paneId];
        const container = document.getElementById(`pane-${paneId}-tabs`);
        if (!pane || !container) return;

        container.innerHTML = pane.tabs.map(tab => `
            <div class="tab ${tab.id === pane.activeTabId ? 'active' : ''}"
                    data-tab-id="${tab.id}"
                    data-pane-id="${paneId}">
                <svg class="tab-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
                </svg>
                <span class="tab-title">${this.escapeHtml(tab.title)}</span>
                <span class="tab-close" data-tab-id="${tab.id}" data-pane-id="${paneId}" title="Close tab">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="10" height="10">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </span>
            </div>
        `).join('');

        // Bind tab click events
        container.querySelectorAll('.tab').forEach(tabEl => {
            tabEl.addEventListener('click', (e) => {
                if (e.target.closest('.tab-close')) return;
                this.setActiveTab(parseInt(tabEl.dataset.paneId), tabEl.dataset.tabId);
            });

            // Double-click to rename
            tabEl.addEventListener('dblclick', (e) => {
                if (e.target.closest('.tab-close')) return;
                this.app.showRenameTabModal(parseInt(tabEl.dataset.paneId), tabEl.dataset.tabId);
            });
        });

        // Bind close button events
        container.querySelectorAll('.tab-close').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.removeTab(parseInt(btn.dataset.paneId), btn.dataset.tabId);
            });
        });
    }

    renderContent(paneId) {
        const tab = this.getActiveTab(paneId);
        const container = document.getElementById(`pane-${paneId}-content`);
        if (!tab || !container) return;

        // All tabs are now chat type
        this.app.chatView.render(paneId, tab, container);
    }

    escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
}


    global.NexusShellManagers = Object.freeze({
        ...existing,
        ThemeManager,
        PageManager,
        LayoutManager,
        TabManager,
    });
})(window);
