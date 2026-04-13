/**
 * Nexus Application - Enhanced UI
 * Supports split-view layouts, multi-tab panes, chat and task views
 */

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
// Page Manager - Handles Chat/Task/Config page switching
// ============================================================
class PageManager {
    constructor(app) {
        this.app = app;
        // Migrate old page names to the current structure
        let storedPage = localStorage.getItem('nexus-page');
        if (storedPage === 'project') {
            storedPage = 'chat';
        }
        if (storedPage === 'config' || storedPage === 'admin') {
            storedPage = 'settings';
        }
        if (storedPage) {
            localStorage.setItem('nexus-page', storedPage);
        }
        this.currentPage = storedPage || 'chat';
        this.chatView = document.getElementById('chatView');
        this.taskView = document.getElementById('taskView');
        this.settingsView = document.getElementById('settingsView');
        this.projectHeaderCenter = document.getElementById('projectHeaderCenter');
        this.projectHeaderRight = document.getElementById('projectHeaderRight');
        this.globalUserFilter = document.getElementById('globalUserFilter');
        this.bindEvents();
        this.apply();
    }

    bindEvents() {
        document.querySelectorAll('.page-nav-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.setPage(btn.dataset.page);
            });
        });
    }

    setPage(page) {
        const prevPage = this.currentPage;
        this.currentPage = page;
        localStorage.setItem('nexus-page', page);
        this.apply();

        // Stop task polling/streams when leaving task page
        if (prevPage === 'task' && page !== 'task' && this.app.taskBoardPanel) {
            this.app.taskBoardPanel._stopAutoPolling();
        }

        // Refresh settings view when switching to settings page
        if (page === 'settings' && this.app.settingsView) {
            this.app.settingsView.refresh();
        }

        // Mount/refresh task board when switching to task page
        if (page === 'task' && this.app.taskBoardPanel) {
            this.app._mountTaskBoard();
        }

        // Refresh chat providers when switching back to chat page
        if (page === 'chat' && this.app.refreshChatProviders) {
            this.app.refreshChatProviders();
        }

        // No additional action needed for task/settings pages
    }

    apply() {
        // Update nav button states
        document.querySelectorAll('.page-nav-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.page === this.currentPage);
        });

        // Show/hide page views
        if (this.chatView) {
            this.chatView.classList.toggle('active', this.currentPage === 'chat');
        }
        if (this.taskView) {
            this.taskView.classList.toggle('active', this.currentPage === 'task');
        }
        if (this.settingsView) {
            this.settingsView.classList.toggle('active', this.currentPage === 'settings');
        }

        // Show/hide chat-specific header elements
        const isChatPage = this.currentPage === 'chat';
        if (this.projectHeaderCenter) {
            this.projectHeaderCenter.style.display = isChatPage ? '' : 'none';
        }
        if (this.projectHeaderRight) {
            this.projectHeaderRight.style.display = '';
        }
        if (this.globalUserFilter) {
            this.globalUserFilter.style.display = isChatPage ? '' : 'none';
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
            pane.style.display = i < panesNeeded ? '' : 'none';
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

// ============================================================
// Chat View
// ============================================================
class ChatView {
    constructor(app) {
        this.app = app;
        this.sessions = {};
        this.currentSessionByTab = {}; // tabId -> sessionId
        this.selectionMode = {};  // paneId -> boolean
        this.selectedSessionIds = {}; // paneId -> Set<sessionId>
        this.sessionSource = {};  // paneId -> 'runtime' | 'history'
        this.historyProjectPath = {}; // paneId -> string
        this.historyViewMode = {}; // paneId -> 'projects' | 'sessions'
        this.historyProjects = {}; // paneId -> array of project entries
        this.taskSessionStreams = {}; // paneId -> EventSource (for task_* sessions)
        this.promotedRuntimeMeta = {}; // runtimeSessionId -> synthetic meta (fallback when backend promote API unavailable)
        this.pendingBootstrapBySessionId = {}; // runtimeSessionId -> one-time bootstrap context text
        this._chatStreaming = {}; // paneId -> boolean, true when fetch streaming is active (prevents auto-refresh from overwriting DOM)
        this._pendingNewSession = {}; // paneId -> { id: string, createdAt: number }

        // Auto-refresh state
        this._autoRefreshTimer = null;
        this._autoRefreshInterval = 5000; // 5s for session list
        this._lastSessionsHash = {}; // paneId -> hash of session list (for change detection)
        this._lastMessageCountBySession = {}; // sessionId -> last known message count

        // Markdown renderer component (MC-035)
        this.markdownRenderer = typeof window.MarkdownRenderer === 'function'
            ? new window.MarkdownRenderer({ renderFn: (text) => this.renderMarkdown(text) })
            : null;
    }

    _markPendingNewSession(paneId, sessionId) {
        this._pendingNewSession[paneId] = { id: sessionId, createdAt: Date.now() };
    }

    _clearPendingNewSession(paneId, sessionId = null) {
        const pending = this._pendingNewSession[paneId];
        if (!pending) return;
        if (!sessionId || pending.id === sessionId) {
            delete this._pendingNewSession[paneId];
        }
    }

    _isPendingNewSession(paneId, sessionId) {
        const pending = this._pendingNewSession[paneId];
        if (!pending || pending.id !== sessionId) return false;
        // Keep a short grace window for backend persistence latency.
        if ((Date.now() - pending.createdAt) > 60000) {
            delete this._pendingNewSession[paneId];
            return false;
        }
        return true;
    }

    // ============ Auto-refresh (live polling) ============

    startAutoRefresh() {
        if (this._autoRefreshTimer) return;
        this._autoRefreshTimer = setInterval(() => this._autoRefreshTick(), this._autoRefreshInterval);
    }

    stopAutoRefresh() {
        if (this._autoRefreshTimer) {
            clearInterval(this._autoRefreshTimer);
            this._autoRefreshTimer = null;
        }
    }

    async _autoRefreshTick() {
        // Only refresh when chat page is active
        if (this.app.pageManager.currentPage !== 'chat') return;

        const panesCount = this.app.layoutManager.getPanesCount();
        for (let i = 0; i < panesCount; i++) {
            await this._autoRefreshPane(i);
        }
    }

    async _autoRefreshPane(paneId) {
        try {
            const isHistory = this.sessionSource[paneId] === 'history';

            // 1. Refresh session list (Runtime only — history is file-based, less dynamic)
            if (!isHistory) {
                const statusFilter = document.querySelector(`.session-filter-select[data-pane="${paneId}"][data-filter="status"]`);
                const searchInput = document.querySelector(`.session-search-input:not(.history-path-input)[data-pane="${paneId}"]`);
                const globalUserFilter = document.getElementById('globalUserFilter');
                const data = await NexusAPI.getSessions({
                    pageSize: 50,
                    search: searchInput?.value || '',
                    status: statusFilter?.value || '',
                    username: globalUserFilter?.value || '',
                });

                // Only re-render if data changed (compare by hash of ids + updated_at)
                const newHash = (data.sessions || []).map(s => `${s.id}:${s.updated_at}:${s.status}:${s.message_count}`).join('|');
                if (newHash !== this._lastSessionsHash[paneId]) {
                    this._lastSessionsHash[paneId] = newHash;
                    this.sessions[paneId] = data.sessions || [];
                    this.sessionTotals = this.sessionTotals || {};
                    this.sessionTotals[paneId] = data.total || this.sessions[paneId].length;
                    this.renderSessionList(paneId);
                }
            }

            // 2. Refresh active session messages if session is running
            //    Skip if an SSE stream is already active for this pane (channel/task streaming)
            //    Skip if fetch streaming (chat response) is in progress for this pane
            const activeTabId = this.getActiveTabId(paneId);
            const activeSessionId = activeTabId ? this.currentSessionByTab[activeTabId] : null;
            if (activeSessionId && !isHistory && !/^task_/.test(activeSessionId) && !this.taskSessionStreams[paneId] && !this._chatStreaming[paneId] && !this._isPendingNewSession(paneId, activeSessionId)) {
                const activeMeta = this.getSessionMeta(paneId, activeSessionId);

                // Check if post-stream sync is needed (stream just finished, status may already be completed)
                const postSync = this._needsPostStreamSync && this._needsPostStreamSync[paneId];
                if (postSync && postSync.sessionId === activeSessionId) {
                    try {
                        const data = await NexusAPI.getSessionMessages(activeSessionId);
                        this.renderMessages(paneId, activeSessionId, data);
                    } catch (e) {
                        console.warn('[autoRefresh] post-stream sync failed:', e);
                    }
                    delete this._needsPostStreamSync[paneId];
                } else if (activeMeta && ['running', 'pending', 'queued'].includes(activeMeta.status)) {
                    const source = activeMeta.source || 'runtime';
                    if (source !== 'history') {
                        // Check if we should switch to SSE streaming
                        const container = document.getElementById(`sessionItems-${paneId}`);
                        const sessionItem = container?.querySelector(`.session-item[data-session-id="${activeSessionId}"]`);
                        const sessionStatus = sessionItem?.dataset.status || '';
                        if (!sessionStatus || ['running', 'pending', 'queued'].includes(sessionStatus)) {
                            await this._streamChannelSessionMessages(paneId, activeSessionId);
                        } else {
                            const data = await NexusAPI.getSessionMessages(activeSessionId);
                            const msgCount = (data.messages || []).length;
                            const prevCount = this._lastMessageCountBySession[activeSessionId] || 0;
                            if (msgCount !== prevCount) {
                                this._lastMessageCountBySession[activeSessionId] = msgCount;
                                this.renderMessages(paneId, activeSessionId, data);
                            }
                        }
                    }
                } else if (activeMeta && activeMeta.status === 'completed') {
                    // Auto-reload messages when message_count changes for the
                    // active completed session. This handles the case where the
                    // session went running→completed between two poll ticks
                    // (e.g. channel message processed faster than the 5s poll).
                    const serverMsgCount = activeMeta.message_count || 0;
                    const prevCount = this._lastMessageCountBySession[activeSessionId] || 0;
                    if (serverMsgCount > 0 && serverMsgCount !== prevCount) {
                        this._lastMessageCountBySession[activeSessionId] = serverMsgCount;
                        try {
                            const data = await NexusAPI.getSessionMessages(activeSessionId);
                            this.renderMessages(paneId, activeSessionId, data);
                        } catch (e) {
                            console.warn('[autoRefresh] message count sync failed:', e);
                        }
                    }
                }
            }
        } catch (e) {
            // Silently ignore auto-refresh errors
        }
    }

    async render(paneId, tab, container) {
        // Initialize selection state for this pane
        if (!this.selectionMode[paneId]) {
            this.selectionMode[paneId] = false;
        }
        if (!this.selectedSessionIds[paneId]) {
            this.selectedSessionIds[paneId] = new Set();
        }
        if (!this.sessionSource[paneId]) {
            this.sessionSource[paneId] = 'runtime';
        }
        if (!this.historyViewMode[paneId]) {
            this.historyViewMode[paneId] = 'projects';
        }

        if (tab?.id && this.currentSessionByTab[tab.id] === undefined) {
            this.currentSessionByTab[tab.id] = tab.data?.sessionId || null;
        }

        const isHistory = this.sessionSource[paneId] === 'history';
        const isHistorySessions = isHistory && this.historyViewMode[paneId] === 'sessions' && this.historyProjectPath[paneId];
        const isHistoryProjects = isHistory && !isHistorySessions;
        const selectedProjectPath = this.historyProjectPath[paneId] || '';

        container.innerHTML = `
            <div class="chat-container">
                <div class="session-list" id="sessionList-${paneId}">
                    <div class="session-list-header">
                        <div class="session-header-row">
                            <span class="session-header-title">${isHistorySessions ? 'History Sessions' : isHistoryProjects ? 'History Projects' : 'Sessions'}</span>
                            <div class="session-header-actions">
                                <button class="action-btn primary" data-action="new-session" data-pane="${paneId}" ${isHistory ? 'style="display:none"' : ''}>
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                                    </svg>
                                    <span>New Chat</span>
                                </button>
                                <button class="action-btn" data-action="toggle-session-selection" data-pane="${paneId}" title="Batch select" ${isHistory ? 'style="display:none"' : ''}>
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>
                                    </svg>
                                    <span>Select</span>
                                </button>
                            </div>
                        </div>
                        <div class="session-source-tabs">
                            <button class="session-source-tab ${!isHistory ? 'active' : ''}" data-source="runtime" data-pane="${paneId}">
                                Runtime
                            </button>
                            <button class="session-source-tab ${isHistory ? 'active' : ''}" data-source="history" data-pane="${paneId}">
                                History
                            </button>
                        </div>
                        <div class="session-selection-actions" id="sessionSelectionActions-${paneId}" style="display: none;">
                            <button class="action-btn" data-action="select-all-sessions" data-pane="${paneId}">
                                <span>Select All</span>
                            </button>
                            <button class="action-btn" data-action="deselect-all-sessions" data-pane="${paneId}">
                                <span>Clear</span>
                            </button>
                            <button class="action-btn danger" data-action="delete-selected-sessions" data-pane="${paneId}" id="deleteSelectedSessionsBtn-${paneId}">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                                </svg>
                                <span>Delete (0)</span>
                            </button>
                        </div>
                        ${isHistorySessions ? `
                            <div style="display:flex;align-items:center;gap:6px;margin:4px 0;padding:4px 6px;background:var(--bg-tertiary,#2a2a2a);border-radius:4px;">
                                <button class="history-back-btn" data-pane="${paneId}" style="background:none;border:none;cursor:pointer;color:var(--text-secondary);padding:2px;display:flex;align-items:center;" title="Back to projects">
                                    <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/></svg>
                                </button>
                                <span style="font-size:11px;color:var(--text-secondary);font-family:var(--font-mono,monospace);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${this.escapeHtml(selectedProjectPath)}">${this.escapeHtml(selectedProjectPath)}</span>
                            </div>
                        ` : ''}
                        ${isHistoryProjects ? `
                            <div class="history-project-path" id="historyProjectPath-${paneId}" style="margin:4px 0;">
                                <input type="text" class="session-search-input history-path-input" placeholder="Or type a path and press Enter..."
                                    data-pane="${paneId}" value="${this.escapeHtml(this.historyProjectPath[paneId] || '')}"
                                    style="width:100%;font-size:11px;font-family:var(--font-mono,monospace);">
                            </div>
                        ` : ''}
                        <div class="session-search" style="${isHistoryProjects ? 'display:none' : ''}">
                            <svg class="session-search-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                            </svg>
                            <input type="text" class="session-search-input" placeholder="Search sessions..." data-pane="${paneId}">
                        </div>
                        <div class="session-filter" id="sessionFilter-${paneId}" style="${isHistory ? 'display:none' : ''}">
                            <select class="session-filter-select" data-pane="${paneId}" data-filter="status">
                                <option value="">All Status</option>
                                <option value="running">Running</option>
                                <option value="completed">Completed</option>
                                <option value="error">Error</option>
                            </select>
                        </div>
                        <div class="session-filter" id="historyProviderFilter-${paneId}" style="${isHistorySessions ? '' : 'display:none'}">
                            <select class="session-filter-select history-provider-filter" data-pane="${paneId}" data-filter="provider">
                                <option value="">All Providers</option>
                                <option value="claude">Claude</option>
                                <option value="codebuddy">CodeBuddy</option>
                                <option value="codex">Codex</option>
                                <option value="gemini">Gemini</option>
                            </select>
                        </div>
                    </div>
                    <div class="session-items" id="sessionItems-${paneId}">
                        <div class="empty-state">
                            <div class="loading-spinner"></div>
                        </div>
                    </div>
                </div>
                <div class="chat-detail" id="chatDetail-${paneId}">
                    <div class="empty-state">
                        <svg class="empty-state-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
                        </svg>
                        <p class="empty-state-title">Select a session</p>
                        <p class="empty-state-text">Choose a session from the list to view messages</p>
                    </div>
                </div>
            </div>
        `;

        this.bindEvents(paneId);
        await this.loadSessions(paneId);

        const activeSessionId = tab?.data?.sessionId || (tab?.id ? this.currentSessionByTab[tab.id] : null);
        // Restore session from URL hash (e.g. #task_56c45bfc) if no tab-level selection
        const hashSessionId = !activeSessionId && location.hash ? location.hash.slice(1) : null;
        const targetSessionId = activeSessionId || hashSessionId;
        if (targetSessionId) {
            const inList = (this.sessions[paneId] || []).some(s => s.id === targetSessionId);
            const isPending = this._isPendingNewSession(paneId, targetSessionId);
            if (!inList && isPending) {
                return;
            }
            await this.selectSession(paneId, targetSessionId, { silent: true });
        }
    }

    getActiveTabId(paneId) {
        const tab = this.app.tabManager.getActiveTab(paneId);
        return tab ? tab.id : null;
    }

    getActiveTab(paneId) {
        return this.app.tabManager.getActiveTab(paneId);
    }

    bindEvents(paneId) {
        const searchInput = document.querySelector(`.session-search-input:not(.history-path-input)[data-pane="${paneId}"]`);
        if (searchInput) {
            let timeout;
            searchInput.addEventListener('input', () => {
                clearTimeout(timeout);
                timeout = setTimeout(() => this.loadSessions(paneId), 300);
            });
        }

        const statusFilter = document.querySelector(`.session-filter-select[data-pane="${paneId}"][data-filter="status"]`);
        if (statusFilter) {
            statusFilter.addEventListener('change', () => this.loadSessions(paneId));
        }

        // Source tab switching (Runtime / History)
        document.querySelectorAll(`.session-source-tab[data-pane="${paneId}"]`).forEach(btn => {
            btn.addEventListener('click', () => {
                const source = btn.dataset.source;
                if (this.sessionSource[paneId] === source) return;
                this.sessionSource[paneId] = source;
                // When switching to History, reset to projects view
                if (source === 'history') {
                    this.historyViewMode[paneId] = 'projects';
                    this.historyProjectPath[paneId] = '';
                }
                // Re-render the whole pane to update UI state
                const tab = this.getActiveTab(paneId);
                const container = document.getElementById(`sessionList-${paneId}`)?.parentElement?.parentElement;
                if (container) {
                    this.render(paneId, tab, container);
                }
            });
        });

        // History back button (sessions -> projects)
        const historyBackBtn = document.querySelector(`.history-back-btn[data-pane="${paneId}"]`);
        if (historyBackBtn) {
            historyBackBtn.addEventListener('click', () => {
                this.historyViewMode[paneId] = 'projects';
                this.historyProjectPath[paneId] = '';
                const tab = this.getActiveTab(paneId);
                const container = document.getElementById(`sessionList-${paneId}`)?.parentElement?.parentElement;
                if (container) {
                    this.render(paneId, tab, container);
                }
            });
        }

        // History project path input (manual entry)
        const historyPathInput = document.querySelector(`.history-path-input[data-pane="${paneId}"]`);
        if (historyPathInput) {
            historyPathInput.addEventListener('input', () => {
                this.historyProjectPath[paneId] = historyPathInput.value;
            });
            historyPathInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    const path = historyPathInput.value.trim();
                    if (path) {
                        this.historyProjectPath[paneId] = path;
                        this.historyViewMode[paneId] = 'sessions';
                        const tab = this.getActiveTab(paneId);
                        const container = document.getElementById(`sessionList-${paneId}`)?.parentElement?.parentElement;
                        if (container) {
                            this.render(paneId, tab, container);
                        }
                    }
                }
            });
        }

        // History provider filter
        const providerFilter = document.querySelector(`.history-provider-filter[data-pane="${paneId}"]`);
        if (providerFilter) {
            providerFilter.addEventListener('change', () => this.loadSessions(paneId));
        }

        // New session button
        const newSessionBtn = document.querySelector(`[data-action="new-session"][data-pane="${paneId}"]`);
        if (newSessionBtn) {
            newSessionBtn.addEventListener('click', () => this.showNewSessionView(paneId));
        }

        // Toggle selection mode button
        const toggleSelectionBtn = document.querySelector(`[data-action="toggle-session-selection"][data-pane="${paneId}"]`);
        if (toggleSelectionBtn) {
            toggleSelectionBtn.addEventListener('click', () => this.toggleSessionSelectionMode(paneId));
        }

        // Select all button
        const selectAllBtn = document.querySelector(`[data-action="select-all-sessions"][data-pane="${paneId}"]`);
        if (selectAllBtn) {
            selectAllBtn.addEventListener('click', () => this.selectAllSessions(paneId));
        }

        // Deselect all button
        const deselectAllBtn = document.querySelector(`[data-action="deselect-all-sessions"][data-pane="${paneId}"]`);
        if (deselectAllBtn) {
            deselectAllBtn.addEventListener('click', () => this.deselectAllSessions(paneId));
        }

        // Delete selected button
        const deleteSelectedBtn = document.querySelector(`[data-action="delete-selected-sessions"][data-pane="${paneId}"]`);
        if (deleteSelectedBtn) {
            deleteSelectedBtn.addEventListener('click', () => this.deleteSelectedSessions(paneId));
        }
    }

    getSessionMeta(paneId, sessionId) {
        const sessions = this.sessions[paneId] || [];
        return sessions.find(session => session.id === sessionId) || this.promotedRuntimeMeta[sessionId] || null;
    }

    getAvailableAgents(selectedUser = '') {
        const agents = (this.app.availableAgents || []).filter(agent => {
            const agentType = (agent.agent_type || '').toLowerCase();
            return !agentType.endsWith('-internal');
        });
        if (!agents.length) return [];
        return agents.filter(agent => {
            if (agent.available === false) return false;
            if (selectedUser && agent.username !== selectedUser) return false;
            return true;
        });
    }

    buildAgentOptions(agents = []) {
        if (!agents.length) {
            return '<option value="ubuntu::claude">ubuntu / claude</option>';
        }

        const groups = {};
        agents.forEach(agent => {
            if (!groups[agent.username]) {
                groups[agent.username] = [];
            }
            groups[agent.username].push(agent);
        });

        return Object.entries(groups).map(([username, items]) => {
            const options = items.map(agent => {
                const label = agent.display_name || `${agent.username} / ${agent.agent_type}`;
                return `<option value="${this.escapeHtml(agent.id)}">${this.escapeHtml(label)}</option>`;
            }).join('');
            return `<optgroup label="${this.escapeHtml(username)}">${options}</optgroup>`;
        }).join('');
    }

    parseAgentSelection(value) {
        const defUser = NexusAPI.getDefaultExecUser();
        const fallback = { username: defUser, agentType: 'claude', label: `${defUser} / claude` };
        if (!value) return fallback;

        const agents = this.app.availableAgents || [];
        const matched = agents.find(agent => agent.id === value);
        if (matched) {
            return {
                username: matched.username,
                agentType: matched.agent_type || 'claude',
                label: matched.display_name || `${matched.username} / ${matched.agent_type || 'claude'}`
            };
        }

        const parts = value.split('::');
        const username = parts[0] || NexusAPI.getDefaultExecUser();
        const agentType = parts[1] || 'claude';
        return {
            username,
            agentType,
            label: `${username} / ${agentType}`
        };
    }

    showNewSessionView(paneId) {
        const detail = document.getElementById(`chatDetail-${paneId}`);
        if (!detail) return;

        // Clear current session selection for active tab
        const activeTabId = this.getActiveTabId(paneId);
        if (activeTabId) {
            this.currentSessionByTab[activeTabId] = null;
            const tab = this.getActiveTab(paneId);
            if (tab) {
                tab.data = tab.data || {};
                tab.data.sessionId = null;
            }
        }
        const container = document.getElementById(`sessionItems-${paneId}`);
        container?.querySelectorAll('.session-item').forEach(item => {
            item.classList.remove('active');
        });

        // Get available agents
        const globalUserFilter = document.getElementById('globalUserFilter');
        const selectedUser = globalUserFilter?.value || '';
        const allAgents = this.getAvailableAgents('');
        const rawUsernames = [...new Set(allAgents.map(agent => agent.username))];
        const usernames = rawUsernames.length ? rawUsernames : [NexusAPI.getDefaultExecUser()];
        const initialUser = (selectedUser && usernames.includes(selectedUser))
            ? selectedUser
            : (usernames.includes(NexusAPI.getDefaultExecUser()) ? NexusAPI.getDefaultExecUser() : (usernames[0] || NexusAPI.getDefaultExecUser()));

        const buildModelOptions = (user) => {
            const agents = this.getAvailableAgents(user);
            const agentModels = [...new Set(agents.map(agent => agent.agent_type))];
            // Merge with custom providers (use getCustomProviderNames for new format)
            const customProviderNames = this.app.getCustomProviderNames ? this.app.getCustomProviderNames() : [];
            const defaultProviders = this.app.getDefaultProviders ? this.app.getDefaultProviders() : ['nanobot', 'claude', 'gemini', 'codex', 'codebuddy'];
            const allModels = [...new Set([...defaultProviders, ...customProviderNames, ...agentModels])];
            if (!allModels.length) {
                return '<option value="claude">claude</option>';
            }
            const getModelLabel = (model) => {
                if (this.app?.isCustomAlias && this.app.isCustomAlias(model)) {
                    const baseProvider = this.app.getBaseProvider ? this.app.getBaseProvider(model) : null;
                    if (baseProvider) {
                        return `${model} (${baseProvider})`;
                    }
                }
                return model;
            };
            return allModels.map(model => {
                const label = getModelLabel(model);
                return `<option value="${this.escapeHtml(model)}">${this.escapeHtml(label)}</option>`;
            }).join('');
        };

        // Render new session view with input and selectors
        detail.innerHTML = `
            <div class="new-session-view">
                <div class="new-session-content">
                    <div class="new-session-icon">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="64" height="64">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
                        </svg>
                    </div>
                    <h2 class="new-session-title">Start New Chat</h2>
                    <p class="new-session-hint">Select a User and Model, then enter your message</p>
                </div>
                <div class="new-session-agent-selector" style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
                    <label>Select Agent</label>
                    <select id="newSessionUser-${paneId}" class="new-session-agent-select"></select>
                    <select id="newSessionModel-${paneId}" class="new-session-agent-select"></select>
                </div>
                <div class="new-session-input-container">
                    <textarea
                        id="newSessionInput-${paneId}"
                        class="new-session-input"
                        placeholder="Enter your message..."
                        rows="3"
                    ></textarea>
                    <button class="new-session-send-btn" data-pane="${paneId}">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="20" height="20">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
                        </svg>
                        Send
                    </button>
                </div>
            </div>
        `;

        // Set default user/model
        const userSelect = document.getElementById(`newSessionUser-${paneId}`);
        const modelSelect = document.getElementById(`newSessionModel-${paneId}`);

        const applyModelOptions = (user, preferred = null) => {
            if (!modelSelect) return;
            const defaultPref = preferred || this.app.getDefaultProvider();
            modelSelect.innerHTML = buildModelOptions(user);
            const optionValues = Array.from(modelSelect.options).map(opt => opt.value);
            const selected = optionValues.includes(defaultPref) ? defaultPref : (optionValues[0] || 'claude');
            modelSelect.value = selected;
        };

        if (userSelect) {
            userSelect.innerHTML = usernames.map(u => `<option value="${this.escapeHtml(u)}">${this.escapeHtml(u)}</option>`).join('');
            userSelect.value = initialUser;
            applyModelOptions(initialUser);
            userSelect.addEventListener('change', () => {
                const user = userSelect.value || initialUser;
                applyModelOptions(user);
            });
        } else {
            applyModelOptions(initialUser);
        }

        // Bind events
        const textarea = document.getElementById(`newSessionInput-${paneId}`);
        const sendBtn = detail.querySelector('.new-session-send-btn');

        if (textarea) {
            textarea.focus();
            textarea.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    const selectedUser = userSelect?.value || initialUser || NexusAPI.getDefaultExecUser();
                    const selectedModel = modelSelect?.value || this.app.getDefaultProvider();
                    this.createNewSession(paneId, textarea.value, selectedUser, selectedModel, selectedModel);
                }
            });
        }

        if (sendBtn) {
            sendBtn.addEventListener('click', () => {
                const selectedUser = userSelect?.value || initialUser || NexusAPI.getDefaultExecUser();
                const selectedModel = modelSelect?.value || this.app.getDefaultProvider();
                this.createNewSession(paneId, textarea?.value || '', selectedUser, selectedModel, selectedModel);
            });
        }
    }

    refreshNewSessionSelectors(paneId) {
        const userSelect = document.getElementById(`newSessionUser-${paneId}`);
        const modelSelect = document.getElementById(`newSessionModel-${paneId}`);
        if (!modelSelect) return;

        const globalUserFilter = document.getElementById('globalUserFilter');
        const selectedUser = globalUserFilter?.value || '';
        const allAgents = this.getAvailableAgents('');
        const rawUsernames = [...new Set(allAgents.map(agent => agent.username))];
        const usernames = rawUsernames.length ? rawUsernames : [NexusAPI.getDefaultExecUser()];
        const fallbackUser = (selectedUser && usernames.includes(selectedUser))
            ? selectedUser
            : (usernames.includes(NexusAPI.getDefaultExecUser()) ? NexusAPI.getDefaultExecUser() : (usernames[0] || NexusAPI.getDefaultExecUser()));

        const buildModelOptions = (user) => {
            const agents = this.getAvailableAgents(user);
            const agentModels = [...new Set(agents.map(agent => agent.agent_type))];
            const customProviderNames = this.app.getCustomProviderNames ? this.app.getCustomProviderNames() : [];
            const defaultProviders = this.app.getDefaultProviders ? this.app.getDefaultProviders() : ['nanobot', 'claude', 'gemini', 'codex', 'codebuddy'];
            const allModels = [...new Set([...defaultProviders, ...customProviderNames, ...agentModels])];
            if (!allModels.length) {
                return '<option value="claude">claude</option>';
            }
            const getModelLabel = (model) => {
                if (this.app?.isCustomAlias && this.app.isCustomAlias(model)) {
                    const baseProvider = this.app.getBaseProvider ? this.app.getBaseProvider(model) : null;
                    if (baseProvider) {
                        return `${model} (${baseProvider})`;
                    }
                }
                return model;
            };
            return allModels.map(model => {
                const label = getModelLabel(model);
                return `<option value="${this.escapeHtml(model)}">${this.escapeHtml(label)}</option>`;
            }).join('');
        };

        const currentUser = userSelect?.value || fallbackUser;
        const resolvedUser = usernames.includes(currentUser) ? currentUser : fallbackUser;

        if (userSelect) {
            userSelect.innerHTML = usernames.map(u => `<option value="${this.escapeHtml(u)}">${this.escapeHtml(u)}</option>`).join('');
            userSelect.value = resolvedUser;
        }

        const currentModel = modelSelect.value;
        modelSelect.innerHTML = buildModelOptions(resolvedUser);
        const optionValues = Array.from(modelSelect.options).map(opt => opt.value);
        const defaultPref = this.app.getDefaultProvider();
        const selected = optionValues.includes(currentModel)
            ? currentModel
            : (optionValues.includes(defaultPref) ? defaultPref : (optionValues[0] || 'claude'));
        modelSelect.value = selected;
    }

    async createNewSession(paneId, message, execUser = null, agentType = 'claude', alias = null) {
        console.log('[createNewSession] START', { paneId, message: message?.substring(0, 50), execUser, agentType, alias });
        execUser = execUser || NexusAPI.getDefaultExecUser();
        if (!message.trim()) {
            console.log('[createNewSession] empty message, returning');
            this.app.showToast('Please enter a message', 'warning');
            return;
        }

        const agentLabel = `${execUser} / ${agentType}`;

        const detail = document.getElementById(`chatDetail-${paneId}`);
        console.log('[createNewSession] detail element:', !!detail);
        if (!detail) return;
        
        // Generate a unique session ID
        const sessionId = `chat_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
        this._markPendingNewSession(paneId, sessionId);
        const sessionTitle = message.substring(0, 50) + (message.length > 50 ? '...' : '');

        // Immediately show the chat view with user message and thinking indicator
        detail.innerHTML = `
            <div class="chat-header">
                <div class="chat-header-info">
                    <h2 class="chat-header-title">${this.escapeHtml(sessionTitle)}</h2>
                    <span class="chat-header-meta">New Session - ${this.escapeHtml(agentLabel)}</span>
                </div>
            </div>
            <div class="chat-messages" id="chatMessages-${paneId}">
                <div class="message user">
                    <div class="message-avatar user">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="18" height="18">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
                        </svg>
                    </div>
                    <div class="message-content">
                        <div class="message-bubble"><div class="message-text">${this.escapeHtml(message)}</div></div>
                    </div>
                </div>
                <div class="message assistant" id="thinking-${paneId}">
                    <div class="message-avatar assistant">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="18" height="18">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                        </svg>
                    </div>
                    <div class="message-content">
                        <div class="thinking-indicator">
                            <span class="thinking-dot"></span>
                            <span class="thinking-dot"></span>
                            <span class="thinking-dot"></span>
                        </div>
                    </div>
                </div>
            </div>
            <div class="chat-input-container">
                <div class="chat-input-wrapper">
                    <textarea 
                        id="chatInput-${paneId}" 
                        class="chat-input" 
                        placeholder="Enter message to continue..."
                        rows="1"
                        disabled
                    ></textarea>
                    <button class="chat-send-btn" data-pane="${paneId}" disabled>
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="18" height="18">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
                        </svg>
                    </button>
                </div>
            </div>
        `;

        // Scroll to bottom
        const messagesContainer = document.getElementById(`chatMessages-${paneId}`);
        if (messagesContainer) {
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }

        try {
            const aliasValue = (alias || '').trim() || agentType;
            // Build legacy (易事厅) request payload 
            // The backend auto-detects protocol, default is legacy format
            const payload = {
                content: message,
                user: execUser,
                session_id: sessionId,
                msg_type: 'text',
                provider: agentType,
                alias: aliasValue,
                forwardedProps: { alias: aliasValue },
            };

            // Call streaming API
            const hadContent = await this.streamChatResponse(paneId, execUser, payload, `thinking-${paneId}`);
            
            // After successful response, set current session and reload everything
            const activeTabId = this.getActiveTabId(paneId);
            if (activeTabId) {
                this.currentSessionByTab[activeTabId] = sessionId;
                const tab = this.getActiveTab(paneId);
                if (tab) {
                    tab.data = tab.data || {};
                    tab.data.sessionId = sessionId;
                }
            }
            
            // Reload sessions list (sidebar only, does NOT touch the chat detail area)
            await this.loadSessions(paneId);

            // Do NOT call loadMessages here.
            // The streaming response has already rendered content (or error) in the DOM.
            // Calling loadMessages after a new session risks a 404 (session not yet
            // persisted) which triggers showNewSessionView and wipes the streamed content.
            
        } catch (error) {
            this._clearPendingNewSession(paneId, sessionId);
            console.error('Failed to create session:', error);
            this.app.showToast(error.message || 'Failed to create session', 'error');
            
            // Show error in thinking area
            const thinkingEl = document.getElementById(`thinking-${paneId}`);
            if (thinkingEl) {
                thinkingEl.innerHTML = `
                    <div class="message-avatar assistant">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="18" height="18">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                        </svg>
                    </div>
                    <div class="message-content">
                        <div class="message-error">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="16" height="16">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                            </svg>
                            <span>${this.escapeHtml(error.message || 'Request failed')}</span>
                            <button class="retry-btn" onclick="nexusApp.chatView.showNewSessionView('${paneId}')">Retry</button>
                        </div>
                    </div>
                `;
            }
        }
    }

    async streamChatResponse(paneId, execUser, payload, thinkingId) {
        // Mark this pane as actively streaming via fetch (prevent auto-refresh from overwriting DOM)
        this._chatStreaming[paneId] = true;

        const messagesContainer = document.getElementById(`chatMessages-${paneId}`);
        const thinkingEl = document.getElementById(thinkingId);

        // Keep the thinking indicator visible until the first real content arrives.
        // We lazily swap it for the streaming bubble on first content event.
        let bubbleEl = null;
        let bubbleInitialized = false;
        let currentTextEl = null;
        let currentTextContent = '';
        let textSegmentIndex = 0;
        const streamingToolCalls = new Map();

        const initBubble = () => {
            if (bubbleInitialized) return;
            bubbleInitialized = true;
            if (thinkingEl) {
                thinkingEl.innerHTML = `
                    <div class="message-avatar">A</div>
                    <div class="message-content">
                        <div class="message-bubble streaming-bubble" id="streaming-bubble-${thinkingId}"></div>
                    </div>
                `;
            }
            bubbleEl = document.getElementById(`streaming-bubble-${thinkingId}`);
        };

        const ensureTextElement = () => {
            if (!currentTextEl) {
                initBubble();
                if (bubbleEl) {
                    const textId = `streaming-content-${thinkingId}-seg${textSegmentIndex}`;
                    bubbleEl.insertAdjacentHTML('beforeend', `<div class="message-text streaming" id="${textId}"></div>`);
                    currentTextEl = document.getElementById(textId);
                }
            }
            return currentTextEl;
        };

        const appendText = (value) => {
            if (value === undefined || value === null) return;
            const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
            if (!text) return;
            const textEl = ensureTextElement();
            currentTextContent += text;
            if (textEl) {
                textEl.innerHTML = this.formatMessageContent(currentTextContent);
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            }
        };

        const endCurrentTextSegment = () => {
            if (currentTextEl) {
                currentTextEl.classList.remove('streaming');
            }
            currentTextEl = null;
            currentTextContent = '';
            textSegmentIndex++;
        };

        const processDataEvent = (data, eventType) => {
            console.log('[processDataEvent]', data.type || eventType, data);
            const sseDelta = data.response ?? data.delta;
            const aguiText = data.delta ?? data.content ?? data.text ?? data.response;

            if (eventType === 'delta' && sseDelta !== undefined) {
                appendText(sseDelta);
                if (data.finished === true) endCurrentTextSegment();
                return;
            }

            if (data.type === 'RUN_STARTED') {
                // Session is now running — refresh the session list so status badge updates
                console.log('[processDataEvent] RUN_STARTED - refreshing sessions');
                this.loadSessions(paneId);
                return;
            }

            if (data.type === 'TEXT_MESSAGE_START') {
                console.log('[processDataEvent] TEXT_MESSAGE_START - initBubble');
                initBubble();
                return;
            }

            if (data.type === 'TEXT_MESSAGE_CONTENT') {
                console.log('[processDataEvent] TEXT_MESSAGE_CONTENT:', aguiText?.substring(0, 50));
                appendText(aguiText);
                return;
            }

            if (data.type === 'TEXT_MESSAGE_END') {
                endCurrentTextSegment();
                return;
            }

            if (data.type === 'result') {
                appendText(data.content ?? data.result);
                return;
            }

            if (data.type === 'TOOL_CALL_START') {
                const toolCallId = data.toolCallId || `tool-${Date.now()}`;
                const toolName = data.toolCallName || 'Tool';
                const toolTitle = this.formatToolCallTitle(toolName, {}, '');
                streamingToolCalls.set(toolCallId, { name: toolName, args: '', status: 'executing', result: '' });
                endCurrentTextSegment();
                initBubble();
                if (bubbleEl) {
                    bubbleEl.insertAdjacentHTML('beforeend', this.renderStreamingToolCall(toolCallId, toolTitle, 'executing'));
                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                }
                return;
            }

            if (data.type === 'TOOL_CALL_ARGS') {
                const toolCallId = data.toolCallId;
                const argsDelta = data.delta || '';
                if (toolCallId && streamingToolCalls.has(toolCallId)) {
                    const tc = streamingToolCalls.get(toolCallId);
                    tc.args += argsDelta;
                    const argsEl = document.getElementById(`streaming-tool-args-${toolCallId}`);
                    if (argsEl) argsEl.textContent = tc.args;

                    const titleEl = document.querySelector(`[data-streaming-tool-id="${toolCallId}"] .tool-call-name`);
                    if (titleEl) {
                        titleEl.textContent = this.formatToolCallTitle(tc.name, {}, tc.args);
                    }
                }
                return;
            }

            if (data.type === 'TOOL_CALL_END' || data.type === 'TOOL_CALL_RESULT') {
                const toolCallId = data.toolCallId;
                const result = data.result || data.content || '';
                const error = data.error;
                if (toolCallId && streamingToolCalls.has(toolCallId)) {
                    const tc = streamingToolCalls.get(toolCallId);
                    if (data.type === 'TOOL_CALL_END') {
                        tc.status = error ? 'failed' : 'completed';
                    }
                    tc.result = result;

                    const statusEl = document.querySelector(`[data-streaming-tool-id="${toolCallId}"] .tool-call-status-icon`);
                    if (statusEl && data.type === 'TOOL_CALL_END') {
                        statusEl.textContent = error ? '✗' : '✓';
                        statusEl.parentElement.style.color = error ? 'var(--error)' : 'var(--success)';
                    }

                    const titleEl = document.querySelector(`[data-streaming-tool-id="${toolCallId}"] .tool-call-name`);
                    if (titleEl) {
                        titleEl.textContent = data.toolCallDisplayName || this.formatToolCallTitle(tc.name, {}, tc.args);
                    }

                    const resultSection = document.getElementById(`streaming-tool-result-section-${toolCallId}`);
                    const resultEl = document.getElementById(`streaming-tool-result-${toolCallId}`);
                    if (resultSection && resultEl && result) {
                        resultSection.style.display = 'block';
                        resultEl.textContent = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
                    }

                    if (error) {
                        const errorSection = document.getElementById(`streaming-tool-error-section-${toolCallId}`);
                        const errorEl = document.getElementById(`streaming-tool-error-${toolCallId}`);
                        if (errorSection && errorEl) {
                            errorSection.style.display = 'block';
                            errorEl.textContent = error;
                        }
                    }

                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                }
                return;
            }

            if (data.delta && !data.type) {
                appendText(data.delta);
                return;
            }

            if (data.type === 'RUN_FINISHED') {
                endCurrentTextSegment();
                // Refresh session list so status updates to completed
                this.loadSessions(paneId);
                return;
            }

            if (data.type === 'RUN_ERROR' || data.error) {
                const errorMsg = data.message || data.error || 'Stream error';
                // Display error in UI instead of throwing (which can be swallowed)
                endCurrentTextSegment();
                initBubble();
                if (bubbleEl) {
                    bubbleEl.insertAdjacentHTML('beforeend', `
                        <div class="message-error" style="margin-top: 8px;">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="16" height="16">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                            </svg>
                            <span>${this.escapeHtml(errorMsg)}</span>
                        </div>
                    `);
                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                }
                return;
            }
        };

        const processSSEEvent = (rawEvent) => {
            if (!rawEvent || !rawEvent.trim()) return;
            const lines = rawEvent.split('\n');
            let eventType = '';
            const dataLines = [];
            for (let line of lines) {
                // Strip trailing \r (from \r\n line endings)
                if (line.endsWith('\r')) line = line.slice(0, -1);
                if (line.startsWith('event:')) {
                    eventType = line.slice(6).trim();
                } else if (line.startsWith('data:')) {
                    // Keep original payload as much as possible (only strip one optional leading space)
                    let payloadLine = line.slice(5);
                    if (payloadLine.startsWith(' ')) payloadLine = payloadLine.slice(1);
                    dataLines.push(payloadLine);
                }
            }
            const eventData = dataLines.join('\n').trim();
            if (!eventData || eventData === '[DONE]') return;
            let data;
            try {
                data = JSON.parse(eventData);
            } catch (parseErr) {
                // Fallback: treat plain-text SSE payload as stream error content.
                processDataEvent({ type: 'RUN_ERROR', message: eventData }, eventType);
                return;
            }
            processDataEvent(data, eventType);
        };

        const decoder = new TextDecoder();
        let reader = null;
        let buffer = '';

        try {
            console.log('[streamChatResponse] fetching chat stream...', { paneId, execUser, thinkingId });
            const response = await NexusAPI.chatStream(execUser, payload);
            console.log('[streamChatResponse] got response, getting reader...');
            reader = response.body?.getReader() || null;

            if (!reader) {
                throw new Error('No response body');
            }

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                const chunk = decoder.decode(value, { stream: true });
                console.log('[streamChatResponse] chunk received:', chunk.length, 'bytes');
                buffer += chunk;
                const events = buffer.split(/\r?\n\r?\n/);
                buffer = events.pop() || '';
                for (const event of events) {
                    console.log('[streamChatResponse] processing SSE event:', event.substring(0, 100));
                    processSSEEvent(event);
                }
            }
            if (buffer.trim()) {
                console.log('[streamChatResponse] processing final buffer');
                processSSEEvent(buffer);
            }
        } finally {
            if (reader) reader.releaseLock();
            // Clear streaming flag so auto-refresh can work again
            this._chatStreaming[paneId] = false;
        }

        if (currentTextEl) {
            currentTextEl.classList.remove('streaming');
        }

        if (bubbleEl) {
            bubbleEl.querySelectorAll('.message-text:empty').forEach(el => el.remove());
        }

        // If streaming produced no visible content, auto-reload messages from backend
        // This handles cases where backend events were persisted but not rendered by parser
        const hasContent = bubbleEl && bubbleEl.textContent && bubbleEl.textContent.trim().length > 0;
        if (!hasContent && payload.session_id) {
            console.log('[streamChatResponse] No content rendered during stream, fallback to snapshot reload');
            const sessionId = payload.session_id;
            // Retry a few times for short persistence lag
            for (let i = 0; i < 4; i++) {
                try {
                    const data = await NexusAPI.getSessionMessages(sessionId);
                    const msgCount = (data.messages || []).length;
                    if (msgCount > 0 || i === 3) {
                        this.renderMessages(paneId, sessionId, data);
                        break;
                    }
                } catch (e) {
                    if (i === 3) {
                        console.warn('[streamChatResponse] fallback snapshot reload failed:', e);
                    }
                }
                await new Promise(r => setTimeout(r, 300));
            }
        }

        const textarea = document.getElementById(`chatInput-${paneId}`);
        const sendBtn = document.querySelector(`.chat-send-btn[data-pane="${paneId}"]`);
        if (textarea) textarea.disabled = false;
        if (sendBtn) sendBtn.disabled = false;

        return hasContent;
    }

    buildTodoToolDisplayName(todosValue) {
        if (todosValue === undefined || todosValue === null || todosValue === '') return '';

        let todos = todosValue;
        if (typeof todos === 'string') {
            try {
                todos = JSON.parse(todos);
            } catch (_) {
                return '';
            }
        }

        if (!Array.isArray(todos) || todos.length === 0) return '';

        const total = todos.length;
        const currentIndex = todos.findIndex(todo => todo && typeof todo === 'object' && todo.status === 'in_progress');
        if (currentIndex >= 0) {
            const currentContent = String(todos[currentIndex]?.content || '').trim();
            return currentContent
                ? `Todos: ${currentIndex + 1}/${total} - ${currentContent}`
                : `Todos: ${currentIndex + 1}/${total}`;
        }

        return `Todos: ${total} items`;
    }

    buildToolDisplayName(toolName, params = {}) {
        const name = toolName || 'Tool Call';
        if (!params || typeof params !== 'object') return name;

        const normalizedName = typeof name === 'string' ? name.trim().toLowerCase() : '';

        if (normalizedName === 'task') {
            const subagent = params.subagent_type || params.subagent_name || '';
            const desc = params.description || '';
            if (subagent && desc) return `Task: ${subagent} - ${desc}`;
            if (subagent) return `Task: ${subagent}`;
            if (desc) return `Task: ${desc}`;
        }

        if (normalizedName === 'skill' || normalizedName === 'use_skill') {
            const skill = params.skill || params.command || '';
            if (skill) return `Skill: ${skill}`;
        }

        if (normalizedName === 'read' || normalizedName === 'read_file') {
            const fp = params.file_path || params.filePath || '';
            if (fp) return `Read: ${fp}`;
        }

        if (normalizedName === 'write' || normalizedName === 'write_to_file') {
            const fp = params.file_path || params.filePath || '';
            if (fp) return `Write: ${fp}`;
        }

        if (normalizedName === 'edit' || normalizedName === 'replace_in_file' || normalizedName === 'apply_patch') {
            const fp = params.file_path || params.filePath || '';
            if (fp) return `Edit: ${fp}`;
        }

        if (normalizedName === 'grep' || normalizedName === 'search_content') {
            const path = params.path || params.directory || '';
            if (path) return `Grep: ${path}`;
        }

        if (normalizedName === 'glob' || normalizedName === 'search_file') {
            const path = params.path || params.target_directory || '';
            const pattern = params.pattern || '';
            if (path && pattern) return `Glob: ${pattern} in ${path}`;
            if (path) return `Glob: ${path}`;
            if (pattern) return `Glob: ${pattern}`;
        }

        if (normalizedName === 'bash' || normalizedName === 'execute_command') {
            const explanation = params.explanation || params.description || '';
            if (explanation) return `Bash: ${explanation}`;
            const command = params.command || '';
            if (command) return `Bash: ${command.length > 60 ? `${command.slice(0, 60)}…` : command}`;
        }

        if (normalizedName === 'todowrite' || normalizedName === 'todo_write') {
            const todoTitle = this.buildTodoToolDisplayName(params.todos);
            if (todoTitle) return todoTitle;
        }

        if (normalizedName === 'websearch' || normalizedName === 'web_search') {
            const query = params.query || params.searchTerm || '';
            if (query) return `Search: ${query.length > 60 ? `${query.slice(0, 60)}…` : query}`;
        }

        if (normalizedName === 'webfetch' || normalizedName === 'web_fetch') {
            const url = params.url || '';
            if (url) return `Fetch: ${url.length > 60 ? `${url.slice(0, 60)}…` : url}`;
        }

        return name;
    }

    extractPartialToolParams(argsString) {
        if (typeof argsString !== 'string' || !argsString.trim()) return {};
        const extracted = {};
        const keys = ['explanation', 'description', 'command', 'searchTerm', 'query', 'pattern', 'filePath', 'file_path', 'path', 'directory', 'target_directory'];
        for (const key of keys) {
            const m = argsString.match(new RegExp(`"${key}"\\s*:\\s*"([^\\"]*)`));
            if (m && m[1]) {
                extracted[key] = m[1].replace(/\\n/g, ' ').replace(/\\t/g, ' ').trim();
            }
        }

        const todosMatch = argsString.match(/"todos"\s*:\s*"((?:\\.|[^"\\])*)"/s);
        if (todosMatch && todosMatch[1]) {
            extracted.todos = todosMatch[1]
                .replace(/\\n/g, ' ')
                .replace(/\\t/g, ' ')
                .replace(/\\"/g, '"')
                .trim();
        }

        return extracted;
    }

    parseToolCallParams(args, argsString) {
        if (args && typeof args === 'object' && Object.keys(args).length > 0) {
            return args;
        }
        if (typeof argsString === 'string' && argsString.trim()) {
            try {
                const parsed = JSON.parse(argsString);
                if (parsed && typeof parsed === 'object') return parsed;
            } catch (_) {
                return this.extractPartialToolParams(argsString);
            }
        }
        return {};
    }

    formatToolCallTitle(toolName, args, argsString = '') {
        const params = this.parseToolCallParams(args, argsString);
        return this.buildToolDisplayName(toolName || 'Tool Call', params);
    }
    
    /**
     * Render a streaming tool call UI element (simplified version for real-time display)
     */
    renderStreamingToolCall(toolCallId, toolName, status = 'executing') {
        const statusConfig = {
            pending: { icon: '⏳', color: 'var(--text-muted)' },
            executing: { icon: '▶️', color: 'var(--primary-500)' },
            completed: { icon: '✓', color: 'var(--text-muted)' },
            failed: { icon: '✗', color: 'var(--error)' }
        };
        const cfg = statusConfig[status] || statusConfig.executing;
        
        return `
            <div class="tool-call" data-streaming-tool-id="${toolCallId}">
                <div class="tool-call-header" onclick="this.closest('.tool-call').classList.toggle('expanded')">
                    <div class="tool-call-status" style="color: ${cfg.color}">
                        <span class="tool-call-status-icon">${cfg.icon}</span>
                    </div>
                    <svg class="tool-call-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                    </svg>
                    <span class="tool-call-name">${this.escapeHtml(toolName)}</span>
                    <svg class="tool-call-toggle" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </div>
                <div class="tool-call-body">
                    <div class="tool-call-section">
                        <div class="tool-call-section-header">
                            <span class="tool-call-section-title">Input</span>
                        </div>
                        <div class="tool-call-content" id="streaming-tool-args-${toolCallId}"></div>
                    </div>
                    <div class="tool-call-section" id="streaming-tool-result-section-${toolCallId}" style="display: none;">
                        <div class="tool-call-section-header">
                            <span class="tool-call-section-title">Output</span>
                        </div>
                        <div class="tool-call-content tool-call-result" id="streaming-tool-result-${toolCallId}"></div>
                    </div>
                    <div class="tool-call-section" id="streaming-tool-error-section-${toolCallId}" style="display: none;">
                        <div class="tool-call-section-header">
                            <span class="tool-call-section-title" style="color: var(--error);">Error</span>
                        </div>
                        <div class="tool-call-content tool-call-error" id="streaming-tool-error-${toolCallId}"></div>
                    </div>
                </div>
            </div>
        `;
    }

    async loadSessions(paneId) {
        const container = document.getElementById(`sessionItems-${paneId}`);
        if (!container) return;

        const isHistory = this.sessionSource[paneId] === 'history';
        const isHistoryProjects = isHistory && this.historyViewMode[paneId] === 'projects';
        const searchInput = document.querySelector(`.session-search-input:not(.history-path-input)[data-pane="${paneId}"]`);
        const globalUserFilter = document.getElementById('globalUserFilter');

        try {
            // History projects listing mode
            if (isHistoryProjects) {
                container.innerHTML = '<div class="empty-state"><div class="loading-spinner"></div></div>';
                const customPaths = this.app.getAliasHistoryConfigPaths();
                const projects = await NexusAPI.getHistoryProjects({
                    execUser: globalUserFilter?.value ?? '',
                    customPaths: Object.keys(customPaths).length ? customPaths : undefined,
                });
                this.historyProjects[paneId] = projects || [];
                this.renderHistoryProjects(paneId);
                return;
            }

            let data;

            if (isHistory) {
                const projectPath = (this.historyProjectPath[paneId] || '').trim();
                if (!projectPath) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <p class="empty-state-title">Enter a project path</p>
                            <p class="empty-state-text">Type the workspace path above and press Enter to load history sessions</p>
                        </div>
                    `;
                    return;
                }
                const providerFilter = document.querySelector(`.history-provider-filter[data-pane="${paneId}"]`);
                const customPaths = this.app.getAliasHistoryConfigPaths();
                data = await NexusAPI.getHistorySessions({
                    projectPath: projectPath,
                    pageSize: 50,
                    search: searchInput?.value || '',
                    provider: providerFilter?.value || '',
                    execUser: globalUserFilter?.value ?? '',
                    customPaths: Object.keys(customPaths).length ? customPaths : undefined,
                });
            } else {
                const statusFilter = document.querySelector(`.session-filter-select[data-pane="${paneId}"][data-filter="status"]`);
                data = await NexusAPI.getSessions({
                    pageSize: 50,
                    search: searchInput?.value || '',
                    status: statusFilter?.value || '',
                    username: globalUserFilter?.value || ''
                });
            }

            this.sessions[paneId] = data.sessions || [];
            const pending = this._pendingNewSession[paneId];
            if (pending && this.sessions[paneId].some(s => s.id === pending.id)) {
                this._clearPendingNewSession(paneId, pending.id);
            }
            this.sessionTotals = this.sessionTotals || {};
            this.sessionTotals[paneId] = data.total || this.sessions[paneId].length;
            this.renderSessionList(paneId);
        } catch (error) {
            console.error('Failed to load sessions:', error);
            container.innerHTML = `
                <div class="empty-state">
                    <p class="empty-state-text" style="color: var(--error)">Failed to load sessions</p>
                </div>
            `;
        }
    }

    renderSessionList(paneId) {
        const container = document.getElementById(`sessionItems-${paneId}`);
        if (!container) return;

        const sessions = this.sessions[paneId] || [];
        
        if (sessions.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <svg class="empty-state-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"/>
                    </svg>
                    <p class="empty-state-title">No sessions found</p>
                    <p class="empty-state-text">Sessions will appear here</p>
                </div>
            `;
            return;
        }

        // Group sessions by date
        const groups = this.groupSessionsByDate(sessions);
        
        container.innerHTML = Object.entries(groups).map(([label, items]) => `
            <div class="session-group">
                <div class="session-group-title">${label}</div>
                ${items.map(session => this.renderSessionItem(session, paneId)).join('')}
            </div>
        `).join('');

        // Bind click events
        container.querySelectorAll('.session-item').forEach(item => {
            item.addEventListener('click', (e) => {
                // Don't select session if clicking on checkbox area
                if (e.target.closest('.session-item-checkbox')) {
                    return;
                }
                this.selectSession(paneId, item.dataset.sessionId);
            });
        });

        // Bind checkbox events (for selection mode)
        container.querySelectorAll('.session-item-checkbox input[type="checkbox"]').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                e.stopPropagation();
                const sessionId = checkbox.closest('.session-item-checkbox').dataset.sessionId;
                this.toggleSessionSelection(paneId, sessionId);
            });
        });
    }

    renderHistoryProjects(paneId) {
        const container = document.getElementById(`sessionItems-${paneId}`);
        if (!container) return;

        const projects = this.historyProjects[paneId] || [];

        if (projects.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <svg class="empty-state-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
                    </svg>
                    <p class="empty-state-title">No history projects found</p>
                    <p class="empty-state-text">No CLI session history was found. Use Claude Code, CodeBuddy, Codex, or Gemini CLI in your projects first.</p>
                </div>
            `;
            return;
        }

        container.innerHTML = projects.map(project => {
            const providerBadges = (project.providers || []).map(p =>
                `<span style="display:inline-block;font-size:10px;padding:1px 5px;border-radius:3px;background:var(--bg-tertiary,#333);color:var(--text-secondary);margin-right:3px;">${this.escapeHtml(p.alias || p.provider)}</span>`
            ).join('');

            const timeStr = this.formatTime(project.last_active);
            const sessionCount = project.total_sessions || 0;
            const isGeminiOnly = project.path.startsWith('[gemini:');
            const displayPath = isGeminiOnly ? project.path : project.path;
            // Show just the last 2 segments for compact display
            const parts = project.path.split('/');
            const shortPath = parts.length > 2 ? '.../' + parts.slice(-2).join('/') : project.path;

            return `
                <div class="session-item history-project-item" data-project-path="${this.escapeHtml(project.path)}"
                     ${project.gemini_hash ? `data-gemini-hash="${this.escapeHtml(project.gemini_hash)}"` : ''}
                     style="cursor:pointer;">
                    <div class="session-item-content">
                        <div class="session-item-header">
                            <span class="session-item-title" style="font-family:var(--font-mono,monospace);font-size:12px;" title="${this.escapeHtml(project.path)}">${this.escapeHtml(shortPath)}</span>
                            <span class="session-item-time">${timeStr}</span>
                        </div>
                        <p class="session-item-preview" style="font-family:var(--font-mono,monospace);font-size:11px;opacity:0.7;">${this.escapeHtml(project.path)}</p>
                        <div class="session-item-meta">
                            ${providerBadges}
                            <span style="font-size:11px;color:var(--text-tertiary);">${sessionCount} session${sessionCount !== 1 ? 's' : ''}</span>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        // Bind click events to select a project
        container.querySelectorAll('.history-project-item').forEach(item => {
            item.addEventListener('click', () => {
                const projectPath = item.dataset.projectPath;
                if (projectPath && !projectPath.startsWith('[gemini:')) {
                    this.historyProjectPath[paneId] = projectPath;
                    this.historyViewMode[paneId] = 'sessions';
                    const tab = this.getActiveTab(paneId);
                    const outerContainer = document.getElementById(`sessionList-${paneId}`)?.parentElement?.parentElement;
                    if (outerContainer) {
                        this.render(paneId, tab, outerContainer);
                    }
                }
            });
        });
    }

    renderSessionItem(session, paneId) {
        const isHistory = this.sessionSource[paneId] === 'history';
        const statusClass = ['running', 'pending', 'queued'].includes(session.status) ? 'running' :
                           session.status === 'error' ? 'error' : 'completed';
        const timeStr = this.formatTime(session.updated_at || session.created_at);
        const activeTabId = this.getActiveTabId(paneId);
        const isActive = activeTabId ? this.currentSessionByTab[activeTabId] === session.id : false;
        const isInSelectionMode = this.selectionMode[paneId];
        const isChecked = this.selectedSessionIds[paneId]?.has(session.id);

        const providerBadge = isHistory && session.provider
            ? `<span style="display:inline-block;font-size:10px;padding:1px 5px;border-radius:3px;background:var(--bg-tertiary,#333);color:var(--text-secondary);margin-right:4px;font-weight:500;">${this.escapeHtml(session.alias || session.provider)}</span>`
            : '';
        const sourceBadge = isHistory
            ? `<span style="display:inline-block;font-size:9px;padding:1px 4px;border-radius:3px;background:var(--warning,#f0ad4e);color:#000;margin-right:4px;">history</span>`
            : '';

        return `
            <div class="session-item ${isActive ? 'active' : ''} ${isChecked ? 'checked' : ''}"
                 data-session-id="${session.id}"
                 data-provider="${this.escapeHtml(session.provider || '')}"
                 data-alias="${this.escapeHtml(session.alias || '')}"
                 data-source="${isHistory ? 'history' : 'runtime'}"
                 data-status="${session.status || 'idle'}">
                ${isInSelectionMode ? `
                    <div class="session-item-checkbox" data-session-id="${session.id}">
                        <input type="checkbox" ${isChecked ? 'checked' : ''}>
                    </div>
                ` : ''}
                <div class="session-item-content">
                    <div class="session-item-header">
                        <span class="session-item-title">${providerBadge}${this.escapeHtml(session.title || session.id)}</span>
                        <span class="session-item-time">${timeStr}</span>
                    </div>
                    ${session.last_message ? `<p class="session-item-preview">${this.escapeHtml(session.last_message)}</p>` : ''}
                    <div class="session-item-meta">
                        ${isHistory ? sourceBadge : `
                            <span class="session-item-status ${statusClass}">
                                <span class="status-dot"></span>
                                ${session.status || 'idle'}
                            </span>
                        `}
                        ${session.username ? `<span>@${session.username}${session.provider ? ' / ' + session.provider : ''}</span>` : ''}
                        ${isHistory && session.message_count ? `<span>${session.message_count} msgs</span>` : ''}
                    </div>
                    ${!isHistory && session.exec_dir ? `
                    <div class="session-item-details" style="font-size:10px;color:var(--text-tertiary,#666);margin-top:2px;line-height:1.4;word-break:break-all;">
                        <span style="opacity:0.7;" title="${this.escapeHtml(session.exec_dir)}">📂 ${this.escapeHtml(session.exec_dir.split('/').slice(-2).join('/'))}</span>
                    </div>
                    ` : ''}
                </div>
            </div>
        `;
    }

    async selectSession(paneId, sessionId, options = {}) {
        const activeTabId = this.getActiveTabId(paneId);
        if (activeTabId) {
            this.currentSessionByTab[activeTabId] = sessionId;
            const tab = this.getActiveTab(paneId);
            if (tab) {
                tab.data = tab.data || {};
                tab.data.sessionId = sessionId;
            }
        }
        
        // Update active state in list
        const container = document.getElementById(`sessionItems-${paneId}`);
        container?.querySelectorAll('.session-item').forEach(item => {
            item.classList.toggle('active', item.dataset.sessionId === sessionId);
        });

        // Get provider info from the clicked item (for history sessions)
        const sessionItem = container?.querySelector(`.session-item[data-session-id="${sessionId}"]`);
        const provider = sessionItem?.dataset.provider || '';
        const alias = sessionItem?.dataset.alias || '';
        const source = sessionItem?.dataset.source || this.sessionSource[paneId] || 'runtime';

        // Update URL hash so session ID is visible in address bar & bookmarkable
        history.replaceState(null, '', `#${sessionId}`);

        // A just-created runtime session may not be queryable immediately.
        // Avoid forcing loadMessages(404) that would wipe current streamed DOM.
        if (!sessionItem && source === 'runtime' && this._isPendingNewSession(paneId, sessionId)) {
            return;
        }

        // Load and display messages
        await this.loadMessages(paneId, sessionId, { provider, alias, source });
    }

    async loadMessages(paneId, sessionId, options = {}) {
        const detail = document.getElementById(`chatDetail-${paneId}`);
        if (!detail) return;

        const source = options.source || this.sessionSource[paneId] || 'runtime';
        if (source === 'runtime' && this._isPendingNewSession(paneId, sessionId)) {
            // Keep currently streamed DOM untouched during short persistence window.
            return;
        }

        // Close previous task session stream (if any)
        this._closeTaskSessionStream(paneId);

        detail.innerHTML = `
            <div class="empty-state">
                <div class="loading-spinner"></div>
            </div>
        `;

        // Task sessions: use SSE stream only when task is still running/pending;
        // completed/failed tasks load from Redis snapshot directly (faster, no 404 risk)
        if (/^task_[A-Za-z0-9_-]+$/.test(sessionId)) {
            const container = document.getElementById(`sessionItems-${paneId}`);
            const sessionItem = container?.querySelector(`.session-item[data-session-id="${sessionId}"]`);
            const sessionStatus = sessionItem?.dataset.status || '';
            const isActive = ['running', 'pending', 'queued'].includes(sessionStatus);
            if (isActive) {
                await this._streamTaskSessionMessages(paneId, sessionId);
                return;
            }
            // Completed/failed tasks: fall through to normal snapshot loading below
        }

        // Channel sessions (e.g. channel_wecom_*): use SSE stream when running
        if (source === 'runtime' && !/^task_/.test(sessionId)) {
            const container = document.getElementById(`sessionItems-${paneId}`);
            const sessionItem = container?.querySelector(`.session-item[data-session-id="${sessionId}"]`);
            const sessionMeta = this.getSessionMeta(paneId, sessionId);
            const sessionStatus = sessionItem?.dataset.status || sessionMeta?.status || '';
            if (['running', 'pending', 'queued'].includes(sessionStatus)) {
                await this._streamChannelSessionMessages(paneId, sessionId);
                return;
            }
        }

        try {
            let data;
            if (source === 'history' && options.provider) {
                // Use the alias (e.g. "claude-internal") or provider for the history API
                const providerKey = options.alias || options.provider;
                const globalUserFilter = document.getElementById('globalUserFilter');
                const cfg = this.app.getAliasConfigPath(providerKey);
                data = await NexusAPI.getHistoryMessages(providerKey, sessionId, {
                    execUser: globalUserFilter?.value ?? '',
                    configPath: cfg || undefined,
                });
            } else {
                data = await NexusAPI.getSessionMessages(sessionId);
            }
            this.renderMessages(paneId, sessionId, data);
        } catch (error) {
            console.error('Failed to load messages:', error);
            const isNotFound = /not found|404/i.test(error.message || '');
            if (isNotFound) {
                if (source === 'runtime' && this._isPendingNewSession(paneId, sessionId)) {
                    // Backend has not persisted the new session yet; avoid wiping streamed content.
                    return;
                }
                // Session was deleted or expired — reset to initial view
                if (location.hash) history.replaceState(null, '', location.pathname);
                this.showNewSessionView(paneId);
                return;
            }
            detail.innerHTML = `
                <div class="empty-state">
                    <p class="empty-state-text" style="color: var(--error)">Failed to load messages</p>
                </div>
            `;
        }
    }

    _closeTaskSessionStream(paneId) {
        const es = this.taskSessionStreams[paneId];
        if (es) {
            try { es.close(); } catch {}
            delete this.taskSessionStreams[paneId];
        }
    }

    async _streamTaskSessionMessages(paneId, sessionId) {
        const taskId = sessionId.replace(/^task_/, '');
        const globalUserFilter = document.getElementById('globalUserFilter');
        const execUser = globalUserFilter?.value || NexusAPI.getDefaultExecUser();

        // Render a basic chat shell first
        this.renderMessages(paneId, sessionId, {
            session: { title: sessionId },
            messages: [],
            tool_calls: [],
        });

        const messagesContainer = document.getElementById(`chatMessages-${paneId}`);
        if (!messagesContainer) return;
        messagesContainer.innerHTML = `
            <div class="empty-state" style="padding: 24px;">
                <div class="loading-spinner"></div>
                <p class="empty-state-text" style="margin-top:8px;">Loading task stream...</p>
            </div>
        `;

        const es = NexusAPI.streamTaskMessages(taskId, { execUser, tail: 5000 });
        this.taskSessionStreams[paneId] = es;

        let bubbleEl = null;
        let currentTextEl = null;
        let currentTextContent = '';
        let textSegmentIndex = 0;
        const streamingToolCalls = new Map();
        let initialized = false;
        let done = false;

        const ensureBubble = () => {
            if (!bubbleEl) {
                if (!initialized) {
                    messagesContainer.innerHTML = '';
                    initialized = true;
                }
                const msgId = `task-session-stream-${paneId}-${Date.now()}`;
                messagesContainer.insertAdjacentHTML('beforeend', `
                    <div class="message assistant" id="${msgId}">
                        <div class="message-avatar assistant">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="18" height="18">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                            </svg>
                        </div>
                        <div class="message-content">
                            <div class="message-bubble streaming-bubble" id="task-session-bubble-${msgId}"></div>
                        </div>
                    </div>
                `);
                bubbleEl = document.getElementById(`task-session-bubble-${msgId}`);
            }
            return bubbleEl;
        };

        const ensureTextElement = () => {
            if (!currentTextEl) {
                const bubble = ensureBubble();
                if (bubble) {
                    const textId = `task-session-content-${paneId}-seg${textSegmentIndex}`;
                    bubble.insertAdjacentHTML('beforeend', `<div class="message-text streaming" id="${textId}"></div>`);
                    currentTextEl = document.getElementById(textId);
                }
            }
            return currentTextEl;
        };

        es.onmessage = (event) => {
            if (done) return;
            let data;
            try {
                data = JSON.parse(event.data);
            } catch {
                return;
            }

            if (data.type === 'TEXT_MESSAGE_START') {
                ensureBubble();
            } else if (data.type === 'TEXT_MESSAGE_CONTENT') {
                const textDelta = data.delta ?? data.content ?? data.text ?? data.response;
                if (textDelta !== undefined && textDelta !== null && textDelta !== '') {
                    const textEl = ensureTextElement();
                    currentTextContent += (typeof textDelta === 'string' ? textDelta : JSON.stringify(textDelta, null, 2));
                    if (textEl) {
                        textEl.innerHTML = this.formatMessageContent(currentTextContent);
                        messagesContainer.scrollTop = messagesContainer.scrollHeight;
                    }
                }
            } else if (data.type === 'TEXT_MESSAGE_END') {
                if (currentTextEl) currentTextEl.classList.remove('streaming');
                currentTextEl = null;
                currentTextContent = '';
                textSegmentIndex++;
            } else if (data.type === 'TOOL_CALL_START') {
                const toolCallId = data.toolCallId || `tool-${Date.now()}`;
                const toolName = data.toolCallName || 'Tool';
                const toolTitle = this.formatToolCallTitle(toolName, {}, '');
                streamingToolCalls.set(toolCallId, { name: toolName, args: '', status: 'executing', result: '' });

                if (currentTextEl) currentTextEl.classList.remove('streaming');
                currentTextEl = null;
                currentTextContent = '';
                textSegmentIndex++;

                const bubble = ensureBubble();
                if (bubble) {
                    bubble.insertAdjacentHTML('beforeend', this.renderStreamingToolCall(toolCallId, toolTitle, 'executing'));
                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                }
            } else if (data.type === 'TOOL_CALL_ARGS') {
                const toolCallId = data.toolCallId;
                const argsDelta = data.delta || '';
                if (toolCallId && streamingToolCalls.has(toolCallId)) {
                    const tc = streamingToolCalls.get(toolCallId);
                    tc.args += argsDelta;
                    const argsEl = document.getElementById(`streaming-tool-args-${toolCallId}`);
                    if (argsEl) argsEl.textContent = tc.args;

                    const titleEl = document.querySelector(`[data-streaming-tool-id="${toolCallId}"] .tool-call-name`);
                    if (titleEl) {
                        titleEl.textContent = this.formatToolCallTitle(tc.name, {}, tc.args);
                    }
                }
            } else if (data.type === 'TOOL_CALL_END') {
                const toolCallId = data.toolCallId;
                const result = data.result || '';
                const error = data.error;
                if (toolCallId && streamingToolCalls.has(toolCallId)) {
                    const statusEl = document.querySelector(`[data-streaming-tool-id="${toolCallId}"] .tool-call-status-icon`);
                    if (statusEl) {
                        statusEl.textContent = error ? '✗' : '✓';
                        statusEl.parentElement.style.color = error ? 'var(--error)' : 'var(--success)';
                    }
                    const resultSection = document.getElementById(`streaming-tool-result-section-${toolCallId}`);
                    const resultEl = document.getElementById(`streaming-tool-result-${toolCallId}`);
                    if (resultSection && resultEl && result) {
                        resultSection.style.display = 'block';
                        resultEl.textContent = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
                    }
                    if (error) {
                        const errorSection = document.getElementById(`streaming-tool-error-section-${toolCallId}`);
                        const errorEl = document.getElementById(`streaming-tool-error-${toolCallId}`);
                        if (errorSection && errorEl) {
                            errorSection.style.display = 'block';
                            errorEl.textContent = error;
                        }
                    }
                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                }
            } else if (data.type === 'TOOL_CALL_RESULT') {
                const toolCallId = data.toolCallId;
                const result = data.result || data.content || '';
                if (toolCallId && streamingToolCalls.has(toolCallId)) {
                    const resultSection = document.getElementById(`streaming-tool-result-section-${toolCallId}`);
                    const resultEl = document.getElementById(`streaming-tool-result-${toolCallId}`);
                    if (resultSection && resultEl && result) {
                        resultSection.style.display = 'block';
                        resultEl.textContent = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
                    }
                }
            } else if (data.type === 'RUN_FINISHED' || data.type === 'RUN_ERROR') {
                done = true;
                if (currentTextEl) currentTextEl.classList.remove('streaming');
                this._closeTaskSessionStream(paneId);
                // Reload with snapshot API for final clean rendering with all content
                NexusAPI.getSessionMessages(sessionId).then(snapshotData => {
                    this.renderMessages(paneId, sessionId, snapshotData);
                }).catch(e => {
                    console.warn('Failed to reload snapshot after task finish:', e);
                });
                this.loadSessions(paneId);
            }
        };

        es.onerror = () => {
            if (done) return;
            this._closeTaskSessionStream(paneId);
            // If stream failed before any data arrived, fallback to normal message loading
            if (!initialized) {
                done = true;
                NexusAPI.getSessionMessages(sessionId).then(snapshotData => {
                    this.renderMessages(paneId, sessionId, snapshotData);
                }).catch(e => {
                    console.warn('Fallback message load also failed:', e);
                    if (messagesContainer) {
                        messagesContainer.innerHTML = `
                            <div class="empty-state" style="padding: 24px;">
                                <p class="empty-state-text" style="color: var(--error)">Failed to load task messages</p>
                            </div>
                        `;
                    }
                });
            }
        };
    }

    async _streamChannelSessionMessages(paneId, sessionId) {
        // Don't create duplicate SSE connections
        if (this.taskSessionStreams[paneId]) return;

        // Prevent reconnection flicker: if we already rendered this session's
        // messages recently (within the current auto-refresh cycle), skip
        // the full snapshot reload.
        const alreadyRendered = this._lastChannelStreamSession &&
            this._lastChannelStreamSession[paneId] === sessionId;

        // First load existing messages as snapshot (only if not already rendered)
        let snapshotData;
        if (!alreadyRendered) {
            try {
                snapshotData = await NexusAPI.getSessionMessages(sessionId);
                this.renderMessages(paneId, sessionId, snapshotData);
            } catch (e) {
                console.warn('Failed to load snapshot for channel session:', e);
            }
        }

        // Track which session we're streaming for this pane
        if (!this._lastChannelStreamSession) this._lastChannelStreamSession = {};
        this._lastChannelStreamSession[paneId] = sessionId;

        const messagesContainer = document.getElementById(`chatMessages-${paneId}`);
        if (!messagesContainer) return;

        // Connect SSE stream for live updates
        const es = NexusAPI.streamSessionMessages(sessionId, { tail: 5000 });
        this.taskSessionStreams[paneId] = es;

        let bubbleEl = null;
        let currentTextEl = null;
        let currentTextContent = '';
        let textSegmentIndex = 0;
        const streamingToolCalls = new Map();
        let done = false;

        const ensureBubble = () => {
            if (!bubbleEl) {
                const msgId = `channel-stream-${paneId}-${Date.now()}`;
                messagesContainer.insertAdjacentHTML('beforeend', `
                    <div class="message assistant" id="${msgId}">
                        <div class="message-avatar assistant">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="18" height="18">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                            </svg>
                        </div>
                        <div class="message-content">
                            <div class="message-bubble streaming-bubble" id="channel-stream-bubble-${msgId}"></div>
                        </div>
                    </div>
                `);
                bubbleEl = document.getElementById(`channel-stream-bubble-${msgId}`);
            }
            return bubbleEl;
        };

        const ensureTextElement = () => {
            if (!currentTextEl) {
                const bubble = ensureBubble();
                if (bubble) {
                    const textId = `channel-stream-content-${paneId}-seg${textSegmentIndex}`;
                    bubble.insertAdjacentHTML('beforeend', `<div class="message-text streaming" id="${textId}"></div>`);
                    currentTextEl = document.getElementById(textId);
                }
            }
            return currentTextEl;
        };

        es.onmessage = (event) => {
            if (done) return;
            let data;
            try {
                data = JSON.parse(event.data);
            } catch {
                return;
            }

            if (data.type === 'TEXT_MESSAGE_START') {
                ensureBubble();
            } else if (data.type === 'TEXT_MESSAGE_CONTENT') {
                const textDelta = data.delta ?? data.content ?? data.text ?? data.response;
                if (textDelta !== undefined && textDelta !== null && textDelta !== '') {
                    const textEl = ensureTextElement();
                    currentTextContent += (typeof textDelta === 'string' ? textDelta : JSON.stringify(textDelta, null, 2));
                    if (textEl) {
                        textEl.innerHTML = this.formatMessageContent(currentTextContent);
                        messagesContainer.scrollTop = messagesContainer.scrollHeight;
                    }
                }
            } else if (data.type === 'TEXT_MESSAGE_END') {
                if (currentTextEl) currentTextEl.classList.remove('streaming');
                currentTextEl = null;
                currentTextContent = '';
                textSegmentIndex++;
            } else if (data.type === 'TOOL_CALL_START') {
                const toolCallId = data.toolCallId || `tool-${Date.now()}`;
                const toolName = data.toolCallName || 'Tool';
                const toolTitle = this.formatToolCallTitle(toolName, {}, '');
                streamingToolCalls.set(toolCallId, { name: toolName, args: '', status: 'executing', result: '' });

                if (currentTextEl) currentTextEl.classList.remove('streaming');
                currentTextEl = null;
                currentTextContent = '';
                textSegmentIndex++;

                const bubble = ensureBubble();
                if (bubble) {
                    bubble.insertAdjacentHTML('beforeend', this.renderStreamingToolCall(toolCallId, toolTitle, 'executing'));
                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                }
            } else if (data.type === 'TOOL_CALL_ARGS') {
                const toolCallId = data.toolCallId;
                const argsDelta = data.delta || '';
                if (toolCallId && streamingToolCalls.has(toolCallId)) {
                    const tc = streamingToolCalls.get(toolCallId);
                    tc.args += argsDelta;
                    const argsEl = document.getElementById(`streaming-tool-args-${toolCallId}`);
                    if (argsEl) argsEl.textContent = tc.args;

                    const titleEl = document.querySelector(`[data-streaming-tool-id="${toolCallId}"] .tool-call-name`);
                    if (titleEl) {
                        titleEl.textContent = this.formatToolCallTitle(tc.name, {}, tc.args);
                    }
                }
            } else if (data.type === 'TOOL_CALL_END') {
                const toolCallId = data.toolCallId;
                const result = data.result || '';
                const error = data.error;
                if (toolCallId && streamingToolCalls.has(toolCallId)) {
                    const statusEl = document.querySelector(`[data-streaming-tool-id="${toolCallId}"] .tool-call-status-icon`);
                    if (statusEl) {
                        statusEl.textContent = error ? '✗' : '✓';
                        statusEl.parentElement.style.color = error ? 'var(--error)' : 'var(--success)';
                    }
                    const resultSection = document.getElementById(`streaming-tool-result-section-${toolCallId}`);
                    const resultEl = document.getElementById(`streaming-tool-result-${toolCallId}`);
                    if (resultSection && resultEl && result) {
                        resultSection.style.display = 'block';
                        resultEl.textContent = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
                    }
                    if (error) {
                        const errorSection = document.getElementById(`streaming-tool-error-section-${toolCallId}`);
                        const errorEl = document.getElementById(`streaming-tool-error-${toolCallId}`);
                        if (errorSection && errorEl) {
                            errorSection.style.display = 'block';
                            errorEl.textContent = error;
                        }
                    }
                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                }
            } else if (data.type === 'TOOL_CALL_RESULT') {
                const toolCallId = data.toolCallId;
                const result = data.result || data.content || '';
                if (toolCallId && streamingToolCalls.has(toolCallId)) {
                    const resultSection = document.getElementById(`streaming-tool-result-section-${toolCallId}`);
                    const resultEl = document.getElementById(`streaming-tool-result-${toolCallId}`);
                    if (resultSection && resultEl && result) {
                        resultSection.style.display = 'block';
                        resultEl.textContent = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
                    }
                }
            } else if (data.type === 'RUN_FINISHED' || data.type === 'RUN_ERROR') {
                done = true;
                if (currentTextEl) currentTextEl.classList.remove('streaming');
                this._closeTaskSessionStream(paneId);
                // Clear channel stream tracking so next session load does full snapshot
                if (this._lastChannelStreamSession) delete this._lastChannelStreamSession[paneId];
                // Reload with snapshot for clean final rendering
                NexusAPI.getSessionMessages(sessionId).then(finalData => {
                    this.renderMessages(paneId, sessionId, finalData);
                }).catch(e => {
                    console.warn('Failed to reload snapshot after channel session finish:', e);
                });
                this.loadSessions(paneId);
            }
        };

        es.onerror = () => {
            if (done) return;
            this._closeTaskSessionStream(paneId);
            // Clear channel stream tracking on error
            if (this._lastChannelStreamSession) delete this._lastChannelStreamSession[paneId];
        };
    }

    renderMessages(paneId, sessionId, data) {
        const detail = document.getElementById(`chatDetail-${paneId}`);
        if (!detail) return;

        const messages = data.messages || [];
        const toolCalls = data.tool_calls || [];

        // Track message count for auto-refresh change detection
        this._lastMessageCountBySession[sessionId] = messages.length;

        detail.innerHTML = `
            <div class="chat-header">
                <div class="chat-header-info">
                    <h2 class="chat-header-title">${this.escapeHtml(data.session?.title || sessionId)}</h2>
                    <span class="chat-header-meta">${messages.length} messages</span>
                </div>
                <div class="chat-header-actions">
                    ${!sessionId.startsWith('task_') ? `<button class="action-btn" data-action="fetch-from-cli" data-session-id="${sessionId}" title="Fetch from CLI file">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="16" height="16">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                        </svg>
                    </button>` : ''}
                    <button class="action-btn" data-action="show-files" data-session-id="${sessionId}" title="Files">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="16" height="16">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
                        </svg>
                    </button>
                    <button class="action-btn" data-action="tmux-open" data-session-id="${sessionId}" title="Open in tmux">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="16" height="16">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                        </svg>
                    </button>
                    <button class="action-btn" data-action="delete-session" data-session-id="${sessionId}" title="Delete">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="16" height="16">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                        </svg>
                    </button>
                </div>
            </div>
            <div class="chat-messages" id="chatMessages-${paneId}">
                ${messages.length === 0 
                    ? '<div class="empty-state"><p class="empty-state-text">No messages yet</p></div>'
                    : messages.map(msg => this.renderMessage(msg, toolCalls)).join('')}
            </div>
            <div class="chat-input-container">
                <div class="chat-input-wrapper">
                    <textarea 
                        id="chatInput-${paneId}" 
                        class="chat-input" 
                        placeholder="Enter message to continue..."
                        rows="1"
                        data-session-id="${sessionId}"
                    ></textarea>
                    <button class="chat-send-btn" data-pane="${paneId}" data-session-id="${sessionId}">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="18" height="18">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
                        </svg>
                    </button>
                </div>
            </div>
        `;

        // Bind fetch-from-cli (refresh) action
        const fetchBtn = detail.querySelector('[data-action="fetch-from-cli"]');
        if (fetchBtn) {
            fetchBtn.addEventListener('click', () => {
                this.fetchFromCli(paneId, sessionId);
            });
        }

        // Bind delete action
        const deleteBtn = detail.querySelector('[data-action="delete-session"]');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', () => {
                this.app.showDeleteModal('session', sessionId, () => {
                    this.deleteSession(paneId, sessionId);
                });
            });
        }

        // Bind files action
        const filesBtn = detail.querySelector('[data-action="show-files"]');
        if (filesBtn) {
            filesBtn.addEventListener('click', () => {
                this.showFilesModal(sessionId);
            });
        }

        // Bind tmux-open action
        const tmuxBtn = detail.querySelector('[data-action="tmux-open"]');
        if (tmuxBtn) {
            tmuxBtn.addEventListener('click', () => {
                this.openInTmux(sessionId);
            });
        }

        // Bind input events
        const textarea = document.getElementById(`chatInput-${paneId}`);
        const sendBtn = detail.querySelector('.chat-send-btn');
        
        if (textarea) {
            // Auto-resize textarea
            textarea.addEventListener('input', () => {
                textarea.style.height = 'auto';
                textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
            });
            
            // Enter to send (Shift+Enter for newline)
            textarea.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.sendMessage(paneId, sessionId, textarea.value);
                }
            });
        }
        
        if (sendBtn) {
            sendBtn.addEventListener('click', () => {
                this.sendMessage(paneId, sessionId, textarea?.value || '');
            });
        }

        // Scroll to bottom
        const messagesContainer = detail.querySelector('.chat-messages');
        if (messagesContainer) {
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
    }

    _buildBootstrapContextFromHistoryMessages(messages = [], mode = 'full') {
        if (!Array.isArray(messages) || messages.length === 0) {
            return '(历史会话没有可用消息)';
        }
        const effectiveMode = (mode || 'full').trim().toLowerCase();
        const isWindowed = effectiveMode === 'windowed';
        const selected = isWindowed ? messages.slice(-50) : messages;
        const lines = [];
        for (const msg of selected) {
            const role = (msg?.role || '').toLowerCase() === 'user' ? '用户' : '助手';
            let content = (msg?.content || '').trim();
            if (!content) continue;
            if (isWindowed && content.length > 800) {
                content = content.slice(0, 800) + '…(截断)';
            }
            lines.push(`[${role}] ${content}`);
        }
        return lines.length ? lines.join('\n\n') : '(历史会话没有可用消息)';
    }

    async _promoteHistorySessionFallback(meta, sessionId, projectPath, execUser) {
        const providerKey = (meta?.alias || meta?.provider || 'claude').trim() || 'claude';
        const cfg = this.app.getAliasConfigPath(providerKey);
        const historyDetail = await NexusAPI.getHistoryMessages(providerKey, sessionId, {
            execUser,
            configPath: cfg || undefined,
        });
        const bootstrapContext = this._buildBootstrapContextFromHistoryMessages(historyDetail?.messages || []);
        const runtimeSessionId = `chat_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;

        this.promotedRuntimeMeta[runtimeSessionId] = {
            id: runtimeSessionId,
            thread_id: runtimeSessionId,
            title: (meta?.title || `History: ${sessionId}`),
            username: execUser,
            exec_user: execUser,
            provider: (meta?.provider || providerKey || 'claude').toLowerCase(),
            alias: providerKey,
            source: 'runtime',
        };
        this.pendingBootstrapBySessionId[runtimeSessionId] = bootstrapContext;

        return { runtimeSessionId, usedFallback: true };
    }

    async _promoteHistorySessionIfNeeded(paneId, sessionId) {
        const meta = this.getSessionMeta(paneId, sessionId);
        const source = (meta?.source || '').toLowerCase();
        const isHistoryMode = this.sessionSource[paneId] === 'history';
        const shouldPromote = source === 'history' || isHistoryMode;
        if (!shouldPromote) {
            return sessionId;
        }

        const providerKey = (meta?.alias || meta?.provider || '').trim();
        const projectPath = (this.historyProjectPath[paneId] || '').trim();
        const globalUserFilter = document.getElementById('globalUserFilter');
        const execUser = globalUserFilter?.value || NexusAPI.getDefaultExecUser();

        if (!providerKey) {
            throw new Error('History session provider is missing');
        }
        if (!projectPath) {
            throw new Error('History project path is required before continuing chat');
        }

        let runtimeSessionId = '';
        let usedFallback = false;

        try {
            const promoted = await NexusAPI.promoteHistorySession(providerKey, sessionId, {
                projectPath,
                execUser,
                mode: 'full',
            });
            runtimeSessionId = promoted?.runtime_session_id || '';
        } catch (error) {
            const status = Number(error?.status || 0);
            if (status !== 404) {
                throw error;
            }
            const fallback = await this._promoteHistorySessionFallback(meta, sessionId, projectPath, execUser);
            runtimeSessionId = fallback.runtimeSessionId;
            usedFallback = fallback.usedFallback;
        }

        if (!runtimeSessionId) {
            throw new Error('Promote history session failed: missing runtime session id');
        }

        // Switch current pane to runtime source and bind active tab to new runtime session.
        this.sessionSource[paneId] = 'runtime';
        const activeTabId = this.getActiveTabId(paneId);
        if (activeTabId) {
            this.currentSessionByTab[activeTabId] = runtimeSessionId;
            const tab = this.getActiveTab(paneId);
            if (tab) {
                tab.data = tab.data || {};
                tab.data.sessionId = runtimeSessionId;
            }
        }

        if (!usedFallback) {
            await this.loadSessions(paneId);
            await this.loadMessages(paneId, runtimeSessionId, { source: 'runtime' });
        }

        if (usedFallback) {
            this.app.showToast('当前服务暂不支持 promote API，已自动使用兼容续聊模式', 'info');
        }

        return runtimeSessionId;
    }

    async sendMessage(paneId, sessionId, message) {
        if (!message.trim()) return;
        console.log('[sendMessage] START', { paneId, sessionId, message: message.substring(0, 50) });

        if (!document.getElementById(`chatMessages-${paneId}`)) {
            console.error('[sendMessage] chatMessages container not found for pane', paneId);
            return;
        }

        let effectiveSessionId = sessionId;
        try {
            effectiveSessionId = await this._promoteHistorySessionIfNeeded(paneId, sessionId);
            console.log('[sendMessage] effectiveSessionId:', effectiveSessionId);
        } catch (promoteError) {
            console.error('[sendMessage] promote failed:', promoteError);
            this.app.showToast(promoteError.message || 'Failed to continue history session', 'error');
            return;
        }

        // Re-acquire DOM refs after promote (renderMessages may have rebuilt the DOM)
        const textarea = document.getElementById(`chatInput-${paneId}`);
        const sendBtn = document.querySelector(`.chat-send-btn[data-pane="${paneId}"]`);
        const messagesContainer = document.getElementById(`chatMessages-${paneId}`);
        if (!messagesContainer) return;

        // Clear input and disable
        if (textarea) {
            textarea.value = '';
            textarea.style.height = 'auto';
            textarea.disabled = true;
            textarea.dataset.sessionId = effectiveSessionId;
        }
        if (sendBtn) {
            sendBtn.disabled = true;
            sendBtn.dataset.sessionId = effectiveSessionId;
        }

        // Add user message to UI immediately (must match renderMessage structure)
        const userTimeStr = this.formatTime(Date.now());
        const userMsgHtml = `
            <div class="message user">
                <div class="message-avatar">U</div>
                <div class="message-content">
                    <div class="message-bubble"><div class="message-text">${this.formatMessageContent(message)}</div></div>
                    <span class="message-time">${userTimeStr}</span>
                </div>
            </div>
        `;
        
        // Remove empty state if present
        const emptyState = messagesContainer.querySelector('.empty-state');
        if (emptyState) emptyState.remove();
        
        messagesContainer.insertAdjacentHTML('beforeend', userMsgHtml);

        // Add thinking indicator (must match renderMessage structure)
        const thinkingId = `thinking-${Date.now()}`;
        const thinkingHtml = `
            <div class="message assistant" id="${thinkingId}">
                <div class="message-avatar">A</div>
                <div class="message-content">
                    <div class="thinking-indicator">
                        <span class="thinking-dot"></span>
                        <span class="thinking-dot"></span>
                        <span class="thinking-dot"></span>
                    </div>
                </div>
            </div>
        `;
        messagesContainer.insertAdjacentHTML('beforeend', thinkingHtml);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;

        try {
            // Send message via streaming API
            await this.streamMessage(paneId, effectiveSessionId, message, thinkingId);
            
            // Note: Don't reload messages immediately after streaming because
            // the backend may not have saved the final content yet.
            // The streaming content is already displayed in the UI.
        } catch (error) {
            console.error('Failed to send message:', error);
            this.app.showToast(error.message || 'Failed to send message', 'error');
            
            // Replace thinking with error
            const thinkingEl = document.getElementById(thinkingId);
            if (thinkingEl) {
                thinkingEl.innerHTML = `
                    <div class="message-avatar assistant">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="18" height="18">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                        </svg>
                    </div>
                    <div class="message-content">
                        <div class="message-error">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="16" height="16">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                            </svg>
                            <span>${this.escapeHtml(error.message || 'Send failed')}</span>
                        </div>
                    </div>
                `;
            }
        } finally {
            // Re-enable input
            if (textarea) textarea.disabled = false;
            if (sendBtn) sendBtn.disabled = false;
            textarea?.focus();
        }
    }

    async streamMessage(paneId, sessionId, message, thinkingId) {
        const sessionMeta = this.getSessionMeta(paneId, sessionId);
        const globalUserFilter = document.getElementById('globalUserFilter');
        const execUser = sessionMeta?.username || globalUserFilter?.value || NexusAPI.getDefaultExecUser();
        const provider = (sessionMeta?.provider || '').trim();
        const alias = (sessionMeta?.alias || provider || '').trim();
        const workspace = (this.historyProjectPath[paneId] || '').trim();

        let outboundMessage = message;
        const bootstrapContext = this.pendingBootstrapBySessionId[sessionId];
        if (bootstrapContext && !String(message || '').trim().startsWith('/')) {
            outboundMessage = `[History Full Context]\n\n以下是完整历史对话上下文（全量注入）：\n\n${bootstrapContext}\n\n---\n\n请严格基于以上完整历史上下文继续对话。\n\n用户的当前请求：\n${message}`;
            delete this.pendingBootstrapBySessionId[sessionId];
        }
        
        // Build legacy request payload with session_id to continue conversation
        const payload = {
            content: outboundMessage,
            user: execUser,
            session_id: sessionId,
            msg_type: 'text',
            provider: provider || undefined,
            alias: alias || undefined,
            cwd: workspace || undefined,
            cwd_mode: workspace ? 'inplace' : undefined,
            run_kind: 'chat_continue',
            forwardedProps: {
                ...(alias ? { alias } : {}),
            },
        };
        
        // Use the shared streaming method
        // IMPORTANT: baseline must be tracked by session (not pane), otherwise switching tabs/sessions can delay sync.
        const baselineCount = this._lastMessageCountBySession[sessionId] || 0;
        const hadContent = await this.streamChatResponse(paneId, execUser, payload, thinkingId);

        // Refresh session list to update last_message
        this.loadSessions(paneId);

        // Mark that this pane needs a post-stream sync check from auto-refresh
        this._needsPostStreamSync = this._needsPostStreamSync || {};
        this._needsPostStreamSync[paneId] = { sessionId, ts: Date.now() };

        // Always auto-sync final snapshot after stream ends so UI never depends on manual refresh
        // forceOnLastRetry is always true to guarantee at least one full render
        await this._syncSessionMessagesAfterStream(paneId, sessionId, baselineCount, { forceOnLastRetry: true });
    }

    async _syncSessionMessagesAfterStream(paneId, sessionId, baselineCount = 0, options = {}) {
        const forceOnLastRetry = !!options.forceOnLastRetry;
        const maxRetries = 20;

        for (let i = 0; i < maxRetries; i++) {
            try {
                const data = await NexusAPI.getSessionMessages(sessionId);
                const msgCount = (data.messages || []).length;
                const reachedNewState = msgCount > baselineCount;
                const isLast = i === maxRetries - 1;

                if (reachedNewState || (forceOnLastRetry && isLast)) {
                    if (isLast && !reachedNewState) {
                        console.log('[syncSessionMessagesAfterStream] force-rendering final snapshot (baseline not exceeded)');
                    }
                    this.renderMessages(paneId, sessionId, data);
                    // Clear post-stream sync flag once we successfully render
                    if (this._needsPostStreamSync) delete this._needsPostStreamSync[paneId];
                    return;
                }
            } catch (e) {
                if (i === maxRetries - 1) {
                    console.warn('[syncSessionMessagesAfterStream] final snapshot sync failed:', e);
                }
            }
            // Incremental delay: 300ms for first 5 retries, then gradually increase
            const delayMs = i < 5 ? 300 : i < 10 ? 500 : i < 15 ? 800 : 1200;
            await new Promise(r => setTimeout(r, delayMs));
        }
    }

    normalizeContentSegments(segments) {
        if (!Array.isArray(segments) || segments.length === 0) {
            return [];
        }

        const sortedSegments = [...segments].sort((a, b) => (a.sequence || 0) - (b.sequence || 0));
        const normalized = [];

        for (const segment of sortedSegments) {
            if (!segment || !segment.type) continue;

            if (segment.type === 'text') {
                const text = segment.content ?? '';
                if (!text) continue;

                const prev = normalized[normalized.length - 1];
                if (prev && prev.type === 'text') {
                    prev.content = `${prev.content || ''}${text}`;
                    continue;
                }

                normalized.push({ ...segment, content: text });
                continue;
            }

            normalized.push({ ...segment });
        }

        return normalized;
    }

    renderMessage(msg, toolCalls) {
        const isUser = msg.role === 'user';
        const avatar = isUser ? 'U' : 'A';
        const timeStr = this.formatTime(msg.timestamp);
        const hasContent = msg.content && msg.content.trim();
        const normalizedSegments = this.normalizeContentSegments(msg.content_segments);

        // Find tool calls for this message
        const messageToolCallIds = new Set([
            ...(msg.tool_call_ids || []),
            ...(normalizedSegments
                .filter(segment => segment.type === 'tool_call' && segment.tool_call_id)
                .map(segment => segment.tool_call_id))
        ]);
        const messageToolCalls = toolCalls.filter(tc => (
            tc.parent_message_id === msg.id ||
            tc.message_id === msg.id ||
            messageToolCallIds.has(tc.id)
        ));

        // Build message bubble content
        let bubbleContent = '';
        
        // Check if message has content_segments for ordered rendering
        if (normalizedSegments.length > 0) {
            for (const segment of normalizedSegments) {
                if (segment.type === 'text' && segment.content) {
                    bubbleContent += `<div class="message-text">${this.formatMessageContent(segment.content)}</div>`;
                } else if (segment.type === 'tool_call' && segment.tool_call_id) {
                    // Find the tool call by ID
                    const tc = messageToolCalls.find(t => t.id === segment.tool_call_id);
                    if (tc) {
                        bubbleContent += this.renderToolCall(tc);
                    }
                }
            }
        } else {
            // Fallback: render content + tool calls at the end (legacy behavior)
            if (hasContent) {
                bubbleContent += `<div class="message-text">${this.formatMessageContent(msg.content)}</div>`;
            }
            
            if (messageToolCalls.length > 0) {
                bubbleContent += messageToolCalls.map(tc => this.renderToolCall(tc)).join('');
            }
        }
        
        // If no content and no tool calls, show empty placeholder
        if (!bubbleContent) {
            bubbleContent = '<span class="message-empty">(Empty message)</span>';
        }

        return `
            <div class="message ${isUser ? 'user' : 'assistant'}">
                <div class="message-avatar">${avatar}</div>
                <div class="message-content">
                    <div class="message-bubble">${bubbleContent}</div>
                    <span class="message-time">${timeStr}</span>
                </div>
            </div>
        `;
    }
    
    renderToolCallStandalone(tc, isFromUser = false) {
        const status = tc.status || 'pending';
        const toolTitle = this.formatToolCallTitle(tc.tool_name || tc.name || 'Tool Call', tc.args, tc.args_string || '');
        const statusConfig = {
            pending: { icon: '⏳', color: 'var(--text-muted)', bgColor: 'rgba(148, 163, 184, 0.1)', label: 'Pending' },
            executing: { icon: '▶️', color: 'var(--primary-500)', bgColor: 'rgba(59, 130, 246, 0.1)', label: 'Executing' },
            completed: { icon: '✓', color: 'var(--text-muted)', bgColor: 'rgba(113, 113, 122, 0.1)', label: 'Completed' },
            failed: { icon: '✗', color: 'var(--error)', bgColor: 'rgba(239, 68, 68, 0.1)', label: 'Failed' }
        };
        const cfg = statusConfig[status] || statusConfig.pending;
        
        // Calculate execution time
        let execTime = '';
        if (tc.start_time && tc.end_time) {
            const ms = tc.end_time - tc.start_time;
            execTime = ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(2)}s`;
        }
        
        // Format args and result
        // Prefer args_string if args is empty object
        const hasArgs = tc.args && Object.keys(tc.args).length > 0;
        const argsContent = hasArgs ? JSON.stringify(tc.args, null, 2) : (tc.args_string || '');
        const resultContent = tc.result !== undefined ? 
            (typeof tc.result === 'string' ? tc.result : JSON.stringify(tc.result, null, 2)) : '';
        
        // Generate unique IDs for copy buttons
        const toolId = `tool-${tc.id || Math.random().toString(36).substr(2, 9)}`;
        
        return `
            <div class="tool-call-standalone" data-tool-id="${toolId}">
                <div class="tool-call-standalone-inner">
                    <div class="tool-call-standalone-header" onclick="this.closest('.tool-call-standalone').classList.toggle('expanded')">
                        <div class="tool-call-standalone-status" style="background: ${cfg.bgColor}; color: ${cfg.color}">
                            <span class="tool-call-status-icon">${cfg.icon}</span>
                            <span class="tool-call-status-label">${cfg.label}</span>
                        </div>
                        <svg class="tool-call-standalone-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                        </svg>
                        <span class="tool-call-standalone-name">${this.escapeHtml(toolTitle)}</span>
                        ${execTime ? `<span class="tool-call-standalone-time">⏱ ${execTime}</span>` : ''}
                        ${tc.error ? `<span class="tool-call-standalone-error-badge">⚠ Error</span>` : ''}
                        <svg class="tool-call-standalone-toggle" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </div>
                    <div class="tool-call-standalone-body">
                        ${argsContent ? `
                            <div class="tool-call-standalone-section">
                                <div class="tool-call-standalone-section-header">
                                    <span class="tool-call-standalone-section-title">
                                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                                        </svg>
                                        Input
                                    </span>
                                    <button class="tool-call-standalone-copy-btn" onclick="event.stopPropagation(); nexusApp.chatView.copyToClipboard('${toolId}-args')">
                                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                                        </svg>
                                        Copy
                                    </button>
                                </div>
                                <div class="tool-call-standalone-content" id="${toolId}-args">${this.escapeHtml(argsContent)}</div>
                            </div>
                        ` : ''}
                        ${resultContent ? `
                            <div class="tool-call-standalone-section">
                                <div class="tool-call-standalone-section-header">
                                    <span class="tool-call-standalone-section-title">
                                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                        </svg>
                                        Output
                                    </span>
                                    <button class="tool-call-standalone-copy-btn" onclick="event.stopPropagation(); nexusApp.chatView.copyToClipboard('${toolId}-result')">
                                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                                        </svg>
                                        Copy
                                    </button>
                                </div>
                                <div class="tool-call-standalone-content tool-call-standalone-result" id="${toolId}-result">${this.escapeHtml(resultContent)}</div>
                            </div>
                        ` : ''}
                        ${tc.error ? `
                            <div class="tool-call-standalone-section">
                                <div class="tool-call-standalone-section-header">
                                    <span class="tool-call-standalone-section-title" style="color: var(--error);">
                                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                        </svg>
                                        Error
                                    </span>
                                    <button class="tool-call-standalone-copy-btn" onclick="event.stopPropagation(); nexusApp.chatView.copyToClipboard('${toolId}-error')">
                                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                                        </svg>
                                        Copy
                                    </button>
                                </div>
                                <div class="tool-call-standalone-content tool-call-standalone-error" id="${toolId}-error">${this.escapeHtml(tc.error)}</div>
                            </div>
                        ` : ''}
                    </div>
                </div>
            </div>
        `;
    }

    renderToolCall(tc) {
        const status = tc.status || 'pending';
        const toolTitle = this.formatToolCallTitle(tc.tool_name || tc.name || 'Tool Call', tc.args, tc.args_string || '');
        const statusConfig = {
            pending: { icon: '⏳', color: 'var(--text-muted)', label: 'Pending' },
            executing: { icon: '▶️', color: 'var(--primary-500)', label: 'Executing' },
            completed: { icon: '✓', color: 'var(--success)', label: 'Completed' },
            failed: { icon: '✗', color: 'var(--error)', label: 'Failed' }
        };
        const cfg = statusConfig[status] || statusConfig.pending;
        
        // Calculate execution time
        let execTime = '';
        if (tc.start_time && tc.end_time) {
            const ms = tc.end_time - tc.start_time;
            execTime = ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(2)}s`;
        }
        
        // Format args and result
        // Prefer args_string if args is empty object
        const hasArgs = tc.args && Object.keys(tc.args).length > 0;
        const argsContent = hasArgs ? JSON.stringify(tc.args, null, 2) : (tc.args_string || '');
        const resultContent = tc.result !== undefined ? 
            (typeof tc.result === 'string' ? tc.result : JSON.stringify(tc.result, null, 2)) : '';
        
        // Generate unique IDs for copy buttons
        const toolId = `tool-${tc.id || Math.random().toString(36).substr(2, 9)}`;
        
        return `
            <div class="tool-call" data-tool-id="${toolId}">
                <div class="tool-call-header" onclick="this.closest('.tool-call').classList.toggle('expanded')">
                    <div class="tool-call-status" style="color: ${cfg.color}">
                        <span class="tool-call-status-icon">${cfg.icon}</span>
                    </div>
                    <svg class="tool-call-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                    </svg>
                    <span class="tool-call-name">${this.escapeHtml(toolTitle)}</span>
                    ${execTime ? `<span class="tool-call-time">${execTime}</span>` : ''}
                    ${tc.error ? `<span class="tool-call-error-badge">Error</span>` : ''}
                    <svg class="tool-call-toggle" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </div>
                <div class="tool-call-body">
                    ${argsContent ? `
                        <div class="tool-call-section">
                            <div class="tool-call-section-header">
                                <span class="tool-call-section-title">Input</span>
                                <button class="tool-call-copy-btn" onclick="event.stopPropagation(); nexusApp.chatView.copyToClipboard('${toolId}-args')">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                                    </svg>
                                    Copy
                                </button>
                            </div>
                            <div class="tool-call-content" id="${toolId}-args">${this.escapeHtml(argsContent)}</div>
                        </div>
                    ` : ''}
                    ${resultContent ? `
                        <div class="tool-call-section">
                            <div class="tool-call-section-header">
                                <span class="tool-call-section-title">Output</span>
                                <button class="tool-call-copy-btn" onclick="event.stopPropagation(); nexusApp.chatView.copyToClipboard('${toolId}-result')">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                                    </svg>
                                    Copy
                                </button>
                            </div>
                            <div class="tool-call-content tool-call-result" id="${toolId}-result">${this.escapeHtml(resultContent)}</div>
                        </div>
                    ` : ''}
                    ${tc.error ? `
                        <div class="tool-call-section">
                            <div class="tool-call-section-header">
                                <span class="tool-call-section-title" style="color: var(--error);">Error</span>
                                <button class="tool-call-copy-btn" onclick="event.stopPropagation(); nexusApp.chatView.copyToClipboard('${toolId}-error')">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                                    </svg>
                                    Copy
                                </button>
                            </div>
                            <div class="tool-call-content tool-call-error" id="${toolId}-error">${this.escapeHtml(tc.error)}</div>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }
    
    copyToClipboard(elementId) {
        const element = document.getElementById(elementId);
        if (!element) return;

        const text = element.textContent || '';
        navigator.clipboard.writeText(text).then(() => {
            this.app.showToast('Copied to clipboard', 'success');
        }).catch(err => {
            console.error('Copy failed:', err);
            this.app.showToast('Copy failed', 'error');
        });
    }

    async openInTmux(sessionId) {
        try {
            // Remove existing terminal modal if any
            document.getElementById('terminalModal')?.remove();

            // Create modal overlay with terminal container
            const modal = document.createElement('div');
            modal.className = 'terminal-modal-overlay';
            modal.id = 'terminalModal';
            modal.innerHTML = `
                <div class="terminal-modal">
                    <div class="terminal-header">
                        <div class="terminal-header-title">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                            </svg>
                            <span>Terminal — ${this.escapeHtml(sessionId.substring(0, 16))}</span>
                        </div>
                        <div class="terminal-header-actions">
                            <button class="terminal-header-btn close-btn" data-action="close-terminal" title="Close terminal">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="16" height="16">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                                </svg>
                            </button>
                        </div>
                    </div>
                    <div class="terminal-container" id="terminalContainer"></div>
                    <div class="terminal-status">
                        <span class="terminal-status-dot" id="terminalStatusDot"></span>
                        <span id="terminalStatusText">Connecting...</span>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);

            // Get terminal container
            const container = document.getElementById('terminalContainer');
            const statusDot = document.getElementById('terminalStatusDot');
            const statusText = document.getElementById('terminalStatusText');

            // Initialize xterm.js
            const term = new Terminal({
                cursorBlink: true,
                fontSize: 14,
                fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
                theme: {
                    background: '#1e1e1e',
                    foreground: '#d4d4d4',
                    cursor: '#aeafad',
                    selectionBackground: 'rgba(255, 255, 255, 0.2)',
                    black: '#000000',
                    red: '#cd3131',
                    green: '#0dbc79',
                    yellow: '#e5e510',
                    blue: '#2472c8',
                    magenta: '#bc3fbc',
                    cyan: '#11a8cd',
                    white: '#e5e5e5',
                    brightBlack: '#666666',
                    brightRed: '#f14c4c',
                    brightGreen: '#23d18b',
                    brightYellow: '#f5f543',
                    brightBlue: '#3b8eea',
                    brightMagenta: '#d670d6',
                    brightCyan: '#29b8db',
                    brightWhite: '#ffffff',
                },
                scrollback: 5000,
                convertEol: true,
            });

            const fitAddon = new FitAddon.FitAddon();
            term.loadAddon(fitAddon);
            term.open(container);

            // Small delay to ensure the container is laid out before fitting
            await new Promise(r => setTimeout(r, 50));
            fitAddon.fit();

            // Build WebSocket URL (same-origin, cookies sent automatically)
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/api/nexus/terminal/${encodeURIComponent(sessionId)}`;

            const ws = new WebSocket(wsUrl);
            let connected = false;

            ws.onopen = () => {
                // Send initial resize
                ws.send(JSON.stringify({
                    type: 'resize',
                    cols: term.cols,
                    rows: term.rows,
                }));
            };

            ws.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    if (msg.type === 'output') {
                        // Decode base64 → Uint8Array (preserves UTF-8 multi-byte sequences)
                        const binaryStr = atob(msg.data);
                        const bytes = new Uint8Array(binaryStr.length);
                        for (let i = 0; i < binaryStr.length; i++) {
                            bytes[i] = binaryStr.charCodeAt(i);
                        }
                        term.write(bytes);
                    } else if (msg.type === 'connected') {
                        connected = true;
                        statusDot.className = 'terminal-status-dot';
                        statusText.textContent = 'Connected';
                    } else if (msg.type === 'disconnected') {
                        connected = false;
                        statusDot.className = 'terminal-status-dot disconnected';
                        statusText.textContent = 'Process ended';
                    } else if (msg.type === 'error') {
                        term.write(`\r\n\x1b[31mError: ${msg.message}\x1b[0m\r\n`);
                        statusDot.className = 'terminal-status-dot disconnected';
                        statusText.textContent = 'Error';
                    }
                } catch (e) {
                    console.error('Terminal message parse error:', e);
                }
            };

            ws.onerror = (error) => {
                console.error('Terminal WebSocket error:', error);
                statusDot.className = 'terminal-status-dot disconnected';
                statusText.textContent = 'Connection error';
            };

            ws.onclose = () => {
                connected = false;
                statusDot.className = 'terminal-status-dot disconnected';
                statusText.textContent = 'Disconnected';
            };

            // Forward keyboard input to WebSocket
            term.onData((data) => {
                if (ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'input', data: data }));
                }
            });

            // Handle terminal resize
            const resizeObserver = new ResizeObserver(() => {
                fitAddon.fit();
                if (ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({
                        type: 'resize',
                        cols: term.cols,
                        rows: term.rows,
                    }));
                }
            });
            resizeObserver.observe(container);

            // Keepalive ping every 30s
            const pingInterval = setInterval(() => {
                if (ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'ping' }));
                }
            }, 30000);

            // Cleanup function
            const cleanup = () => {
                clearInterval(pingInterval);
                resizeObserver.disconnect();
                if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
                    ws.close();
                }
                term.dispose();
                modal.remove();
            };

            // Close button
            modal.querySelector('[data-action="close-terminal"]').addEventListener('click', cleanup);

            // Escape key to close
            const escHandler = (e) => {
                if (e.key === 'Escape') {
                    cleanup();
                    document.removeEventListener('keydown', escHandler);
                }
            };
            document.addEventListener('keydown', escHandler);

            // Click backdrop to close
            modal.addEventListener('click', (e) => {
                if (e.target === modal) cleanup();
            });

            // Focus terminal
            term.focus();

        } catch (error) {
            console.error('Failed to open terminal:', error);
            this.app.showToast(error.message || 'Failed to open terminal', 'error');
        }
    }

        async deleteSession(paneId, sessionId) {
        try {
            await NexusAPI.deleteSession(sessionId);
            this.app.showToast('Session deleted', 'success');
            const activeTabId = this.getActiveTabId(paneId);
            if (activeTabId) {
                this.currentSessionByTab[activeTabId] = null;
                const tab = this.getActiveTab(paneId);
                if (tab) {
                    tab.data = tab.data || {};
                    tab.data.sessionId = null;
                }
            }
            await this.loadSessions(paneId);
            
            // Clear detail view
            const detail = document.getElementById(`chatDetail-${paneId}`);
            if (detail) {
                detail.innerHTML = `
                    <div class="empty-state">
                        <svg class="empty-state-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
                        </svg>
                        <p class="empty-state-title">Select a session</p>
                        <p class="empty-state-text">Choose a session from the list to view messages</p>
                    </div>
                `;
            }
        } catch (error) {
            console.error('Failed to delete session:', error);
            this.app.showToast('Failed to delete session', 'error');
        }
    }

    async fetchFromCli(paneId, sessionId) {
        try {
            const fetchBtn = document.querySelector(`[data-action="fetch-from-cli"][data-session-id="${sessionId}"]`);
            if (fetchBtn) {
                fetchBtn.disabled = true;
                fetchBtn.style.opacity = '0.5';
            }

            const globalUserFilter = document.getElementById('globalUserFilter');
            const execUser = globalUserFilter?.value || NexusAPI.getDefaultExecUser();

            const result = await NexusAPI.fetchFromCli(sessionId, { execUser });
            this.app.showToast(
                `Refreshed: ${result.messages_imported} messages, ${result.tool_calls_imported} tool calls`,
                'success'
            );

            // Reload messages to reflect the updated data
            await this.loadMessages(paneId, sessionId, { source: 'runtime' });
        } catch (error) {
            console.error('Failed to fetch from CLI:', error);
            // Extract detail from backend error response
            let errorMsg = 'Failed to refresh from CLI file';
            const errorText = error.message || '';
            // Try to extract JSON detail from error body
            const detailMatch = errorText.match(/"detail"\s*:\s*"([^"]+)"/);
            if (detailMatch) {
                errorMsg = detailMatch[1];
            } else if (errorText.includes(' - ')) {
                errorMsg = errorText.split(' - ').slice(1).join(' - ');
            }
            // "Not found" / "No CLI sessions found" are informational, not hard errors
            const isNotFound = /not found|no cli session/i.test(errorMsg);
            this.app.showToast(errorMsg, isNotFound ? 'warning' : 'error');
        } finally {
            const fetchBtn = document.querySelector(`[data-action="fetch-from-cli"][data-session-id="${sessionId}"]`);
            if (fetchBtn) {
                fetchBtn.disabled = false;
                fetchBtn.style.opacity = '1';
            }
        }
    }

    groupSessionsByDate(sessions) {
        const groups = {};
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);
        const weekAgo = new Date(today);
        weekAgo.setDate(weekAgo.getDate() - 7);

        sessions.forEach(session => {
            const date = new Date(session.updated_at || session.created_at);
            date.setHours(0, 0, 0, 0);

            let label;
            if (date >= today) label = 'Today';
            else if (date >= yesterday) label = 'Yesterday';
            else if (date >= weekAgo) label = 'This Week';
            else label = 'Earlier';

            if (!groups[label]) groups[label] = [];
            groups[label].push(session);
        });

        return groups;
    }

    formatTime(timestamp) {
        if (!timestamp) return '';
        const date = new Date(timestamp);
        const now = new Date();
        const diff = now - date;

        if (diff < 60000) return 'Just now';
        if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
        if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
        return date.toLocaleDateString();
    }

    formatMessageContent(content) {
        if (content === undefined || content === null || content === '') return '';
        const text = String(content);
        if (this.markdownRenderer && typeof this.markdownRenderer.render === 'function') {
            return this.markdownRenderer.render(text);
        }
        return this.renderMarkdown(text);
    }

    renderMarkdown(content) {
        const normalized = content.replace(/\r\n?/g, '\n');
        const blocks = [];
        const lines = normalized.split('\n');
        let index = 0;

        while (index < lines.length) {
            const line = lines[index];
            if (!line.trim()) {
                index++;
                continue;
            }

            const fenceMatch = line.match(/^```([\w-]+)?\s*$/);
            if (fenceMatch) {
                const language = fenceMatch[1] || '';
                const codeLines = [];
                index++;
                while (index < lines.length && !/^```\s*$/.test(lines[index])) {
                    codeLines.push(lines[index]);
                    index++;
                }
                if (index < lines.length && /^```\s*$/.test(lines[index])) {
                    index++;
                }
                const languageClass = language ? ` class="language-${this.escapeHtml(language)}"` : '';
                blocks.push(`<pre class="message-code-block"><code${languageClass}>${this.escapeHtml(codeLines.join('\n'))}</code></pre>`);
                continue;
            }

            const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
            if (headingMatch) {
                const level = headingMatch[1].length;
                blocks.push(`<h${level}>${this.formatInlineMarkdown(headingMatch[2])}</h${level}>`);
                index++;
                continue;
            }

            if (/^([-*_])(?:\s*\1){2,}\s*$/.test(line.trim())) {
                blocks.push('<hr class="message-hr">');
                index++;
                continue;
            }

            if (/^\s*>\s?/.test(line)) {
                const quoteBlock = this.renderMarkdownBlockquote(lines, index);
                blocks.push(quoteBlock.html);
                index = quoteBlock.nextIndex;
                continue;
            }

            if (this.isMarkdownListItem(line)) {
                const listBlock = this.renderMarkdownList(lines, index);
                blocks.push(listBlock.html);
                index = listBlock.nextIndex;
                continue;
            }

            const paragraphLines = [line];
            index++;
            while (index < lines.length && lines[index].trim() && !this.isMarkdownBlockStart(lines[index])) {
                paragraphLines.push(lines[index]);
                index++;
            }
            blocks.push(`<p>${paragraphLines.map(part => this.formatInlineMarkdown(part)).join('<br>')}</p>`);
        }

        return blocks.join('');
    }

    isMarkdownBlockStart(line) {
        const trimmed = line.trimStart();
        return /^```/.test(trimmed)
            || /^(#{1,6})\s+/.test(trimmed)
            || /^([-*_])(?:\s*\1){2,}\s*$/.test(trimmed)
            || /^>\s?/.test(trimmed)
            || this.isMarkdownListItem(trimmed);
    }

    isMarkdownListItem(line) {
        const trimmed = line.trimStart();
        return /^[-*+]\s+/.test(trimmed) || /^\d+\.\s+/.test(trimmed);
    }

    renderMarkdownList(lines, startIndex) {
        const firstLine = lines[startIndex].trimStart();
        const ordered = /^\d+\.\s+/.test(firstLine);
        const items = [];
        let index = startIndex;

        while (index < lines.length) {
            const current = lines[index];
            if (!current.trim()) break;
            const trimmed = current.trimStart();
            if (ordered ? !/^\d+\.\s+/.test(trimmed) : !/^[-*+]\s+/.test(trimmed)) break;
            items.push(trimmed.replace(ordered ? /^\d+\.\s+/ : /^[-*+]\s+/, ''));
            index++;
        }

        const tag = ordered ? 'ol' : 'ul';
        return {
            html: `<${tag}>${items.map(item => `<li>${this.formatInlineMarkdown(item)}</li>`).join('')}</${tag}>`,
            nextIndex: index,
        };
    }

    renderMarkdownBlockquote(lines, startIndex) {
        const quoteLines = [];
        let index = startIndex;

        while (index < lines.length) {
            const current = lines[index];
            if (!current.trim()) break;
            if (!/^\s*>\s?/.test(current)) break;
            quoteLines.push(current.replace(/^\s*>\s?/, ''));
            index++;
        }

        return {
            html: `<blockquote class="message-blockquote">${quoteLines.map(line => `<p>${this.formatInlineMarkdown(line)}</p>`).join('')}</blockquote>`,
            nextIndex: index,
        };
    }

    formatInlineMarkdown(text) {
        if (!text) return '';

        const tokens = [];
        const createToken = (html) => `@@MD_TOKEN_${tokens.push(html) - 1}@@`;
        let formatted = text;

        formatted = formatted.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_match, alt, url) => {
            const safeUrl = this.sanitizeMarkdownUrl(url);
            if (!safeUrl) {
                return createToken(this.escapeHtml(`![${alt}](${url})`));
            }
            return createToken(`<img src="${safeUrl}" alt="${this.escapeHtml(alt)}" class="message-markdown-image" loading="lazy">`);
        });

        formatted = formatted.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_match, label, url) => {
            const safeUrl = this.sanitizeMarkdownUrl(url);
            if (!safeUrl) {
                return createToken(this.escapeHtml(`[${label}](${url})`));
            }
            return createToken(`<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${this.escapeHtml(label)}</a>`);
        });

        formatted = formatted.replace(/`([^`]+)`/g, (_match, code) => createToken(`<code>${this.escapeHtml(code)}</code>`));

        formatted = this.escapeHtml(formatted)
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')
            .replace(/~~([^~]+)~~/g, '<del>$1</del>');

        return this.restoreMarkdownTokens(formatted, tokens);
    }

    restoreMarkdownTokens(text, tokens) {
        return text.replace(/@@MD_TOKEN_(\d+)@@/g, (_match, index) => tokens[Number(index)] ?? '');
    }

    sanitizeMarkdownUrl(url) {
        if (!url) return '';
        const trimmed = String(url).trim();
        if (!trimmed) return '';

        try {
            if (trimmed.startsWith('/')) {
                const safe = new URL(trimmed, window.location.origin);
                return this.escapeHtml(`${safe.pathname}${safe.search}${safe.hash}`);
            }

            const parsed = new URL(trimmed);
            const protocol = parsed.protocol.toLowerCase();
            if (!['http:', 'https:', 'mailto:'].includes(protocol)) {
                return '';
            }
            return this.escapeHtml(parsed.href);
        } catch {
            return '';
        }
    }

    escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ========== Batch Selection Methods ==========

    toggleSessionSelectionMode(paneId) {
        this.selectionMode[paneId] = !this.selectionMode[paneId];

        // Clear selections when exiting selection mode
        if (!this.selectionMode[paneId]) {
            this.selectedSessionIds[paneId] = new Set();
        }

        // Update UI
        const selectionActions = document.getElementById(`sessionSelectionActions-${paneId}`);
        const toggleBtn = document.querySelector(`[data-action="toggle-session-selection"][data-pane="${paneId}"]`);

        if (selectionActions) {
            selectionActions.style.display = this.selectionMode[paneId] ? 'flex' : 'none';
        }

        if (toggleBtn) {
            toggleBtn.classList.toggle('active', this.selectionMode[paneId]);
        }

        // Re-render sessions to show/hide checkboxes
        this.renderSessionList(paneId);
        this.updateDeleteSessionsButtonCount(paneId);
    }

    toggleSessionSelection(paneId, sessionId) {
        if (!this.selectedSessionIds[paneId]) {
            this.selectedSessionIds[paneId] = new Set();
        }

        if (this.selectedSessionIds[paneId].has(sessionId)) {
            this.selectedSessionIds[paneId].delete(sessionId);
        } else {
            this.selectedSessionIds[paneId].add(sessionId);
        }

        // Update item visual state
        const item = document.querySelector(`#sessionItems-${paneId} .session-item[data-session-id="${sessionId}"]`);
        if (item) {
            item.classList.toggle('checked', this.selectedSessionIds[paneId].has(sessionId));
            const checkbox = item.querySelector('.session-item-checkbox input');
            if (checkbox) {
                checkbox.checked = this.selectedSessionIds[paneId].has(sessionId);
            }
        }

        this.updateDeleteSessionsButtonCount(paneId);
    }

    selectAllSessions(paneId) {
        const sessions = this.sessions[paneId] || [];
        this.selectedSessionIds[paneId] = new Set(sessions.map(s => s.id));

        // Update all items
        document.querySelectorAll(`#sessionItems-${paneId} .session-item`).forEach(item => {
            item.classList.add('checked');
            const checkbox = item.querySelector('.session-item-checkbox input');
            if (checkbox) checkbox.checked = true;
        });

        this.updateDeleteSessionsButtonCount(paneId);
    }

    deselectAllSessions(paneId) {
        this.selectedSessionIds[paneId] = new Set();

        // Update all items
        document.querySelectorAll(`#sessionItems-${paneId} .session-item`).forEach(item => {
            item.classList.remove('checked');
            const checkbox = item.querySelector('.session-item-checkbox input');
            if (checkbox) checkbox.checked = false;
        });

        this.updateDeleteSessionsButtonCount(paneId);
    }

    updateDeleteSessionsButtonCount(paneId) {
        const count = this.selectedSessionIds[paneId]?.size || 0;
        const btn = document.getElementById(`deleteSelectedSessionsBtn-${paneId}`);
        if (btn) {
            btn.innerHTML = `
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                </svg>
                <span>Delete (${count})</span>
            `;
            btn.disabled = count === 0;
        }
    }

    async deleteSelectedSessions(paneId) {
        const sessionIds = Array.from(this.selectedSessionIds[paneId] || []);
        if (sessionIds.length === 0) {
            this.app.showToast('No sessions selected', 'warning');
            return;
        }

        const loadedCount = (this.sessions[paneId] || []).length;
        const totalCount = (this.sessionTotals || {})[paneId] || loadedCount;
        const allLoadedSelected = sessionIds.length >= loadedCount && totalCount > loadedCount;

        // Gather current filter params for delete_all API
        const searchInput = document.querySelector(`.session-search-input[data-pane="${paneId}"]`);
        const statusFilter = document.querySelector(`.session-filter-select[data-pane="${paneId}"]`);
        const globalUserFilter = document.getElementById('globalUserFilter');
        const filterParams = {
            username: globalUserFilter?.value || '',
            search: searchInput?.value || '',
            status: statusFilter?.value || '',
        };

        const label = allLoadedSelected
            ? `ALL ${totalCount} session(s) (including ${totalCount - loadedCount} not loaded)`
            : `${sessionIds.length} session(s)`;

        // Show confirmation modal
        this.app.showDeleteModal('sessions', label, async () => {
            try {
                let result;
                if (allLoadedSelected) {
                    // Use delete_all API to cover sessions beyond loaded page
                    result = await NexusAPI.deleteAllSessions(filterParams);
                } else {
                    result = await NexusAPI.bulkDeleteSessions(sessionIds);
                }

                const deletedCount = result.result?.count || sessionIds.length;
                this.app.showToast(`Deleted ${deletedCount} session(s)`, 'success');

                // Clear selections and reload
                this.selectedSessionIds[paneId] = new Set();
                this.updateDeleteSessionsButtonCount(paneId);
                await this.loadSessions(paneId);

            } catch (error) {
                console.error('Failed to delete sessions:', error);
                this.app.showToast('Failed to delete sessions', 'error');
            }
        });
    }

    async showFilesModal(sessionId, subpath = '') {
        // Get agent name
        const execUser = document.getElementById('globalUserFilter')?.value || NexusAPI.getDefaultExecUser();

        try {
            const data = await NexusAPI.getSessionFiles(sessionId, { execUser, subpath });

            // Create modal
            const modal = document.createElement('div');
            modal.className = 'modal-overlay';
            modal.id = 'filesModal';
            modal.innerHTML = `
                <div class="modal files-modal">
                    <div class="modal-header">
                        <h3>Session Files</h3>
                        <button class="modal-close" data-action="close-modal">&times;</button>
                    </div>
                    <div class="files-modal-path">
                        <span class="files-path-label">Path:</span>
                        <span class="files-path-value">${this.escapeHtml(data.folder_path)}</span>
                    </div>
                    <div class="files-breadcrumb">
                        ${this.renderBreadcrumb(sessionId, subpath)}
                    </div>
                    <div class="files-list">
                        ${data.files.length === 0
                            ? '<div class="files-empty">No files found</div>'
                            : data.files.map(file => this.renderFileItem(sessionId, file, execUser)).join('')}
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" data-action="close-modal">Close</button>
                    </div>
                </div>
            `;

            // Remove existing modal if any
            document.getElementById('filesModal')?.remove();
            document.body.appendChild(modal);

            // Bind events
            modal.querySelectorAll('[data-action="close-modal"]').forEach(btn => {
                btn.addEventListener('click', () => modal.remove());
            });

            modal.addEventListener('click', (e) => {
                if (e.target === modal) modal.remove();
            });

            // Bind folder navigation
            modal.querySelectorAll('[data-action="navigate-folder"]').forEach(link => {
                link.addEventListener('click', (e) => {
                    e.preventDefault();
                    const path = link.dataset.path;
                    modal.remove();
                    this.showFilesModal(sessionId, path);
                });
            });

            // Bind breadcrumb navigation
            modal.querySelectorAll('[data-action="navigate-breadcrumb"]').forEach(link => {
                link.addEventListener('click', (e) => {
                    e.preventDefault();
                    const path = link.dataset.path;
                    modal.remove();
                    this.showFilesModal(sessionId, path);
                });
            });

        } catch (error) {
            console.error('Failed to load session files:', error);
            this.app.showToast(error.message || 'Failed to load files', 'error');
        }
    }

    renderBreadcrumb(sessionId, subpath) {
        const parts = subpath ? subpath.split('/').filter(p => p) : [];
        let html = `<a href="#" data-action="navigate-breadcrumb" data-path="" class="breadcrumb-item">Root</a>`;

        let currentPath = '';
        for (const part of parts) {
            currentPath = currentPath ? `${currentPath}/${part}` : part;
            html += ` / <a href="#" data-action="navigate-breadcrumb" data-path="${this.escapeHtml(currentPath)}" class="breadcrumb-item">${this.escapeHtml(part)}</a>`;
        }

        return html;
    }

    renderFileItem(sessionId, file, execUser) {
        const sizeStr = file.size != null ? this.formatFileSize(file.size) : '';
        const modifiedStr = file.modified ? new Date(file.modified).toLocaleString() : '';

        if (file.is_dir) {
            return `
                <div class="file-item file-item-dir">
                    <div class="file-icon">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="20" height="20">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
                        </svg>
                    </div>
                    <a href="#" class="file-name" data-action="navigate-folder" data-path="${this.escapeHtml(file.path)}">${this.escapeHtml(file.name)}</a>
                    <div class="file-size"></div>
                    <div class="file-modified">${modifiedStr}</div>
                </div>
            `;
        } else {
            const downloadUrl = NexusAPI.getFileDownloadUrl(sessionId, file.path, { execUser });
            return `
                <div class="file-item">
                    <div class="file-icon">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="20" height="20">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"/>
                        </svg>
                    </div>
                    <a href="${downloadUrl}" class="file-name" target="_blank" download>${this.escapeHtml(file.name)}</a>
                    <div class="file-size">${sizeStr}</div>
                    <div class="file-modified">${modifiedStr}</div>
                </div>
            `;
        }
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }
}

// ============================================================
// Task View
// ============================================================
class TaskView {
    constructor(app) {
        this.app = app;
        this.tasks = {};
        this.selectedTask = {};
        this.selectionMode = {};  // paneId -> boolean
        this.selectedTaskIds = {}; // paneId -> Set<taskId>
        this.statusColumns = [
            { key: 'inbox', title: 'Inbox', color: 'var(--status-inbox)' },
            { key: 'assigned', title: 'Assigned', color: 'var(--status-assigned)' },
            { key: 'awaiting_owner', title: 'Awaiting Owner', color: 'var(--status-awaiting-owner)' },
            { key: 'in_progress', title: 'In Progress', color: 'var(--status-in-progress)' },
            { key: 'review', title: 'Review', color: 'var(--status-review)' },
            { key: 'quality_review', title: 'QA', color: 'var(--status-quality-review)' },
            { key: 'done', title: 'Done', color: 'var(--status-done)' },
        ];
        // Terminal status columns (shown in collapsed/overflow area)
        this.terminalColumns = [
            { key: 'failed', title: 'Failed', color: 'var(--status-failed)' },
            { key: 'cancelled', title: 'Cancelled', color: 'var(--status-cancelled)' },
        ];
        // For standalone task page
        this.fullPageRendered = false;
        // Active SSE streams for task conversation (taskId -> EventSource)
        this._activeStreams = new Map();
        // SmartPoll instance for visibility-aware kanban refresh
        this._smartPoll = null;
        this._pollInterval = 10000; // 10s (SmartPoll default)
        this._mentionInputsByPane = {}; // paneId -> MentionTextarea[]
    }

    _normalizeTaskStatus(status) {
        const s = String(status || '').trim().toLowerCase();
        // Map legacy/alternative status values to the 7-column model
        if (s === 'pending' || s === 'todo') return 'inbox';
        if (s === 'in_progress' || s === 'running' || s === 'doing') return 'in_progress';
        if (s === 'completed') return 'done';
        // New statuses pass through
        if (s === 'inbox' || s === 'assigned' || s === 'awaiting_owner' ||
            s === 'review' || s === 'quality_review' || s === 'done' ||
            s === 'failed' || s === 'cancelled' || s === 'archived') {
            return s;
        }
        return 'inbox';
    }

    // Render task view as a standalone full-page view (not in a pane/tab)
    async renderFullPage() {
        const container = document.getElementById('taskPageContainer');
        if (!container) return;

        // Use a fixed paneId for the full-page view
        const paneId = 'global';

        // Initialize selection state
        if (!this.selectionMode[paneId]) {
            this.selectionMode[paneId] = false;
        }
        if (!this.selectedTaskIds[paneId]) {
            this.selectedTaskIds[paneId] = new Set();
        }

        container.innerHTML = `
            <div class="task-container" style="height: 100%;">
                <div style="flex: 1; display: flex; flex-direction: column; overflow: hidden;">
                    <div class="task-toolbar">
                        <div class="task-toolbar-left">
                            <button class="action-btn primary" data-action="create-task">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                                </svg>
                                <span>New Task</span>
                            </button>
                            <button class="action-btn" data-action="toggle-selection" title="Toggle selection mode">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>
                                </svg>
                                <span>Select</span>
                            </button>
                            <button class="action-btn" data-action="toggle-schedules" title="Show/hide scheduled tasks">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                </svg>
                                <span>Schedules</span>
                            </button>
                            <div class="selection-actions" id="selectionActions-${paneId}" style="display: none;">
                                <button class="action-btn" data-action="select-all">
                                    <span>Select All</span>
                                </button>
                                <button class="action-btn" data-action="deselect-all">
                                    <span>Clear</span>
                                </button>
                                <button class="action-btn danger" data-action="delete-selected" id="deleteSelectedBtn-${paneId}">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                                    </svg>
                                    <span>Delete (0)</span>
                                </button>
                            </div>
                        </div>
                        <div class="task-toolbar-right">
                            <select class="form-input form-select" style="width: 150px; margin-right: 8px;" data-pane="${paneId}" id="taskProjectFilter-${paneId}">
                                <option value="">All Projects</option>
                            </select>
                            <input type="text" class="form-input" placeholder="Search tasks..." style="width: 200px;" data-pane="${paneId}" id="taskSearch-${paneId}">
                        </div>
                    </div>
                    <!-- Schedules Panel (collapsible) -->
                    <div class="schedule-panel" id="schedulePanel-${paneId}" style="display: none;">
                        <div class="schedule-panel-header">
                            <span class="schedule-panel-title">Scheduled Tasks</span>
                            <div class="schedule-panel-actions">
                                <select class="form-input form-select schedule-status-filter" id="scheduleStatusFilter-${paneId}" style="width:120px; height:30px; font-size:12px;">
                                    <option value="">All Status</option>
                                    <option value="active">Active</option>
                                    <option value="paused">Paused</option>
                                    <option value="cancelled">Cancelled</option>
                                </select>
                                <button class="action-btn schedule-refresh-btn" data-action="refresh-schedules" title="Refresh schedules">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:14px;height:14px;">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                                    </svg>
                                </button>
                            </div>
                        </div>
                        <div class="schedule-list" id="scheduleList-${paneId}">
                            <div class="empty-state" style="padding: 16px;">
                                <div class="loading-spinner" style="width: 18px; height: 18px;"></div>
                            </div>
                        </div>
                    </div>
                    <div class="kanban-board" id="kanbanBoard-${paneId}">
                        <div class="kanban-primary-columns">
                        ${this.statusColumns.map(col => `
                            <div class="kanban-column" data-status="${col.key}">
                                <div class="kanban-column-header">
                                    <span class="kanban-column-title">
                                        <span style="width: 8px; height: 8px; border-radius: 50%; background: ${col.color};"></span>
                                        ${col.title}
                                    </span>
                                    <span class="kanban-column-count" id="count-${paneId}-${col.key}">0</span>
                                </div>
                                <div class="kanban-column-items" id="items-${paneId}-${col.key}">
                                    <div class="empty-state" style="padding: 24px 16px;">
                                        <div class="loading-spinner" style="width: 20px; height: 20px;"></div>
                                    </div>
                                </div>
                            </div>
                        `).join('')}
                        </div>
                        <div class="kanban-terminal-columns" id="terminalColumns-${paneId}" style="display: none;">
                            <!-- Terminal status columns (failed, cancelled) rendered dynamically -->
                        </div>
                    </div>
                    <div id="expansionPanels-${paneId}" style="margin-top: 8px; border-top: 1px solid var(--border); padding-top: 8px; max-height: 260px; overflow-y: auto;">
                        <div class="empty-state" style="padding: 8px;">
                            <div class="loading-spinner" style="width: 16px; height: 16px;"></div>
                        </div>
                    </div>
                </div>
                <div class="task-detail hidden" id="taskDetail-${paneId}">
                    <!-- Task detail will be rendered here -->
                </div>
            </div>
        `;

        // Bind events for the full-page view
        this.bindTaskEvents(paneId, container);

        // Load tasks
        await this.loadTasks(paneId);

        // Keep task board fresh even when no task is running yet
        this._startAutoPolling(paneId);

        this.fullPageRendered = true;
    }

    async render(paneId, tab, container) {
        // Initialize selection state for this pane
        if (!this.selectionMode[paneId]) {
            this.selectionMode[paneId] = false;
        }
        if (!this.selectedTaskIds[paneId]) {
            this.selectedTaskIds[paneId] = new Set();
        }

        container.innerHTML = `
            <div class="task-container">
                <div style="flex: 1; display: flex; flex-direction: column; overflow: hidden;">
                    <div class="task-toolbar">
                        <div class="task-toolbar-left">
                            <button class="action-btn primary" data-action="create-task">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                                </svg>
                                <span>New Task</span>
                            </button>
                            <button class="action-btn" data-action="toggle-selection" title="Toggle selection mode">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>
                                </svg>
                                <span>Select</span>
                            </button>
                            <div class="selection-actions" id="selectionActions-${paneId}" style="display: none;">
                                <button class="action-btn" data-action="select-all">
                                    <span>Select All</span>
                                </button>
                                <button class="action-btn" data-action="deselect-all">
                                    <span>Clear</span>
                                </button>
                                <button class="action-btn danger" data-action="delete-selected" id="deleteSelectedBtn-${paneId}">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                                    </svg>
                                    <span>Delete (0)</span>
                                </button>
                            </div>
                        </div>
                        <div class="task-toolbar-right">
                            <select class="form-input form-select" style="width: 150px; margin-right: 8px;" data-pane="${paneId}" id="taskProjectFilter-${paneId}">
                                <option value="">All Projects</option>
                            </select>
                            <input type="text" class="form-input" placeholder="Search tasks..." style="width: 200px;" data-pane="${paneId}" id="taskSearch-${paneId}">
                        </div>
                    </div>
                    <div class="kanban-board" id="kanbanBoard-${paneId}">
                        <div class="kanban-primary-columns">
                        ${this.statusColumns.map(col => `
                            <div class="kanban-column" data-status="${col.key}">
                                <div class="kanban-column-header">
                                    <span class="kanban-column-title">
                                        <span style="width: 8px; height: 8px; border-radius: 50%; background: ${col.color};"></span>
                                        ${col.title}
                                    </span>
                                    <span class="kanban-column-count" id="count-${paneId}-${col.key}">0</span>
                                </div>
                                <div class="kanban-column-items" id="items-${paneId}-${col.key}">
                                    <div class="empty-state" style="padding: 24px 16px;">
                                        <div class="loading-spinner" style="width: 20px; height: 20px;"></div>
                                    </div>
                                </div>
                            </div>
                        `).join('')}
                        </div>
                        <div class="kanban-terminal-columns" id="terminalColumns-${paneId}" style="display: none;">
                            <!-- Terminal status columns (failed, cancelled) rendered dynamically -->
                        </div>
                    </div>
                    <div id="expansionPanels-${paneId}" style="margin-top: 8px; border-top: 1px solid var(--border); padding-top: 8px; max-height: 260px; overflow-y: auto;">
                        <div class="empty-state" style="padding: 8px;">
                            <div class="loading-spinner" style="width: 16px; height: 16px;"></div>
                        </div>
                    </div>
                </div>
                <div class="task-detail hidden" id="taskDetail-${paneId}">
                    <!-- Task detail will be rendered here -->
                </div>
            </div>
        `;

        this.bindEvents(paneId);
        await this.loadTasks(paneId);
    }

    bindTaskEvents(paneId, container) {
        // Create task button
        const createBtn = container.querySelector(`[data-action="create-task"]`);
        if (createBtn) {
            createBtn.addEventListener('click', () => {
                this.app.showCreateTaskModal('single');
            });
        }

        // Toggle selection mode button
        const toggleSelectionBtn = container.querySelector(`[data-action="toggle-selection"]`);
        if (toggleSelectionBtn) {
            toggleSelectionBtn.addEventListener('click', () => {
                this.toggleSelectionMode(paneId);
            });
        }

        // Select all button
        const selectAllBtn = container.querySelector(`[data-action="select-all"]`);
        if (selectAllBtn) {
            selectAllBtn.addEventListener('click', () => {
                this.selectAllTasks(paneId);
            });
        }

        // Deselect all button
        const deselectAllBtn = container.querySelector(`[data-action="deselect-all"]`);
        if (deselectAllBtn) {
            deselectAllBtn.addEventListener('click', () => {
                this.deselectAllTasks(paneId);
            });
        }

        // Delete selected button
        const deleteSelectedBtn = container.querySelector(`[data-action="delete-selected"]`);
        if (deleteSelectedBtn) {
            deleteSelectedBtn.addEventListener('click', () => {
                this.deleteSelectedTasks(paneId);
            });
        }

        // Search input
        const searchInput = document.getElementById(`taskSearch-${paneId}`);
        if (searchInput) {
            let timeout;
            searchInput.addEventListener('input', () => {
                clearTimeout(timeout);
                timeout = setTimeout(() => this.loadTasks(paneId), 300);
            });
        }

        // Project filter
        const projectFilter = document.getElementById(`taskProjectFilter-${paneId}`);
        if (projectFilter) {
            projectFilter.addEventListener('change', () => {
                this.loadTasks(paneId);
            });
        }

        // Toggle schedules panel
        const toggleSchedulesBtn = container.querySelector(`[data-action="toggle-schedules"]`);
        if (toggleSchedulesBtn) {
            toggleSchedulesBtn.addEventListener('click', () => {
                this.toggleSchedulePanel(paneId);
            });
        }

        // Refresh schedules
        const refreshSchedulesBtn = container.querySelector(`[data-action="refresh-schedules"]`);
        if (refreshSchedulesBtn) {
            refreshSchedulesBtn.addEventListener('click', () => {
                this.loadSchedules(paneId);
            });
        }

        // Schedule status filter
        const scheduleStatusFilter = document.getElementById(`scheduleStatusFilter-${paneId}`);
        if (scheduleStatusFilter) {
            scheduleStatusFilter.addEventListener('change', () => {
                this.loadSchedules(paneId);
            });
        }
    }

    bindEvents(paneId) {
        // Create task button
        const createBtn = document.querySelector(`#pane-${paneId}-content [data-action="create-task"]`);
        if (createBtn) {
            createBtn.addEventListener('click', () => {
                this.app.showCreateTaskModal('single');
            });
        }

        // Toggle selection mode button
        const toggleSelectionBtn = document.querySelector(`#pane-${paneId}-content [data-action="toggle-selection"]`);
        if (toggleSelectionBtn) {
            toggleSelectionBtn.addEventListener('click', () => {
                this.toggleSelectionMode(paneId);
            });
        }

        // Select all button
        const selectAllBtn = document.querySelector(`#pane-${paneId}-content [data-action="select-all"]`);
        if (selectAllBtn) {
            selectAllBtn.addEventListener('click', () => {
                this.selectAllTasks(paneId);
            });
        }

        // Deselect all button
        const deselectAllBtn = document.querySelector(`#pane-${paneId}-content [data-action="deselect-all"]`);
        if (deselectAllBtn) {
            deselectAllBtn.addEventListener('click', () => {
                this.deselectAllTasks(paneId);
            });
        }

        // Delete selected button
        const deleteSelectedBtn = document.querySelector(`#pane-${paneId}-content [data-action="delete-selected"]`);
        if (deleteSelectedBtn) {
            deleteSelectedBtn.addEventListener('click', () => {
                this.deleteSelectedTasks(paneId);
            });
        }

        // Search input
        const searchInput = document.getElementById(`taskSearch-${paneId}`);
        if (searchInput) {
            let timeout;
            searchInput.addEventListener('input', () => {
                clearTimeout(timeout);
                timeout = setTimeout(() => this.loadTasks(paneId), 300);
            });
        }

        // Project filter
        const projectFilter = document.getElementById(`taskProjectFilter-${paneId}`);
        if (projectFilter) {
            projectFilter.addEventListener('change', () => {
                this.loadTasks(paneId);
            });
        }
    }

    async loadProjects(paneId) {
        const globalUserFilter = document.getElementById('globalUserFilter');
        const filterEl = document.getElementById(`taskProjectFilter-${paneId}`);
        if (!filterEl) return;

        try {
            const projects = await NexusAPI.getProjects({
                execUser: globalUserFilter?.value || NexusAPI.getDefaultExecUser()
            });

            // Keep current selection
            const current = filterEl.value;

            filterEl.innerHTML = '<option value="">All Projects</option>' +
                projects.map(p => {
                    // Show pending/active count in dropdown
                    const count = (p.todo || 0) + (p.doing || 0);
                    const label = p.project_name || p.project_id;
                    const countBadge = count > 0 ? ` (${count})` : '';
                    return `<option value="${p.project_id}">${label}${countBadge}</option>`;
                }).join('');

            // Restore selection if it still exists
            if (current && Array.from(filterEl.options).some(o => o.value === current)) {
                filterEl.value = current;
            }
        } catch (error) {
            console.error('Failed to load projects:', error);
        }
    }

    async loadTasks(paneId) {
        const searchInput = document.getElementById(`taskSearch-${paneId}`);
        const projectFilter = document.getElementById(`taskProjectFilter-${paneId}`);
        const globalUserFilter = document.getElementById('globalUserFilter');

        try {
            // Load projects first to populate filter if empty
            if (projectFilter && projectFilter.options.length <= 1) {
                await this.loadProjects(paneId);
            }

            const options = {
                execUser: globalUserFilter?.value || NexusAPI.getDefaultExecUser(),
                pageSize: 100,
                search: searchInput?.value || '',
                projectId: projectFilter?.value || ''
            };

            const data = await NexusAPI.getTasks(options);
            this.tasks[paneId] = (data.tasks || []).map(task => ({
                ...task,
                status: this._normalizeTaskStatus(task.status),
            }));
            this.renderKanban(paneId);
            this.loadExpansionPanels(paneId);

            // Keep selected task detail synchronized with latest status/conversation availability
            const selectedId = this.selectedTask[paneId];
            if (selectedId) {
                const latestTask = this.tasks[paneId].find(t => t.id === selectedId);
                const detailPanel = document.getElementById(`taskDetail-${paneId}`);

                if (!latestTask) {
                    this._closeTaskStream(selectedId);
                    this.selectedTask[paneId] = null;
                    if (detailPanel) {
                        detailPanel.classList.add('hidden');
                    }
                } else if (detailPanel) {
                    const latestStatus = this._normalizeTaskStatus(latestTask.status);
                    const renderedTaskId = detailPanel.dataset.taskId || '';
                    const renderedStatus = detailPanel.dataset.taskStatus || '';
                    const hasConversationDom = !!detailPanel.querySelector(`#taskConversation-${paneId}`);
                    const shouldHaveConversation = ['doing', 'done', 'completed', 'failed'].includes(latestStatus);
                    const isStreaming = this._activeStreams.has(selectedId);

                    const needsRerender =
                        renderedTaskId !== selectedId ||
                        renderedStatus !== latestStatus ||
                        (shouldHaveConversation && !hasConversationDom);

                    if (needsRerender && !isStreaming) {
                        this.renderTaskDetail(paneId, latestTask);
                    }
                }
            }
        } catch (error) {
            console.error('Failed to load tasks:', error);
            this.statusColumns.forEach(col => {
                const container = document.getElementById(`items-${paneId}-${col.key}`);
                if (container) {
                    container.innerHTML = `
                        <div class="empty-state" style="padding: 16px;">
                            <p style="font-size: 12px; color: var(--error);">Failed to load</p>
                        </div>
                    `;
                }
            });
        }
    }

    async loadExpansionPanels(paneId) {
        const root = document.getElementById(`expansionPanels-${paneId}`);
        if (!root) return;

        try {
            const globalUserFilter = document.getElementById('globalUserFilter');
            const username = globalUserFilter?.value || '';
            const data = await NexusAPI.getSessions({
                page: 1,
                pageSize: 200,
                username: username || undefined,
            });
            const sessions = Array.isArray(data?.sessions) ? data.sessions : [];

            if (window.ExpansionPanels && typeof window.ExpansionPanels.render === 'function') {
                window.ExpansionPanels.render(root, sessions);
                return;
            }

            root.innerHTML = `<div style="font-size:12px;color:var(--text-muted);">Session monitor unavailable.</div>`;
        } catch (error) {
            console.error('Failed to load expansion panels:', error);
            root.innerHTML = `<div style="font-size:12px;color:var(--error);">Failed to load session monitor</div>`;
        }
    }

    renderKanban(paneId) {
        const tasks = this.tasks[paneId] || [];
        
        // Group tasks by status
        const grouped = {};
        this.statusColumns.forEach(col => {
            grouped[col.key] = [];
        });

        tasks.forEach(task => {
            const status = (task.status || 'inbox').toLowerCase();
            if (grouped[status]) {
                grouped[status].push(task);
            } else {
                grouped['inbox'].push(task);
            }
        });

        // Render each primary column
        this.statusColumns.forEach(col => {
            const items = grouped[col.key] || [];
            const container = document.getElementById(`items-${paneId}-${col.key}`);
            const countEl = document.getElementById(`count-${paneId}-${col.key}`);

            if (countEl) countEl.textContent = items.length;

            if (container) {
                if (items.length === 0) {
                    container.innerHTML = `
                        <div class="empty-state" style="padding: 24px 16px;">
                            <p style="font-size: 12px; color: var(--text-muted);">No tasks</p>
                        </div>
                    `;
                } else {
                    container.innerHTML = items.map(task => this.renderTaskCard(task, paneId)).join('');

                    // Bind click events
                    container.querySelectorAll('.task-card').forEach(card => {
                        card.addEventListener('click', (e) => {
                            // Don't select task if clicking on checkbox area
                            if (e.target.closest('.task-card-checkbox')) {
                                return;
                            }
                            this.selectTask(paneId, card.dataset.taskId);
                        });
                    });

                    // Bind checkbox events (for selection mode)
                    container.querySelectorAll('.task-card-checkbox').forEach(checkboxDiv => {
                        checkboxDiv.addEventListener('click', (e) => {
                            e.stopPropagation();
                            const taskId = checkboxDiv.dataset.taskId;
                            this.toggleTaskSelection(paneId, taskId);
                        });
                    });
                }
            }
        });

        // Render terminal columns (failed, cancelled) — compact collapsed section
        const terminalContainer = document.getElementById(`terminalColumns-${paneId}`);
        if (terminalContainer) {
            const terminalTasks = [];
            this.terminalColumns.forEach(col => {
                const items = tasks.filter(t => this._normalizeTaskStatus(t.status) === col.key);
                if (items.length > 0) {
                    terminalTasks.push({ col, items });
                }
            });

            if (terminalTasks.length > 0) {
                terminalContainer.style.display = 'flex';
                terminalContainer.innerHTML = terminalTasks.map(({ col, items }) => `
                    <div class="kanban-column kanban-column-terminal" data-status="${col.key}">
                        <div class="kanban-column-header">
                            <span class="kanban-column-title">
                                <span style="width: 8px; height: 8px; border-radius: 50%; background: ${col.color};"></span>
                                ${col.title}
                            </span>
                            <span class="kanban-column-count">${items.length}</span>
                        </div>
                        <div class="kanban-column-items">
                            ${items.map(task => this.renderTaskCard(task, paneId)).join('')}
                        </div>
                    </div>
                `).join('');

                // Bind click events for terminal column cards
                terminalContainer.querySelectorAll('.task-card').forEach(card => {
                    card.addEventListener('click', (e) => {
                        if (e.target.closest('.task-card-checkbox')) return;
                        this.selectTask(paneId, card.dataset.taskId);
                    });
                });
                terminalContainer.querySelectorAll('.task-card-checkbox').forEach(checkboxDiv => {
                    checkboxDiv.addEventListener('click', (e) => {
                        e.stopPropagation();
                        this.toggleTaskSelection(paneId, checkboxDiv.dataset.taskId);
                    });
                });
            } else {
                terminalContainer.style.display = 'none';
            }
        }

        this._bindKanbanDragDrop(paneId);

        // Ensure polling is active on task page so status transitions are picked up without manual refresh
        this._startAutoPolling(paneId);
    }

    _bindKanbanDragDrop(paneId) {
        const board = document.getElementById(`kanbanBoard-${paneId}`);
        if (!board || typeof KanbanDragDrop === 'undefined') return;

        KanbanDragDrop.mount(board, {
            getTaskStatus: (taskId) => {
                const task = (this.tasks[paneId] || []).find((item) => item.id === taskId);
                return task ? this._normalizeTaskStatus(task.status) : null;
            },
            onMove: async (taskId, toStatus, fromStatus) => {
                const globalUserFilter = document.getElementById('globalUserFilter');
                const execUser = globalUserFilter?.value || NexusAPI.getDefaultExecUser();
                try {
                    await NexusAPI.updateTaskStatus(taskId, toStatus, { execUser });
                    const localTask = (this.tasks[paneId] || []).find((item) => item.id === taskId);
                    if (localTask) {
                        localTask.status = toStatus;
                    }
                    this.renderKanban(paneId);
                    if (this.selectedTask[paneId] === taskId) {
                        const task = (this.tasks[paneId] || []).find((item) => item.id === taskId);
                        if (task) this.renderTaskDetail(paneId, task);
                    }
                    this.app?.showToast?.(`Task moved: ${fromStatus} → ${toStatus}`, 'success');
                } catch (error) {
                    console.error('Failed to move task:', error);
                    this.app?.showToast?.(`Move failed: ${error.message}`, 'error');
                    await this.loadTasks(paneId);
                }
            },
        });
    }

    renderTaskCard(task, paneId) {
        const priorityClass = task.priority === 'critical' ? 'critical' :
                             task.priority === 'serious' ? 'serious' : 'normal';
        const timeStr = this.formatTime(task.updated_at || task.created_at);
        const isSelected = this.selectedTask[paneId] === task.id;
        const isInSelectionMode = this.selectionMode[paneId];
        const isChecked = this.selectedTaskIds[paneId]?.has(task.id);
        const alias = String(task?.alias || '').trim();
        const provider = String(task?.provider || '').trim();
        const targetInfo = {
            primary: alias || provider,
            secondary: alias && provider && alias.toLowerCase() !== provider.toLowerCase() ? provider : '',
            tooltip: alias && provider && alias.toLowerCase() !== provider.toLowerCase()
                ? `Alias: ${alias} · Provider: ${provider}`
                : (alias || provider),
        };

        // Priority color bar (left border)
        const priorityColors = {
            critical: 'var(--error)',
            serious: 'var(--warning)',
            normal: 'var(--primary-500)',
        };
        const priorityBarColor = priorityColors[priorityClass] || 'transparent';

        // Agent avatar
        const agentName = task.assigned_to || alias || provider || '';
        const agentAvatar = agentName ? AgentAvatar.render(agentName, { size: 'xs', status: this._normalizeTaskStatus(task.status) === 'in_progress' ? 'online' : 'none' }) : '';

        // Tags display (up to 3 + count)
        const tags = Array.isArray(task.tags) ? task.tags : [];
        const visibleTags = tags.slice(0, 3);
        const extraTagCount = tags.length > 3 ? tags.length - 3 : 0;
        const tagsHtml = tags.length > 0 ? `
            <div class="task-card-tags">
                ${visibleTags.map(tag => `<span class="task-card-tag">${this.escapeHtml(tag)}</span>`).join('')}
                ${extraTagCount > 0 ? `<span class="task-card-tag task-card-tag-more">+${extraTagCount}</span>` : ''}
            </div>
        ` : '';

        // Overdue highlight
        const isOverdue = task.due_date && (task.due_date * 1000 < Date.now()) && this._normalizeTaskStatus(task.status) !== 'done';
        const overdueHtml = isOverdue ? '<span class="task-card-overdue">! Overdue</span>' : '';

        // Awaiting owner detection
        const isAwaitingOwner = this._detectAwaitingOwner(task);
        const awaitingBadge = isAwaitingOwner && this._normalizeTaskStatus(task.status) !== 'awaiting_owner'
            ? '<span class="task-card-awaiting-badge">⚠ Needs Attention</span>' : '';

        const githubUrl = this._resolveGitHubIssueUrl(task);
        const githubLabel = this._resolveGitHubIssueLabel(task);
        const githubState = String(task.github_state || '').trim().toLowerCase();
        const githubStateColor = githubState === 'closed' ? 'var(--success)' : 'var(--primary-500)';
        const githubBadge = githubLabel
            ? (githubUrl
                ? `<a href="${this.escapeHtml(githubUrl)}" target="_blank" rel="noopener noreferrer" title="Open GitHub issue" style="font-size: 10px; padding: 1px 6px; border-radius: 4px; border: 1px solid ${githubStateColor}; color: ${githubStateColor}; text-decoration: none;">GH ${this.escapeHtml(githubLabel)}${githubState ? ` · ${this.escapeHtml(githubState)}` : ''}</a>`
                : `<span style="font-size: 10px; padding: 1px 6px; border-radius: 4px; border: 1px solid ${githubStateColor}; color: ${githubStateColor};">GH ${this.escapeHtml(githubLabel)}${githubState ? ` · ${this.escapeHtml(githubState)}` : ''}</span>`)
            : '';

        const aegisBadge = task.aegis_approved
            ? '<span style="font-size: 10px; padding: 1px 6px; border-radius: 4px; background: rgba(16,185,129,0.16); color: var(--success); font-weight: 600;">Aegis ✓</span>'
            : '';

        return `
            <div class="task-card ${isSelected ? 'selected' : ''} ${isChecked ? 'checked' : ''} ${isOverdue ? 'task-card-overdue-state' : ''} ${isAwaitingOwner ? 'task-card-needs-attention' : ''}" data-task-id="${task.id}" draggable="${!isInSelectionMode}" style="border-left: 3px solid ${priorityBarColor};">
                ${isInSelectionMode ? `
                    <div class="task-card-checkbox" data-task-id="${task.id}">
                        <input type="checkbox" ${isChecked ? 'checked' : ''}>
                    </div>
                ` : ''}
                <div class="task-card-content">
                    <div class="task-card-header">
                        <span class="task-card-id">#${task.id.slice(0, 8)}</span>
                        ${task.ticket_ref ? `<span class="task-card-ticket-ref" title="Project ticket">${this.escapeHtml(task.ticket_ref)}</span>` : ''}
                        ${githubBadge}
                        ${aegisBadge}
                        ${task.priority ? `<span class="task-card-priority ${priorityClass}">${task.priority}</span>` : ''}
                        ${task.loop_enabled ? `<span style="font-size: 10px; padding: 1px 6px; border-radius: 4px; background: ${task.loop_keyword_found ? 'var(--success, #22c55e)' : 'var(--accent, #6366f1)'}; color: #fff; font-weight: 600;">Loop ${task.loop_iteration || 0}/${task.loop_max_iterations || 1}${task.loop_keyword_found ? ' ✓' : ''}</span>` : ''}
                        ${overdueHtml}
                        ${awaitingBadge}
                    </div>
                    <p class="task-card-title">${this.escapeHtml(task.description || 'No description')}</p>
                    ${tagsHtml}
                    <div class="task-card-meta">
                        ${agentAvatar ? `<span class="task-card-meta-item">${agentAvatar}</span>` : ''}
                        <span class="task-card-meta-item">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                            </svg>
                            ${timeStr}
                        </span>
                        ${targetInfo.primary ? `
                            <span class="task-card-meta-item" title="${this.escapeHtml(targetInfo.tooltip)}">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                                </svg>
                                <span>${this.escapeHtml(targetInfo.primary)}</span>
                                ${targetInfo.secondary ? `<span class="task-provider-base">${this.escapeHtml(targetInfo.secondary)}</span>` : ''}
                            </span>
                        ` : ''}
                    </div>
                    ${task.depends_on && task.depends_on.length > 0 ? `
                        <div class="task-card-deps">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width: 12px; height: 12px; color: var(--text-muted);">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/>
                            </svg>
                            ${task.depends_on.map(dep => `<span class="task-card-dep">${dep.slice(0, 8)}</span>`).join('')}
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }

    _resolveGitHubIssueLabel(task) {
        const issueNumber = task?.github_issue_number;
        if (Number.isInteger(issueNumber)) {
            return `#${issueNumber}`;
        }
        const ticketRef = String(task?.ticket_ref || '').trim();
        const match = ticketRef.match(/^([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)#(\d+)$/);
        if (match) {
            return `${match[1]}#${match[2]}`;
        }
        return '';
    }

    _resolveGitHubIssueUrl(task) {
        const direct = String(task?.github_url || '').trim();
        if (direct) return direct;

        const ticketRef = String(task?.ticket_ref || '').trim();
        const match = ticketRef.match(/^([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)#(\d+)$/);
        if (!match) return '';
        const repo = match[1];
        const issue = match[2];
        return `https://github.com/${repo}/issues/${issue}`;
    }

    async selectTask(paneId, taskId) {
        this.selectedTask[paneId] = taskId;

        // Update selection state
        const board = document.getElementById(`kanbanBoard-${paneId}`);
        board?.querySelectorAll('.task-card').forEach(card => {
            card.classList.toggle('selected', card.dataset.taskId === taskId);
        });

        // Show detail panel
        await this.showTaskDetail(paneId, taskId);
    }

    async showTaskDetail(paneId, taskId) {
        const detailPanel = document.getElementById(`taskDetail-${paneId}`);
        if (!detailPanel) return;

        detailPanel.classList.remove('hidden');
        detailPanel.innerHTML = `
            <div class="empty-state">
                <div class="loading-spinner"></div>
            </div>
        `;

        try {
            const globalUserFilter = document.getElementById('globalUserFilter');
            const task = await NexusAPI.getTask(taskId, { 
                execUser: globalUserFilter?.value || NexusAPI.getDefaultExecUser() 
            });
            this.renderTaskDetail(paneId, task);
        } catch (error) {
            console.error('Failed to load task:', error);
            detailPanel.innerHTML = `
                <div class="empty-state">
                    <p style="color: var(--error);">Failed to load task details</p>
                </div>
            `;
        }
    }

    renderTaskDetail(paneId, task) {
        const detailPanel = document.getElementById(`taskDetail-${paneId}`);
        if (!detailPanel) return;

        // Close any existing SSE stream for previous task
        this._closeTaskStream(this.selectedTask[paneId]);

        const statusClass = this._normalizeTaskStatus(task.status);
        const isRunning = statusClass === 'in_progress';
        const hasConversation = isRunning || statusClass === 'done' || statusClass === 'completed' || statusClass === 'failed';
        const alias = String(task?.alias || '').trim();
        const provider = String(task?.provider || '').trim();
        const targetInfo = {
            primary: alias || provider,
            secondary: alias && provider && alias.toLowerCase() !== provider.toLowerCase() ? provider : '',
            tooltip: alias && provider && alias.toLowerCase() !== provider.toLowerCase()
                ? `Alias: ${alias} · Provider: ${provider}`
                : (alias || provider),
        };

        detailPanel.dataset.taskId = task.id;
        detailPanel.dataset.taskStatus = statusClass;

        detailPanel.innerHTML = `
            <div class="task-detail-header">
                <span class="task-detail-title">#${task.id.slice(0, 8)}</span>
                <button class="task-detail-close" data-action="close-detail">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>
            <div class="task-detail-content" style="display: flex; flex-direction: column; overflow: hidden; flex: 1;">
                <div class="task-detail-section" style="flex-shrink: 0;">
                    <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <span class="status-badge ${statusClass}">
                            <span class="status-dot"></span>
                            ${task.status || 'TODO'}
                        </span>
                        ${targetInfo.primary ? `<span class="task-target-badge" title="${this.escapeHtml(targetInfo.tooltip)}">${this.escapeHtml(targetInfo.primary)}</span>` : ''}
                        ${targetInfo.secondary ? `<span class="task-target-badge task-target-badge-base" title="Base provider">${this.escapeHtml(targetInfo.secondary)}</span>` : ''}
                        ${task.workspace ? `<span style="font-size: 11px; color: var(--text-muted); font-family: var(--font-mono);" title="${this.escapeHtml(task.workspace)}">${this.escapeHtml(task.workspace.split('/').pop() || task.workspace)}</span>` : ''}
                    </div>
                    <p style="margin: 6px 0 0; font-size: 13px; color: var(--text-secondary);">${this.escapeHtml(task.description || 'No description')}</p>
                    ${task.error_message ? `<p style="margin: 4px 0 0; font-size: 12px; color: var(--error);">${this.escapeHtml(task.error_message)}</p>` : ''}
                    ${this._resolveGitHubIssueLabel(task) ? `
                        <p style="margin: 6px 0 0; font-size: 12px; color: var(--text-secondary);">
                            GitHub: ${this._resolveGitHubIssueUrl(task)
                                ? `<a href="${this.escapeHtml(this._resolveGitHubIssueUrl(task))}" target="_blank" rel="noopener noreferrer" style="color: var(--primary-500);">${this.escapeHtml(this._resolveGitHubIssueLabel(task))}</a>`
                                : this.escapeHtml(this._resolveGitHubIssueLabel(task))}
                            ${task.github_state ? `<span style="margin-left: 6px; color: var(--text-muted);">(${this.escapeHtml(String(task.github_state))})</span>` : ''}
                        </p>
                    ` : ''}
                    ${(task.aegis_status || task.aegis_approved) ? `
                        <p style="margin: 4px 0 0; font-size: 12px; color: ${task.aegis_approved ? 'var(--success)' : 'var(--warning)'};">
                            Aegis: ${task.aegis_approved ? 'Approved' : this.escapeHtml(String(task.aegis_status || 'pending'))}
                            ${task.aegis_reason ? `<span style="color: var(--text-muted);"> · ${this.escapeHtml(task.aegis_reason)}</span>` : ''}
                        </p>
                    ` : ''}
                    ${task.loop_enabled ? `
                        <div style="margin-top: 8px; padding: 8px 10px; background: var(--bg-secondary); border-radius: 6px; font-size: 12px;">
                            <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 4px;">
                                <span style="font-weight: 600; color: var(--text-primary);">Ralph Loop</span>
                                <span style="padding: 1px 6px; border-radius: 4px; background: ${task.loop_keyword_found ? 'var(--success, #22c55e)' : 'var(--accent, #6366f1)'}; color: #fff; font-weight: 600; font-size: 10px;">
                                    ${task.loop_iteration || 0}/${task.loop_max_iterations || 1}${task.loop_keyword_found ? ' \u2713 Found' : ''}
                                </span>
                            </div>
                            <div style="color: var(--text-secondary);">
                                <span>Keywords: </span>
                                ${(task.loop_keywords || []).map(kw => `<code style="background: var(--bg-tertiary, #374151); padding: 1px 4px; border-radius: 3px; font-size: 11px;">${this.escapeHtml(kw)}</code>`).join(' ')}
                            </div>
                        </div>
                    ` : ''}
                </div>

                <div class="task-conversation" style="flex: 1; overflow: hidden; border-top: 1px solid var(--border); margin-top: 8px; padding-top: 8px; display: flex; flex-direction: column; gap: 8px;">
                    <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                        <button class="action-btn task-detail-tab active" data-task-tab="details" data-pane-id="${paneId}" style="padding: 4px 10px;">Details</button>
                        <button class="action-btn task-detail-tab" data-task-tab="comments" data-pane-id="${paneId}" style="padding: 4px 10px;">Comments</button>
                        <button class="action-btn task-detail-tab" data-task-tab="quality" data-pane-id="${paneId}" style="padding: 4px 10px;">Quality</button>
                        <button class="action-btn task-detail-tab" data-task-tab="timeline" data-pane-id="${paneId}" style="padding: 4px 10px;">Timeline</button>
                        <button class="action-btn task-detail-tab" data-task-tab="session" data-pane-id="${paneId}" style="padding: 4px 10px;">Session</button>
                    </div>
                    <div id="taskTabDetails-${paneId}" data-task-tab-pane="details" style="flex: 1; overflow-y: auto;">
                        <div id="taskDetailsPanel-${paneId}" style="padding: 8px 4px; font-size: 12px; color: var(--text-secondary);"></div>
                    </div>
                    <div id="taskTabComments-${paneId}" data-task-tab-pane="comments" style="display: none; overflow-y: auto;">
                        <div id="taskComments-${paneId}" style="padding: 8px 4px; font-size: 12px; color: var(--text-secondary);">
                            <div class="loading-spinner" style="width: 18px; height: 18px;"></div>
                        </div>
                    </div>
                    <div id="taskTabQuality-${paneId}" data-task-tab-pane="quality" style="display: none; overflow-y: auto;">
                        <div id="taskQuality-${paneId}" style="padding: 8px 4px; font-size: 12px; color: var(--text-secondary);">
                            <div class="loading-spinner" style="width: 18px; height: 18px;"></div>
                        </div>
                    </div>
                    <div id="taskTabTimeline-${paneId}" data-task-tab-pane="timeline" style="display: none; overflow-y: auto;">
                        <div id="taskTimeline-${paneId}" style="padding: 8px 4px; font-size: 12px; color: var(--text-secondary);">
                            <div class="loading-spinner" style="width: 18px; height: 18px;"></div>
                        </div>
                    </div>
                    <div id="taskTabSession-${paneId}" data-task-tab-pane="session" style="display: none; flex: 1; overflow-y: auto;">
                        ${hasConversation ? `
                            <div class="chat-messages" id="taskConversation-${paneId}" style="padding: 0;">
                                <div class="empty-state" style="padding: 24px;">
                                    <div class="loading-spinner"></div>
                                    <p style="font-size: 12px; color: var(--text-muted); margin-top: 8px;">${isRunning ? 'Connecting to live stream...' : 'Loading conversation...'}</p>
                                </div>
                            </div>
                        ` : `
                            <div class="empty-state" style="padding: 24px;">
                                <p style="font-size: 12px; color: var(--text-muted);">Session view is available after task execution starts.</p>
                            </div>
                        `}
                    </div>
                </div>

                <div class="task-detail-section" style="flex-shrink: 0; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border);">
                    <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                        ${hasConversation ? `
                            <button class="action-btn" data-action="view-session" data-task-id="${task.id}" title="Open in Chat view">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
                                </svg>
                                Open Session
                            </button>
                        ` : ''}
                        <button class="action-btn" data-action="broadcast-task" data-task-id="${task.id}" title="Broadcast to subscribers">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405C18.21 15.21 18 14.702 18 14.172V11a6.002 6.002 0 00-4-5.659V4a2 2 0 10-4 0v1.341C7.67 6.165 6 8.388 6 11v3.172c0 .53-.21 1.039-.595 1.423L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/>
                            </svg>
                            Broadcast
                        </button>
                        <button class="action-btn" data-action="delete-task" data-task-id="${task.id}" style="color: var(--error);">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                            </svg>
                            Delete
                        </button>
                    </div>
                </div>
            </div>
        `;

        // Bind events
        const closeBtn = detailPanel.querySelector('[data-action="close-detail"]');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                this._closeTaskStream(task.id);
                detailPanel.classList.add('hidden');
                this.selectedTask[paneId] = null;
                
                const board = document.getElementById(`kanbanBoard-${paneId}`);
                board?.querySelectorAll('.task-card').forEach(card => {
                    card.classList.remove('selected');
                });
            });
        }

        const deleteBtn = detailPanel.querySelector('[data-action="delete-task"]');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', () => {
                this.app.showDeleteModal('task', task.id, async () => {
                    await this.deleteTask(paneId, task.id);
                });
            });
        }

        const broadcastBtn = detailPanel.querySelector('[data-action="broadcast-task"]');
        if (broadcastBtn) {
            broadcastBtn.addEventListener('click', async () => {
                const message = window.prompt('Broadcast message to task subscribers:');
                if (!message || !message.trim()) return;
                const globalUserFilter = document.getElementById('globalUserFilter');
                const execUser = globalUserFilter?.value || NexusAPI.getDefaultExecUser();
                try {
                    const result = await NexusAPI.broadcastTask(task.id, {
                        message: message.trim(),
                        sender: 'user',
                        include_assignee: true,
                    }, { execUser });
                    this.app?.showToast?.(`Broadcast sent to ${result.delivered || 0} subscribers`, 'success');
                } catch (error) {
                    console.error('Failed to broadcast task message:', error);
                    this.app?.showToast?.(error.message || 'Failed to broadcast', 'error');
                }
            });
        }

        const viewSessionBtn = detailPanel.querySelector('[data-action="view-session"]');
        if (viewSessionBtn) {
            viewSessionBtn.addEventListener('click', () => {
                const sessionId = task.session_id || `task_${task.id}`;
                this.app.pageManager.setPage('chat');
                setTimeout(() => {
                    this.app.chatView.selectSession(0, sessionId);
                }, 300);
            });
        }

        this._bindTaskDetailTabs(detailPanel, paneId);
        this._loadTaskDetailsPanel(paneId, task);
        this._loadTaskCommentsPanel(paneId, task.id);
        this._loadTaskQualityPanel(paneId, task.id);
        this._loadTaskTimelinePanel(paneId, task.id);

        // Load or stream conversation
        if (hasConversation) {
            if (isRunning) {
                this._streamTaskConversation(paneId, task.id);
            } else {
                this._loadTaskConversation(paneId, task.id);
            }
        }
    }

    _bindTaskDetailTabs(detailPanel, paneId) {
        const buttons = detailPanel.querySelectorAll('.task-detail-tab');
        const panes = {
            details: detailPanel.querySelector(`#taskTabDetails-${paneId}`),
            comments: detailPanel.querySelector(`#taskTabComments-${paneId}`),
            quality: detailPanel.querySelector(`#taskTabQuality-${paneId}`),
            timeline: detailPanel.querySelector(`#taskTabTimeline-${paneId}`),
            session: detailPanel.querySelector(`#taskTabSession-${paneId}`),
        };

        buttons.forEach((btn) => {
            btn.addEventListener('click', () => {
                const target = btn.getAttribute('data-task-tab') || 'details';
                buttons.forEach((b) => b.classList.toggle('active', b === btn));
                Object.entries(panes).forEach(([key, pane]) => {
                    if (!pane) return;
                    pane.style.display = key === target ? '' : 'none';
                });
            });
        });
    }

    _loadTaskDetailsPanel(paneId, task) {
        const detailsRoot = document.getElementById(`taskDetailsPanel-${paneId}`);
        if (!detailsRoot) return;

        const descHtml = this.app?.chatView?.formatMessageContent
            ? this.app.chatView.formatMessageContent(task.description || '')
            : this.escapeHtml(task.description || '');

        detailsRoot.innerHTML = `
            <div style="display:grid;grid-template-columns:120px 1fr;gap:6px 10px;font-size:12px;">
                <span style="color:var(--text-muted);">Task ID</span><span>${this.escapeHtml(task.id || '')}</span>
                <span style="color:var(--text-muted);">Status</span><span>${this.escapeHtml(task.status || '')}</span>
                <span style="color:var(--text-muted);">Priority</span><span>${this.escapeHtml(task.priority || '')}</span>
                <span style="color:var(--text-muted);">Assignee</span><span>${this.escapeHtml(task.assigned_to || '-')}</span>
                <span style="color:var(--text-muted);">Source Session</span><span>${this.escapeHtml(task.source_session_id || '-')}</span>
                <span style="color:var(--text-muted);">Created</span><span>${this.escapeHtml(task.created_at ? new Date(task.created_at).toLocaleString() : '-')}</span>
                <span style="color:var(--text-muted);">Updated</span><span>${this.escapeHtml(task.updated_at ? new Date(task.updated_at).toLocaleString() : '-')}</span>
                <span style="color:var(--text-muted);">Depends On</span><span>${Array.isArray(task.depends_on) && task.depends_on.length ? this.escapeHtml(task.depends_on.join(', ')) : '-'}</span>
            </div>
            <div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border);">
                <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px;">Description (Markdown)</div>
                <div class="message-text">${descHtml}</div>
            </div>
        `;
    }


    async _loadTaskCommentsPanel(paneId, taskId) {
        if (typeof TaskComponents?.renderTaskComments !== 'function') return;
        const container = document.getElementById(`taskComments-${paneId}`);
        if (!container) return;
        await TaskComponents.renderTaskComments(container, taskId, {
            paneId,
            mentionInputsByPane: this._mentionInputsByPane,
        });
    }

    async _loadTaskQualityPanel(paneId, taskId) {
        if (typeof TaskComponents?.renderQualityGate !== 'function') return;
        const container = document.getElementById(`taskQuality-${paneId}`);
        if (!container) return;
        await TaskComponents.renderQualityGate(container, taskId, {
            paneId,
            onRefresh: async (tid) => {
                await this.loadTasks(paneId);
                await this.showTaskDetail(paneId, tid);
            },
        });
    }

    async _loadTaskTimelinePanel(paneId, taskId) {
        if (typeof TaskComponents?.renderTaskTimeline !== 'function') return;
        const container = document.getElementById(`taskTimeline-${paneId}`);
        if (!container) return;
        await TaskComponents.renderTaskTimeline(container, taskId, { paneId });
    }

    /**
     * Connect to SSE stream and render AG-UI events in real-time for a running task.
     * Also used for replaying completed tasks (isReplay=true skips kanban refresh on finish).
     */
    _streamTaskConversation(paneId, taskId, isReplay = false) {
        this._closeTaskStream(taskId);

        const container = document.getElementById(`taskConversation-${paneId}`);
        if (!container) return;

        const globalUserFilter = document.getElementById('globalUserFilter');
        const execUser = globalUserFilter?.value || NexusAPI.getDefaultExecUser();

        const es = NexusAPI.streamTaskMessages(taskId, { execUser, tail: 5000 });
        this._activeStreams.set(taskId, es);

        // State for streaming rendering
        let bubbleEl = null;
        let currentTextEl = null;
        let currentTextContent = '';
        let textSegmentIndex = 0;
        const streamingToolCalls = new Map();
        let initialized = false;
        let runFinished = false;

        const chatView = this.app.chatView;

        const ensureBubble = () => {
            if (!bubbleEl) {
                // Clear loading state
                if (!initialized) {
                    container.innerHTML = '';
                    initialized = true;
                }
                const msgId = `task-stream-msg-${Date.now()}`;
                container.insertAdjacentHTML('beforeend', `
                    <div class="message assistant" id="${msgId}">
                        <div class="message-avatar assistant">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="18" height="18">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                            </svg>
                        </div>
                        <div class="message-content">
                            <div class="message-bubble streaming-bubble" id="task-bubble-${msgId}"></div>
                        </div>
                    </div>
                `);
                bubbleEl = document.getElementById(`task-bubble-${msgId}`);
            }
            return bubbleEl;
        };

        const ensureTextElement = () => {
            if (!currentTextEl) {
                const bubble = ensureBubble();
                if (bubble) {
                    const textId = `task-stream-text-${taskId}-seg${textSegmentIndex}`;
                    bubble.insertAdjacentHTML('beforeend', `<div class="message-text streaming" id="${textId}"></div>`);
                    currentTextEl = document.getElementById(textId);
                }
            }
            return currentTextEl;
        };

        es.onmessage = (event) => {
            if (runFinished) return;
            let data;
            try {
                data = JSON.parse(event.data);
            } catch { return; }

            if (data.type === 'TEXT_MESSAGE_START') {
                ensureBubble();
            } else if (data.type === 'TEXT_MESSAGE_CONTENT') {
                const textDelta = data.delta ?? data.content ?? data.text ?? data.response;
                if (textDelta !== undefined && textDelta !== null && textDelta !== '') {
                    const textEl = ensureTextElement();
                    currentTextContent += (typeof textDelta === 'string' ? textDelta : JSON.stringify(textDelta, null, 2));
                    if (textEl) {
                        textEl.innerHTML = chatView.formatMessageContent(currentTextContent);
                        container.scrollTop = container.scrollHeight;
                    }
                }
            } else if (data.type === 'result') {
                const resultText = data.content ?? data.result;
                if (resultText !== undefined && resultText !== null && resultText !== '') {
                    const textEl = ensureTextElement();
                    currentTextContent += (typeof resultText === 'string' ? resultText : JSON.stringify(resultText, null, 2));
                    if (textEl) {
                        textEl.innerHTML = chatView.formatMessageContent(currentTextContent);
                        container.scrollTop = container.scrollHeight;
                    }
                }
            } else if (data.type === 'TEXT_MESSAGE_END') {
                if (currentTextEl) {
                    currentTextEl.classList.remove('streaming');
                }
                currentTextEl = null;
                currentTextContent = '';
                textSegmentIndex++;
            } else if (data.type === 'TOOL_CALL_START') {
                const toolCallId = data.toolCallId || `tool-${Date.now()}`;
                const toolName = data.toolCallName || 'Tool';
                const toolTitle = chatView.formatToolCallTitle(toolName, {}, '');
                
                streamingToolCalls.set(toolCallId, { name: toolName, args: '', status: 'executing', result: '' });
                
                if (currentTextEl) currentTextEl.classList.remove('streaming');
                currentTextEl = null;
                currentTextContent = '';
                textSegmentIndex++;
                
                const bubble = ensureBubble();
                if (bubble) {
                    bubble.insertAdjacentHTML('beforeend', chatView.renderStreamingToolCall(toolCallId, toolTitle, 'executing'));
                    container.scrollTop = container.scrollHeight;
                }
            } else if (data.type === 'TOOL_CALL_ARGS') {
                const toolCallId = data.toolCallId;
                const argsDelta = data.delta || '';
                if (toolCallId && streamingToolCalls.has(toolCallId)) {
                    const tc = streamingToolCalls.get(toolCallId);
                    tc.args += argsDelta;
                    const argsEl = document.getElementById(`streaming-tool-args-${toolCallId}`);
                    if (argsEl) argsEl.textContent = tc.args;

                    const titleEl = document.querySelector(`[data-streaming-tool-id="${toolCallId}"] .tool-call-name`);
                    if (titleEl) {
                        titleEl.textContent = chatView.formatToolCallTitle(tc.name, {}, tc.args);
                    }
                }
            } else if (data.type === 'TOOL_CALL_END') {
                const toolCallId = data.toolCallId;
                const result = data.result || '';
                const error = data.error;
                if (toolCallId && streamingToolCalls.has(toolCallId)) {
                    const tc = streamingToolCalls.get(toolCallId);
                    tc.status = error ? 'failed' : 'completed';
                    tc.result = result;
                    
                    const statusEl = document.querySelector(`[data-streaming-tool-id="${toolCallId}"] .tool-call-status-icon`);
                    if (statusEl) {
                        statusEl.textContent = error ? '✗' : '✓';
                        statusEl.parentElement.style.color = error ? 'var(--error)' : 'var(--success)';
                    }
                    const resultSection = document.getElementById(`streaming-tool-result-section-${toolCallId}`);
                    const resultEl = document.getElementById(`streaming-tool-result-${toolCallId}`);
                    if (resultSection && resultEl && result) {
                        resultSection.style.display = 'block';
                        resultEl.textContent = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
                    }
                    if (error) {
                        const errorSection = document.getElementById(`streaming-tool-error-section-${toolCallId}`);
                        const errorEl = document.getElementById(`streaming-tool-error-${toolCallId}`);
                        if (errorSection && errorEl) {
                            errorSection.style.display = 'block';
                            errorEl.textContent = error;
                        }
                    }
                    container.scrollTop = container.scrollHeight;
                }
            } else if (data.type === 'TOOL_CALL_RESULT') {
                const toolCallId = data.toolCallId;
                const result = data.result || data.content || '';
                if (toolCallId && streamingToolCalls.has(toolCallId)) {
                    const tc = streamingToolCalls.get(toolCallId);
                    tc.result = result;
                    const resultSection = document.getElementById(`streaming-tool-result-section-${toolCallId}`);
                    const resultEl = document.getElementById(`streaming-tool-result-${toolCallId}`);
                    if (resultSection && resultEl && result) {
                        resultSection.style.display = 'block';
                        resultEl.textContent = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
                    }
                }
            } else if (data.type === 'RUN_FINISHED' || data.type === 'RUN_ERROR') {
                runFinished = true;
                if (currentTextEl) currentTextEl.classList.remove('streaming');
                
                // Show completion indicator
                if (data.type === 'RUN_ERROR') {
                    container.insertAdjacentHTML('beforeend', `
                        <div style="padding: 8px 12px; margin-top: 8px; background: rgba(239,68,68,0.1); border-radius: 6px; font-size: 12px; color: var(--error);">
                            Task failed${data.message ? ': ' + chatView.escapeHtml(data.message) : ''}
                        </div>
                    `);
                } else {
                    container.insertAdjacentHTML('beforeend', `
                        <div style="padding: 8px 12px; margin-top: 8px; background: rgba(16,185,129,0.1); border-radius: 6px; font-size: 12px; color: var(--success);">
                            ✓ Task completed
                        </div>
                    `);
                }
                container.scrollTop = container.scrollHeight;
                
                // Close stream; refresh kanban and sessions only for live (not replay)
                this._closeTaskStream(taskId);
                if (!isReplay) {
                    this.loadTasks(paneId);
                    this.app.chatView.loadSessions(0);
                }
            }
        };

        es.onerror = () => {
            if (runFinished) return;
            // Don't show error for normal close
            if (es.readyState === EventSource.CLOSED) return;
            console.warn(`Task ${taskId} SSE error, will reconnect automatically`);
        };
    }

    /**
     * Load completed task conversation via SSE replay (preserves tool calls in correct order)
     */
    async _loadTaskConversation(paneId, taskId) {
        const container = document.getElementById(`taskConversation-${paneId}`);
        if (!container) return;

        // Use SSE replay for completed tasks too — it preserves tool calls and ordering
        // The stream will end naturally when it hits RUN_FINISHED/RUN_ERROR
        this._streamTaskConversation(paneId, taskId, true);
    }

    /**
     * Close an active SSE stream for a task
     */
    _closeTaskStream(taskId) {
        if (!taskId) return;
        const es = this._activeStreams.get(taskId);
        if (es) {
            es.close();
            this._activeStreams.delete(taskId);
        }
    }

    /**
     * Start auto-polling task board
     */
    _startAutoPolling(paneId) {
        if (this._smartPoll) return; // Already running
        this._smartPoll = new SmartPoll(async () => {
            if (this.app.pageManager?.currentPage !== 'task') return;

            await this.loadTasks(paneId);

            // Refresh sessions list only when there are running tasks
            const tasks = this.tasks[paneId] || [];
            const hasRunning = tasks.some(t => this._normalizeTaskStatus(t.status) === 'in_progress');
            if (hasRunning) {
                this.app.chatView.loadSessions(0);
            }
        }, { intervalMs: this._pollInterval });
        this._smartPoll.start();
    }

    /**
     * Stop auto-polling
     */
    _stopAutoPolling() {
        if (this._smartPoll) {
            this._smartPoll.destroy();
            this._smartPoll = null;
        }
    }

    /**
     * Detect if a task is awaiting owner intervention.
     * A task needs human attention when:
     * - Its metadata contains awaiting_human flag
     * - It has been in in_progress for over 30 minutes with no recent activity
     * - Its status or description contains "awaiting" or "blocked" keywords
     * @param {Object} task - Task object
     * @returns {boolean} True if the task likely needs human intervention
     */
    _detectAwaitingOwner(task) {
        if (!task) return false;

        // Explicit flag in metadata
        if (task.metadata?.awaiting_human) return true;

        // Status already set to awaiting_owner
        if (this._normalizeTaskStatus(task.status) === 'awaiting_owner') return true;

        // Keyword detection in status
        const statusLower = String(task.status || '').toLowerCase();
        if (statusLower.includes('awaiting') || statusLower.includes('blocked')) return true;

        // Stale in-progress check: no update for > 30 minutes
        if (this._normalizeTaskStatus(task.status) === 'in_progress' && task.updated_at) {
            const lastUpdate = new Date(task.updated_at).getTime();
            const thirtyMinutes = 30 * 60 * 1000;
            if (Date.now() - lastUpdate > thirtyMinutes) return true;
        }

        return false;
    }

    async deleteTask(paneId, taskId) {
        try {
            const globalUserFilter = document.getElementById('globalUserFilter');
            await NexusAPI.deleteTask(taskId, { 
                execUser: globalUserFilter?.value || NexusAPI.getDefaultExecUser() 
            });
            this.app.showToast('Task deleted', 'success');
            this.selectedTask[paneId] = null;
            
            const detailPanel = document.getElementById(`taskDetail-${paneId}`);
            if (detailPanel) detailPanel.classList.add('hidden');

            await this.loadTasks(paneId);
        } catch (error) {
            console.error('Failed to delete task:', error);
            this.app.showToast('Failed to delete task', 'error');
        }
    }

    formatTime(timestamp) {
        if (!timestamp) return '';
        const date = new Date(timestamp);
        const now = new Date();
        const diff = now - date;

        if (diff < 60000) return 'Just now';
        if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
        if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
        return date.toLocaleDateString();
    }

    escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ========== Batch Selection Methods ==========

    toggleSelectionMode(paneId) {
        this.selectionMode[paneId] = !this.selectionMode[paneId];

        // Clear selections when exiting selection mode
        if (!this.selectionMode[paneId]) {
            this.selectedTaskIds[paneId] = new Set();
        }

        // Update UI
        const selectionActions = document.getElementById(`selectionActions-${paneId}`);
        const toggleBtn = document.querySelector(`#pane-${paneId}-content [data-action="toggle-selection"]`);

        if (selectionActions) {
            selectionActions.style.display = this.selectionMode[paneId] ? 'flex' : 'none';
        }

        if (toggleBtn) {
            toggleBtn.classList.toggle('active', this.selectionMode[paneId]);
        }

        // Re-render kanban to show/hide checkboxes
        this.renderKanban(paneId);
        this.updateDeleteButtonCount(paneId);
    }

    toggleTaskSelection(paneId, taskId) {
        if (!this.selectedTaskIds[paneId]) {
            this.selectedTaskIds[paneId] = new Set();
        }

        if (this.selectedTaskIds[paneId].has(taskId)) {
            this.selectedTaskIds[paneId].delete(taskId);
        } else {
            this.selectedTaskIds[paneId].add(taskId);
        }

        // Update card visual state
        const card = document.querySelector(`#kanbanBoard-${paneId} .task-card[data-task-id="${taskId}"]`);
        if (card) {
            card.classList.toggle('checked', this.selectedTaskIds[paneId].has(taskId));
            const checkbox = card.querySelector('.task-card-checkbox input');
            if (checkbox) {
                checkbox.checked = this.selectedTaskIds[paneId].has(taskId);
            }
        }

        this.updateDeleteButtonCount(paneId);
    }

    selectAllTasks(paneId) {
        const tasks = this.tasks[paneId] || [];
        this.selectedTaskIds[paneId] = new Set(tasks.map(t => t.id));

        // Update all cards
        document.querySelectorAll(`#kanbanBoard-${paneId} .task-card`).forEach(card => {
            card.classList.add('checked');
            const checkbox = card.querySelector('.task-card-checkbox input');
            if (checkbox) checkbox.checked = true;
        });

        this.updateDeleteButtonCount(paneId);
    }

    deselectAllTasks(paneId) {
        this.selectedTaskIds[paneId] = new Set();

        // Update all cards
        document.querySelectorAll(`#kanbanBoard-${paneId} .task-card`).forEach(card => {
            card.classList.remove('checked');
            const checkbox = card.querySelector('.task-card-checkbox input');
            if (checkbox) checkbox.checked = false;
        });

        this.updateDeleteButtonCount(paneId);
    }

    updateDeleteButtonCount(paneId) {
        const count = this.selectedTaskIds[paneId]?.size || 0;
        const btn = document.getElementById(`deleteSelectedBtn-${paneId}`);
        if (btn) {
            const span = btn.querySelector('span');
            if (span) {
                span.textContent = `Delete (${count})`;
            }
            btn.disabled = count === 0;
        }
    }

    async deleteSelectedTasks(paneId) {
        const taskIds = Array.from(this.selectedTaskIds[paneId] || []);
        if (taskIds.length === 0) {
            this.app.showToast('No tasks selected', 'warning');
            return;
        }

        // Show confirmation modal
        this.app.showDeleteModal('tasks', `${taskIds.length} tasks`, async () => {
            try {
                const globalUserFilter = document.getElementById('globalUserFilter');
                const result = await NexusAPI.bulkDeleteTasks(taskIds, {
                    execUser: globalUserFilter?.value || NexusAPI.getDefaultExecUser()
                });

                const deletedCount = result.result?.count || taskIds.length;
                this.app.showToast(`Deleted ${deletedCount} tasks`, 'success');

                // Clear selections and reload
                this.selectedTaskIds[paneId] = new Set();
                this.updateDeleteButtonCount(paneId);
                await this.loadTasks(paneId);

            } catch (error) {
                console.error('Failed to delete tasks:', error);
                this.app.showToast('Failed to delete tasks', 'error');
            }
        });
    }

    // ==================== Schedule Methods ====================

    toggleSchedulePanel(paneId) {
        const panel = document.getElementById(`schedulePanel-${paneId}`);
        if (!panel) return;
        const isHidden = panel.style.display === 'none';
        panel.style.display = isHidden ? 'block' : 'none';
        if (isHidden) {
            this.loadSchedules(paneId);
        }
    }

    async loadSchedules(paneId) {
        const listEl = document.getElementById(`scheduleList-${paneId}`);
        if (!listEl) return;

        const statusFilter = document.getElementById(`scheduleStatusFilter-${paneId}`)?.value || '';

        try {
            const data = await NexusAPI.getSchedules({ status: statusFilter || undefined, pageSize: 100 });
            const schedules = data.schedules || [];

            if (schedules.length === 0) {
                listEl.innerHTML = `<div class="empty-state" style="padding: 16px;"><p style="color: var(--text-muted); font-size: 13px;">No schedules found</p></div>`;
                return;
            }

            listEl.innerHTML = schedules.map(s => this._renderScheduleCard(s)).join('');

            // Bind schedule card events
            listEl.querySelectorAll('.schedule-card').forEach(card => {
                const scheduleId = card.dataset.scheduleId;

                card.querySelector('[data-action="trigger-schedule"]')?.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.triggerSchedule(scheduleId, paneId);
                });
                card.querySelector('[data-action="pause-schedule"]')?.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.pauseSchedule(scheduleId, paneId);
                });
                card.querySelector('[data-action="resume-schedule"]')?.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.resumeSchedule(scheduleId, paneId);
                });
                card.querySelector('[data-action="cancel-schedule"]')?.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.cancelSchedule(scheduleId, paneId);
                });
                card.querySelector('[data-action="edit-schedule"]')?.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.showEditScheduleModal(scheduleId);
                });
                card.querySelector('[data-action="delete-schedule"]')?.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.deleteSchedule(scheduleId, paneId);
                });
            });
        } catch (error) {
            console.error('Failed to load schedules:', error);
            listEl.innerHTML = `<div class="empty-state" style="padding: 16px;"><p style="color: var(--error); font-size: 13px;">Failed to load schedules</p></div>`;
        }
    }

    _renderScheduleCard(schedule) {
        const statusColors = {
            active: 'var(--status-doing)',
            paused: 'var(--status-todo)',
            cancelled: 'var(--status-cancelled)',
        };
        const statusColor = statusColors[schedule.status] || 'var(--text-muted)';
        const isActive = schedule.status === 'active';
        const isPaused = schedule.status === 'paused';
        const isCancelled = schedule.status === 'cancelled';

        const nextRun = schedule.next_run_at ? new Date(schedule.next_run_at).toLocaleString() : '-';
        const lastRun = schedule.last_run_at ? new Date(schedule.last_run_at).toLocaleString() : 'Never';
        const maxRunsText = schedule.max_runs ? `${schedule.run_count}/${schedule.max_runs}` : `${schedule.run_count}`;

        // Display cron badge or one-time datetime badge
        let triggerBadge;
        if (schedule.run_at) {
            const runAtFormatted = new Date(schedule.run_at).toLocaleString();
            triggerBadge = `<code class="schedule-cron-badge" title="One-time schedule">Once @ ${this._escapeHtml(runAtFormatted)}</code>`;
        } else {
            triggerBadge = `<code class="schedule-cron-badge">${this._escapeHtml(schedule.cron_expression || '-')}</code>`;
        }

        // Kind badge — show "evolution" type with distinctive styling
        const kindBadge = schedule.schedule_kind === 'evolution'
            ? `<span class="schedule-kind-badge evolution" title="Evolution schedule (${schedule.evolution_phase || 'full'})">♻ ${this._escapeHtml(schedule.evolution_phase || 'evolve')}</span>`
            : '';
        // Hide edit/delete buttons for evolution schedules (managed by system)
        const isSystemSchedule = schedule.schedule_kind === 'evolution';

        return `
            <div class="schedule-card" data-schedule-id="${schedule.id}">
                <div class="schedule-card-header">
                    <div class="schedule-card-info">
                        <span class="schedule-status-dot" style="background: ${statusColor};"></span>
                        <span class="schedule-card-name">${this._escapeHtml(schedule.name)}</span>
                        ${kindBadge}
                        ${triggerBadge}
                    </div>
                    <div class="schedule-card-actions">
                        ${isActive ? `
                            <button class="schedule-action-btn" data-action="trigger-schedule" title="Trigger now">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:14px;height:14px;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                            </button>
                            <button class="schedule-action-btn" data-action="pause-schedule" title="Pause">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:14px;height:14px;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                            </button>
                        ` : ''}
                        ${isPaused ? `
                            <button class="schedule-action-btn" data-action="resume-schedule" title="Resume">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:14px;height:14px;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                            </button>
                        ` : ''}
                        ${!isCancelled ? `
                            <button class="schedule-action-btn" data-action="cancel-schedule" title="Cancel">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:14px;height:14px;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                            </button>
                        ` : ''}
                        <button class="schedule-action-btn" data-action="edit-schedule" title="Edit" style="${isSystemSchedule ? 'display:none' : ''}">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:14px;height:14px;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
                        </button>
                        <button class="schedule-action-btn danger" data-action="delete-schedule" title="Delete" style="${isSystemSchedule ? 'display:none' : ''}">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:14px;height:14px;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                        </button>
                    </div>
                </div>
                <div class="schedule-card-meta">
                    <span title="Provider">${this._escapeHtml(schedule.alias || schedule.provider || '-')}</span>
                    <span title="Runs">${maxRunsText} runs</span>
                    <span title="Next run">Next: ${nextRun}</span>
                    <span title="Last run">Last: ${lastRun}</span>
                </div>
                <div class="schedule-card-desc">${this._escapeHtml(schedule.description || '').substring(0, 120)}${(schedule.description || '').length > 120 ? '...' : ''}</div>
            </div>
        `;
    }

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    async triggerSchedule(scheduleId, paneId) {
        try {
            await NexusAPI.triggerSchedule(scheduleId);
            this.app.showToast('Schedule triggered successfully', 'success');
            this.loadSchedules(paneId);
        } catch (error) {
            this.app.showToast(error.message || 'Failed to trigger schedule', 'error');
        }
    }

    async pauseSchedule(scheduleId, paneId) {
        try {
            await NexusAPI.pauseSchedule(scheduleId);
            this.app.showToast('Schedule paused', 'success');
            this.loadSchedules(paneId);
        } catch (error) {
            this.app.showToast(error.message || 'Failed to pause schedule', 'error');
        }
    }

    async resumeSchedule(scheduleId, paneId) {
        try {
            await NexusAPI.resumeSchedule(scheduleId);
            this.app.showToast('Schedule resumed', 'success');
            this.loadSchedules(paneId);
        } catch (error) {
            this.app.showToast(error.message || 'Failed to resume schedule', 'error');
        }
    }

    async cancelSchedule(scheduleId, paneId) {
        if (!confirm('Cancel this schedule permanently? Cancelled schedules cannot be resumed.')) return;
        try {
            await NexusAPI.cancelSchedule(scheduleId);
            this.app.showToast('Schedule cancelled', 'success');
            this.loadSchedules(paneId);
        } catch (error) {
            this.app.showToast(error.message || 'Failed to cancel schedule', 'error');
        }
    }

    async deleteSchedule(scheduleId, paneId) {
        if (!confirm('Delete this schedule? This action cannot be undone.')) return;
        try {
            await NexusAPI.deleteSchedule(scheduleId);
            this.app.showToast('Schedule deleted', 'success');
            this.loadSchedules(paneId);
        } catch (error) {
            this.app.showToast(error.message || 'Failed to delete schedule', 'error');
        }
    }

    async showEditScheduleModal(scheduleId) {
        try {
            const schedule = await NexusAPI.getSchedule(scheduleId);
            const modal = document.getElementById('editScheduleModal');
            if (!modal) return;

            document.getElementById('editScheduleId').value = schedule.id;
            document.getElementById('editScheduleName').value = schedule.name || '';
            document.getElementById('editScheduleCron').value = schedule.cron_expression || '';
            document.getElementById('editScheduleTimezone').value = schedule.timezone || 'UTC';
            document.getElementById('editScheduleDescription').value = schedule.description || '';
            document.getElementById('editScheduleWorkspace').value = schedule.workspace || '';
            document.getElementById('editScheduleMaxRuns').value = schedule.max_runs || '';

            modal.classList.add('open');
        } catch (error) {
            this.app.showToast(error.message || 'Failed to load schedule', 'error');
        }
    }
}

// ============================================================
// Config View - Handles Parameters, MCP, and Skills configuration
// ============================================================
class ConfigView {
    constructor(app) {
        this.app = app;
        this.activeTab = 'parameters';
        this.bindEvents();
    }

    bindEvents() {
        // Config tab switching
        document.querySelectorAll('.config-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                this.switchTab(tab.dataset.configTab);
            });
        });

        // Parameters tab events (includes concurrency)
        this.bindParametersEvents();
        
        // MCP tab events
        this.bindMcpEvents();
        
        // Skills tab events
        this.bindSkillsEvents();
    }

    switchTab(tabName) {
        this.activeTab = tabName;
        
        // Update tab button states
        document.querySelectorAll('.config-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.configTab === tabName);
        });

        // Update tab content visibility
        document.querySelectorAll('.config-tab-content').forEach(content => {
            content.classList.toggle('active', content.dataset.configContent === tabName);
        });
    }

    refresh() {
        this.renderParameters();
        this.renderMcp();
        this.renderSkills();
    }

    // ============================================================
    // Parameters Tab
    // ============================================================
    bindParametersEvents() {
        // Default provider select
        const defaultProviderSelect = document.getElementById('configDefaultProvider');
        if (defaultProviderSelect) {
            defaultProviderSelect.addEventListener('change', (e) => {
                this.app.setDefaultProvider(e.target.value);
                this.app.showToast('Default provider updated', 'success');
                this.app.refreshChatProviders?.();
            });
        }

        // Add alias button
        const addAliasBtn = document.getElementById('addAliasBtn');
        if (addAliasBtn) {
            addAliasBtn.addEventListener('click', () => this.addAlias());
        }

        // Add alias on Enter key
        const newAliasName = document.getElementById('newAliasName');
        if (newAliasName) {
            newAliasName.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') this.addAlias();
            });
        }

        // Global concurrency
        const setGlobalBtn = document.getElementById('setGlobalConcurrencyBtn');
        if (setGlobalBtn) {
            setGlobalBtn.addEventListener('click', () => this.setGlobalConcurrency());
        }
        const globalInput = document.getElementById('globalConcurrencyInput');
        if (globalInput) {
            globalInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') this.setGlobalConcurrency();
            });
        }

        // Provider concurrency
        const setProviderBtn = document.getElementById('setProviderConcurrencyBtn');
        if (setProviderBtn) {
            setProviderBtn.addEventListener('click', () => this.setProviderConcurrency());
        }
    }

    renderParameters() {
        // Update default provider select
        const defaultProviderSelect = document.getElementById('configDefaultProvider');
        if (defaultProviderSelect) {
            const currentDefault = this.app.getDefaultProvider();
            const allProviders = this.app.getAllProviders();
            
            defaultProviderSelect.innerHTML = allProviders.map(p => {
                const label = this.app.isCustomAlias(p) 
                    ? `${p} (${this.app.getBaseProvider(p)})` 
                    : p;
                return `<option value="${p}" ${p === currentDefault ? 'selected' : ''}>${label}</option>`;
            }).join('');
        }

        // Update base provider select for new alias
        const newAliasBase = document.getElementById('newAliasBase');
        if (newAliasBase) {
            newAliasBase.innerHTML = this.app.getDefaultProviders()
                .map(p => `<option value="${p}">${p}</option>`)
                .join('');
        }

        // Render alias list
        this.renderAliasList();

        // Render per-provider/alias default model settings
        this.renderProviderModels();

        // Update concurrency provider/alias dropdown
        const concurrencySelect = document.getElementById('providerConcurrencySelect');
        if (concurrencySelect) {
            const allProviders = this.app.getAllProviders();
            concurrencySelect.innerHTML = allProviders.map(p => {
                const label = this.app.isCustomAlias(p)
                    ? `${p} (${this.app.getBaseProvider(p)})`
                    : p;
                return `<option value="${p}">${label}</option>`;
            }).join('');
        }

        // Render concurrency data
        this.renderConcurrency();
    }

    renderProviderModels() {
        const container = document.getElementById('providerModelsContainer');
        if (!container) return;

        const allProviders = this.app.getAllProviders();
        container.innerHTML = allProviders.map(name => {
            const currentModel = this.app.getProviderDefaultModel(name);
            const isAlias = this.app.isCustomAlias(name);
            const label = isAlias ? `${name} <span class="alias-item-base">${this.app.getBaseProvider(name)}</span>` : name;
            return `
                <div class="provider-model-row" data-provider="${name}" style="display:flex; gap:8px; align-items:center; margin-bottom:8px;">
                    <span style="min-width:140px; font-weight:500; font-size:13px;">${label}</span>
                    <input type="text" class="form-input provider-model-input" data-provider="${name}"
                           value="${currentModel}" placeholder="Use provider default"
                           style="flex:1; max-width:300px;">
                    <button class="action-btn small provider-model-save" data-provider="${name}" style="padding:4px 10px; font-size:12px;">Save</button>
                </div>
            `;
        }).join('');

        // Bind save buttons and Enter key
        container.querySelectorAll('.provider-model-save').forEach(btn => {
            btn.addEventListener('click', () => {
                const prov = btn.dataset.provider;
                const input = container.querySelector(`.provider-model-input[data-provider="${prov}"]`);
                if (input) {
                    this.app.setProviderDefaultModel(prov, input.value.trim());
                    this.app.showToast(`Default model for ${prov} updated`, 'success');
                }
            });
        });
        container.querySelectorAll('.provider-model-input').forEach(input => {
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    const prov = input.dataset.provider;
                    this.app.setProviderDefaultModel(prov, input.value.trim());
                    this.app.showToast(`Default model for ${prov} updated`, 'success');
                }
            });
        });
    }

    renderAliasList() {
        const container = document.getElementById('aliasListContainer');
        if (!container) return;

        const aliases = this.app.customProviders;
        
        if (aliases.length === 0) {
            container.innerHTML = '<div class="alias-empty">No custom aliases configured</div>';
            return;
        }

        container.innerHTML = aliases.map(alias => `
            <div class="alias-item" data-alias="${alias.name}">
                <div class="alias-item-info">
                    <span class="alias-item-name">${alias.name}</span>
                    <span class="alias-item-base">${alias.baseProvider}</span>
                    ${alias.configPath ? `<span class="alias-item-path" title="${alias.configPath}">${alias.configPath}</span>` : ''}
                </div>
                <button class="alias-item-delete" title="Delete alias">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                    </svg>
                </button>
            </div>
        `).join('');

        // Bind delete buttons
        container.querySelectorAll('.alias-item-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const item = e.target.closest('.alias-item');
                const aliasName = item?.dataset.alias;
                if (aliasName) {
                    this.deleteAlias(aliasName);
                }
            });
        });
    }

    addAlias() {
        const nameInput = document.getElementById('newAliasName');
        const baseSelect = document.getElementById('newAliasBase');
        const configPathInput = document.getElementById('newAliasConfigPath');
        
        if (!nameInput || !baseSelect) return;

        const name = nameInput.value.trim();
        const base = baseSelect.value;
        const configPath = configPathInput?.value.trim() || '';

        if (!name) {
            this.app.showToast('Please enter an alias name', 'error');
            return;
        }

        if (this.app.addCustomProvider(name, base, configPath)) {
            this.app.showToast(`Alias "${name}" added`, 'success');
            nameInput.value = '';
            if (configPathInput) configPathInput.value = '';
            this.renderParameters();
            this.renderSkills();
            this.app.refreshChatProviders?.();
        } else {
            this.app.showToast('Alias already exists or is invalid', 'error');
        }
    }

    deleteAlias(name) {
        if (this.app.removeCustomProvider(name)) {
            this.app.showToast(`Alias "${name}" removed`, 'success');
            this.renderParameters();
            this.renderSkills();
            this.app.refreshChatProviders?.();
        } else {
            this.app.showToast('Cannot remove this alias', 'error');
        }
    }

    // ============================================================
    // MCP Tab
    // ============================================================
    bindMcpEvents() {
        // Add global MCP button
        const addGlobalMcpBtn = document.getElementById('addGlobalMcpBtn');
        if (addGlobalMcpBtn) {
            addGlobalMcpBtn.addEventListener('click', () => this.addGlobalMcp());
        }
    }

    renderMcp() {
        const mcpConfig = this.app.loadMcpConfig();
        
        // Render global MCP list
        this.renderMcpList('globalMcpList', mcpConfig.global, null);
        
        // Render provider panels
        this.renderProviderMcpPanels(mcpConfig.providers);
    }

    renderMcpList(containerId, mcpServers, provider) {
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!mcpServers || mcpServers.length === 0) {
            container.innerHTML = '<div class="mcp-empty">No MCP servers configured</div>';
            return;
        }

        container.innerHTML = mcpServers.map((mcp, index) => `
            <div class="mcp-item" data-index="${index}" data-provider="${provider || 'global'}">
                <div class="mcp-item-info">
                    <div class="mcp-item-name">${mcp.name}</div>
                    <div class="mcp-item-command">${mcp.command} ${(mcp.args || []).join(' ')}</div>
                </div>
                <button class="mcp-item-delete" title="Delete MCP server">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                    </svg>
                </button>
            </div>
        `).join('');

        // Bind delete buttons
        container.querySelectorAll('.mcp-item-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const item = e.target.closest('.mcp-item');
                const index = parseInt(item?.dataset.index);
                const prov = item?.dataset.provider;
                if (!isNaN(index)) {
                    this.deleteMcp(prov === 'global' ? null : prov, index);
                }
            });
        });
    }

    renderProviderMcpPanels(providersMcp) {
        const container = document.getElementById('providerMcpPanels');
        if (!container) return;

        const providers = this.app.getDefaultProviders();
        
        container.innerHTML = providers.map(provider => {
            const mcpList = providersMcp[provider] || [];
            return `
                <div class="provider-panel" data-provider="${provider}">
                    <div class="provider-panel-header">
                        <div class="provider-panel-title">
                            ${provider}
                            <span class="provider-panel-count">${mcpList.length}</span>
                        </div>
                        <svg class="provider-panel-toggle" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </div>
                    <div class="provider-panel-body">
                        <div class="mcp-form">
                            <input type="text" class="form-input provider-mcp-name" placeholder="Server name">
                            <input type="text" class="form-input provider-mcp-command" placeholder="Command">
                            <input type="text" class="form-input provider-mcp-args" placeholder="Args (comma-separated)">
                            <button class="action-btn primary provider-mcp-add">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:16px;height:16px;">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                                </svg>
                                Add
                            </button>
                        </div>
                        <div class="mcp-list" id="providerMcpList-${provider}">
                            ${this.renderProviderMcpItems(mcpList, provider)}
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        // Bind panel toggle
        container.querySelectorAll('.provider-panel-header').forEach(header => {
            header.addEventListener('click', () => {
                header.closest('.provider-panel').classList.toggle('expanded');
            });
        });

        // Bind add buttons
        container.querySelectorAll('.provider-mcp-add').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const panel = e.target.closest('.provider-panel');
                const provider = panel?.dataset.provider;
                if (provider) {
                    this.addProviderMcp(provider, panel);
                }
            });
        });

        // Bind delete buttons
        container.querySelectorAll('.mcp-item-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const item = e.target.closest('.mcp-item');
                const index = parseInt(item?.dataset.index);
                const prov = item?.dataset.provider;
                if (!isNaN(index) && prov) {
                    this.deleteMcp(prov, index);
                }
            });
        });
    }

    renderProviderMcpItems(mcpList, provider) {
        if (!mcpList || mcpList.length === 0) {
            return '<div class="mcp-empty">No MCP servers for this provider</div>';
        }

        return mcpList.map((mcp, index) => `
            <div class="mcp-item" data-index="${index}" data-provider="${provider}">
                <div class="mcp-item-info">
                    <div class="mcp-item-name">${mcp.name}</div>
                    <div class="mcp-item-command">${mcp.command} ${(mcp.args || []).join(' ')}</div>
                </div>
                <button class="mcp-item-delete" title="Delete MCP server">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                    </svg>
                </button>
            </div>
        `).join('');
    }

    addGlobalMcp() {
        const nameInput = document.getElementById('globalMcpName');
        const commandInput = document.getElementById('globalMcpCommand');
        const argsInput = document.getElementById('globalMcpArgs');

        if (!nameInput || !commandInput) return;

        const name = nameInput.value.trim();
        const command = commandInput.value.trim();
        const args = argsInput?.value.trim().split(',').map(s => s.trim()).filter(Boolean) || [];

        if (!name || !command) {
            this.app.showToast('Please enter server name and command', 'error');
            return;
        }

        const config = this.app.loadMcpConfig();
        config.global.push({ name, command, args });
        this.app.saveMcpConfig(config);

        nameInput.value = '';
        commandInput.value = '';
        if (argsInput) argsInput.value = '';

        this.app.showToast(`MCP server "${name}" added`, 'success');
        this.renderMcp();
    }

    addProviderMcp(provider, panel) {
        const nameInput = panel.querySelector('.provider-mcp-name');
        const commandInput = panel.querySelector('.provider-mcp-command');
        const argsInput = panel.querySelector('.provider-mcp-args');

        if (!nameInput || !commandInput) return;

        const name = nameInput.value.trim();
        const command = commandInput.value.trim();
        const args = argsInput?.value.trim().split(',').map(s => s.trim()).filter(Boolean) || [];

        if (!name || !command) {
            this.app.showToast('Please enter server name and command', 'error');
            return;
        }

        const config = this.app.loadMcpConfig();
        if (!config.providers[provider]) {
            config.providers[provider] = [];
        }
        config.providers[provider].push({ name, command, args });
        this.app.saveMcpConfig(config);

        nameInput.value = '';
        commandInput.value = '';
        if (argsInput) argsInput.value = '';

        this.app.showToast(`MCP server "${name}" added to ${provider}`, 'success');
        this.renderMcp();
    }

    deleteMcp(provider, index) {
        const config = this.app.loadMcpConfig();
        
        if (provider === null) {
            // Global
            if (config.global[index]) {
                const name = config.global[index].name;
                config.global.splice(index, 1);
                this.app.saveMcpConfig(config);
                this.app.showToast(`MCP server "${name}" removed`, 'success');
                this.renderMcp();
            }
        } else {
            // Provider specific
            if (config.providers[provider] && config.providers[provider][index]) {
                const name = config.providers[provider][index].name;
                config.providers[provider].splice(index, 1);
                this.app.saveMcpConfig(config);
                this.app.showToast(`MCP server "${name}" removed from ${provider}`, 'success');
                this.renderMcp();
            }
        }
    }

    // ============================================================
    // Skills Tab (backend API driven)
    // ============================================================
    bindSkillsEvents() {
        // Events are bound dynamically after rendering provider panels
    }

    async renderSkills() {
        const container = document.getElementById('providerSkillsPanels');
        if (!container) return;

        container.innerHTML = '<div class="skills-loading">Loading skills...</div>';

        try {
            const execUser = document.getElementById('globalUserFilter')?.value || NexusAPI.getDefaultExecUser();
            const customPaths = this.app.getAliasSkillsPaths();
            const data = await NexusAPI.getSkills({ execUser, customPaths: Object.keys(customPaths).length ? customPaths : undefined });
            this._skillsData = data.providers || {};
            this.renderProviderSkillsPanels(this._skillsData);
        } catch (error) {
            console.error('Failed to load skills:', error);
            container.innerHTML = '<div class="skills-empty">Failed to load skills. Check server connection.</div>';
        }
    }

    renderProviderSkillsPanels(providersSkills) {
        const container = document.getElementById('providerSkillsPanels');
        if (!container) return;

        const defaultProviders = ['claude', 'codebuddy', 'codex', 'gemini'];
        // Include custom aliases
        const aliasNames = this.app.getCustomProviderNames();
        const allProviders = [...defaultProviders, ...aliasNames.filter(n => !defaultProviders.includes(n))];
        // Also include any extra providers from the response
        for (const key of Object.keys(providersSkills)) {
            if (!allProviders.includes(key)) allProviders.push(key);
        }

        // Default provider config dirs (for display)
        const _DEFAULT_CONFIG_DIRS = {
            claude: '~/.claude', codebuddy: '~/.codebuddy', codex: '~/.codex', gemini: '~/.gemini'
        };

        container.innerHTML = allProviders.map(provider => {
            const skills = providersSkills[provider] || [];
            const isAlias = this.app.isCustomAlias(provider);
            const baseInfo = isAlias ? ` <span class="alias-item-base">${this.app.getBaseProvider(provider)}</span>` : '';
            // Show config path for both default providers and aliases
            let configPath;
            if (isAlias) {
                configPath = this.app.getAliasConfigPath(provider) || '';
            } else {
                configPath = _DEFAULT_CONFIG_DIRS[provider] || '';
            }
            const pathInfo = configPath ? ` <span class="alias-item-path" title="${configPath}">${configPath}</span>` : '';
            return `
                <div class="provider-panel expanded" data-provider="${provider}" data-config-path="${configPath || ''}">
                    <div class="provider-panel-header">
                        <div class="provider-panel-title">
                            ${provider}${baseInfo}${pathInfo}
                            <span class="provider-panel-count">${skills.length}</span>
                        </div>
                        <svg class="provider-panel-toggle" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </div>
                    <div class="provider-panel-body">
                        <!-- Create Skill Form -->
                        <div class="skill-create-form">
                            <div class="skill-create-row">
                                <input type="text" class="form-input skill-new-name" placeholder="Skill name">
                                <input type="text" class="form-input skill-new-desc" placeholder="Description (optional)">
                                <button class="action-btn primary skill-create-btn" title="Create new skill">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:16px;height:16px;">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                                    </svg>
                                    Create
                                </button>
                            </div>
                            <textarea class="form-input skill-new-content" placeholder="SKILL.md content (markdown, optional)" rows="3" style="display:none;"></textarea>
                            <button class="skill-toggle-content-btn" title="Toggle content editor">+ Add content</button>
                        </div>
                        <!-- Skills List -->
                        <div class="skills-list" id="providerSkillsList-${provider}">
                            ${this._renderSkillCards(skills, provider)}
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        // Bind panel toggle
        container.querySelectorAll('.provider-panel-header').forEach(header => {
            header.addEventListener('click', () => {
                header.closest('.provider-panel').classList.toggle('expanded');
            });
        });

        // Bind create skill buttons
        container.querySelectorAll('.skill-create-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const panel = e.target.closest('.provider-panel');
                const provider = panel?.dataset.provider;
                if (provider) this._createSkill(provider, panel);
            });
        });

        // Bind "Enter" on name input
        container.querySelectorAll('.skill-new-name').forEach(input => {
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    const panel = e.target.closest('.provider-panel');
                    const provider = panel?.dataset.provider;
                    if (provider) this._createSkill(provider, panel);
                }
            });
        });

        // Bind toggle content button
        container.querySelectorAll('.skill-toggle-content-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const form = e.target.closest('.skill-create-form');
                const textarea = form?.querySelector('.skill-new-content');
                if (textarea) {
                    const isHidden = textarea.style.display === 'none';
                    textarea.style.display = isHidden ? 'block' : 'none';
                    e.target.textContent = isHidden ? '- Hide content' : '+ Add content';
                }
            });
        });

        // Bind delete skill buttons
        container.querySelectorAll('.skill-card-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const card = e.target.closest('.skill-card');
                const provider = card?.dataset.provider;
                const skillName = card?.dataset.skillName;
                if (provider && skillName) this._deleteSkill(provider, skillName);
            });
        });
    }

    _renderSkillCards(skills, provider) {
        if (!skills || skills.length === 0) {
            return '<div class="skills-empty">No skills discovered for this provider</div>';
        }

        return skills.map(skill => `
            <div class="skill-card" data-provider="${provider}" data-skill-name="${skill.name}">
                <div class="skill-card-info">
                    <div class="skill-card-name">${skill.name}</div>
                    ${skill.description ? `<div class="skill-card-desc">${skill.description.length > 120 ? skill.description.slice(0, 120) + '...' : skill.description}</div>` : ''}
                    <div class="skill-card-meta">
                        ${skill.version ? `<span class="skill-card-version">v${skill.version}</span>` : ''}
                        ${skill.path ? `<span class="skill-card-path" title="${skill.path}">${skill.path.length > 40 ? '...' + skill.path.slice(-37) : skill.path}</span>` : ''}
                    </div>
                </div>
                <button class="skill-card-delete" title="Delete skill">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                    </svg>
                </button>
            </div>
        `).join('');
    }

    async _createSkill(provider, panel) {
        const nameInput = panel.querySelector('.skill-new-name');
        const descInput = panel.querySelector('.skill-new-desc');
        const contentTextarea = panel.querySelector('.skill-new-content');

        const skillName = nameInput?.value.trim();
        if (!skillName) {
            this.app.showToast('Please enter a skill name', 'error');
            return;
        }

        const description = descInput?.value.trim() || '';
        const content = contentTextarea?.value.trim() || '';
        const configPath = panel.dataset.configPath || '';

        const payload = {
            provider,
            skill_name: skillName,
            description,
            content: content || `# ${skillName}\n`,
        };
        // If alias has custom config path, pass skills_path
        if (configPath) {
            payload.skills_path = configPath.endsWith('/skills') ? configPath : configPath + '/skills';
        }

        try {
            await NexusAPI.createSkill(payload);
            this.app.showToast(`Skill "${skillName}" created for ${provider}`, 'success');
            if (nameInput) nameInput.value = '';
            if (descInput) descInput.value = '';
            if (contentTextarea) contentTextarea.value = '';
            await this.renderSkills();
        } catch (error) {
            this.app.showToast(`Failed to create skill: ${error.message}`, 'error');
        }
    }

    async _deleteSkill(provider, skillName) {
        if (!confirm(`Delete skill "${skillName}" from ${provider}? This will remove the skill directory from the filesystem.`)) {
            return;
        }

        try {
            const execUser = document.getElementById('globalUserFilter')?.value || NexusAPI.getDefaultExecUser();
            const configPath = this.app.getAliasConfigPath(provider);
            const opts = { execUser };
            if (configPath) {
                opts.skillsPath = configPath.endsWith('/skills') ? configPath : configPath + '/skills';
            }
            await NexusAPI.deleteSkill(provider, skillName, opts);
            this.app.showToast(`Skill "${skillName}" deleted from ${provider}`, 'success');
            await this.renderSkills();
        } catch (error) {
            this.app.showToast(`Failed to delete skill: ${error.message}`, 'error');
        }
    }

    // ============================================================
    // Concurrency Tab
    // ============================================================
    async renderConcurrency() {
        try {
            const resp = await fetch('/api/nexus/concurrency');
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();

            // Global
            const globalInput = document.getElementById('globalConcurrencyInput');
            const globalDisplay = document.getElementById('globalConcurrencyDisplay');
            if (globalInput) {
                globalInput.value = data.global_max_concurrency || 0;
            }
            if (globalDisplay) {
                globalDisplay.textContent = data.global_max_concurrency
                    ? `Current: ${data.global_max_concurrency}`
                    : 'Current: unlimited';
            }

            // Provider list
            this.renderProviderConcurrencyList(data.provider_concurrency || {});
        } catch (e) {
            console.error('Failed to load concurrency config:', e);
        }
    }

    renderProviderConcurrencyList(providerMap) {
        const container = document.getElementById('providerConcurrencyList');
        if (!container) return;

        const entries = Object.entries(providerMap).sort((a, b) => a[0].localeCompare(b[0]));
        if (entries.length === 0) {
            container.innerHTML = '<div class="mcp-empty">No provider concurrency limits configured</div>';
            return;
        }

        container.innerHTML = entries.map(([name, limit]) => `
            <div class="mcp-item" data-provider-name="${name}">
                <div class="mcp-item-info">
                    <div class="mcp-item-name">${name}</div>
                    <div class="mcp-item-command">Max: ${limit}</div>
                </div>
                <button class="mcp-item-delete concurrency-remove-btn" title="Remove limit" data-name="${name}">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                    </svg>
                </button>
            </div>
        `).join('');

        container.querySelectorAll('.concurrency-remove-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const name = e.target.closest('.concurrency-remove-btn')?.dataset.name;
                if (name) {
                    await this.removeProviderConcurrency(name);
                }
            });
        });
    }

    async setGlobalConcurrency() {
        const input = document.getElementById('globalConcurrencyInput');
        if (!input) return;
        const limit = parseInt(input.value) || 0;

        try {
            const resp = await fetch('/api/nexus/concurrency/global', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ limit }),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${resp.status}`);
            }
            this.app.showToast(`Global concurrency set to ${limit || 'unlimited'}`, 'success');
            this.renderConcurrency();
        } catch (e) {
            this.app.showToast(`Failed: ${e.message}`, 'error');
        }
    }

    async setProviderConcurrency() {
        const nameSelect = document.getElementById('providerConcurrencySelect');
        const limitInput = document.getElementById('providerConcurrencyLimit');
        if (!nameSelect || !limitInput) return;

        const name = nameSelect.value;
        const limit = parseInt(limitInput.value) || 0;

        if (!name) {
            this.app.showToast('Please select a provider or alias', 'error');
            return;
        }

        try {
            const resp = await fetch('/api/nexus/concurrency/provider', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, limit }),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${resp.status}`);
            }
            limitInput.value = '';
            this.app.showToast(`Concurrency for "${name}" set to ${limit || 'unlimited'}`, 'success');
            this.renderConcurrency();
        } catch (e) {
            this.app.showToast(`Failed: ${e.message}`, 'error');
        }
    }

    async removeProviderConcurrency(name) {
        try {
            const resp = await fetch(`/api/nexus/concurrency/provider/${encodeURIComponent(name)}`, {
                method: 'DELETE',
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${resp.status}`);
            }
            this.app.showToast(`Concurrency limit for "${name}" removed`, 'success');
            this.renderConcurrency();
        } catch (e) {
            this.app.showToast(`Failed: ${e.message}`, 'error');
        }
    }
}

// ============================================================
// Admin View
// ============================================================
class AdminView {
    constructor(app) {
        this.app = app;
        this.activeTab = 'overview';
        this.container = document.getElementById('adminContent');
        this.bindEvents();
    }

    bindEvents() {
        document.querySelectorAll('.admin-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                this.switchTab(tab.dataset.adminTab);
            });
        });
    }

    switchTab(tabName) {
        this.activeTab = tabName;
        document.querySelectorAll('.admin-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.adminTab === tabName);
        });
        this.renderActiveTab();
    }

    refresh() { this.renderActiveTab(); }

    renderActiveTab() {
        if (!this.container) return;
        const renderers = {
            overview: () => this.renderOverview(),
            security: () => this.renderSecurity(),
            runtimes: () => this.renderRuntimes(),
            search: () => this.renderSearch(),
            audit: () => this.renderAudit(),
            cleanup: () => this.renderCleanup(),
            tools: () => this.renderTools(),
            // New tabs — merged from panels
            agents: () => this.renderAgentsTab(),
            activity: () => this.renderActivityTab(),
            memory: () => this.renderMemoryTab(),
            integrations: () => this.renderIntegrationsTab(),
            admin: () => this.renderAdminTab(),
            // Extended tabs — panel content appended
            scheduling: () => this.renderSchedulingTab(),
        };
        (renderers[this.activeTab] || renderers.overview)();
    }

    _esc(str) { return String(str||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
    _showLoading() { this.container.innerHTML = '<div class="admin-loading">Loading...</div>'; }
    _showError(msg) { this.container.innerHTML = `<div class="admin-error">${this._esc(msg)}</div>`; }
    _fmtBytes(b) { if(!b)return'0 B';const u=['B','KB','MB','GB','TB'];const i=Math.floor(Math.log(b)/Math.log(1024));return(b/Math.pow(1024,i)).toFixed(1)+' '+u[i]; }

    // ── Overview Tab ──
    async renderOverview() {
        this._showLoading();
        try {
            const [diag, workload] = await Promise.all([
                NexusAPI.getDiagnostics().catch(() => null),
                NexusAPI.getWorkload().catch(() => null),
            ]);
            if (!diag) { this._showError('Failed to load diagnostics'); return; }
            const sys = diag.system || {}, redis = diag.redis || {}, tasks = diag.tasks || {}, sessions = diag.sessions || {}, wl = workload || {};
            const sig = (wl.recommendation?.action||'normal').toLowerCase().replace(/[^a-z-]/g,'');
            this.container.innerHTML = `
                <div class="admin-section">
                    <h3 class="admin-section-title">System Overview</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-header"><span class="admin-card-title">System Info</span></div><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Python</span><span class="admin-metric-value">${this._esc(sys.python_version||'N/A')}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Platform</span><span class="admin-metric-value">${this._esc(sys.platform||'N/A')}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Memory</span><span class="admin-metric-value">${this._fmtBytes(sys.memory_usage_bytes)}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Uptime</span><span class="admin-metric-value">${sys.uptime_seconds?Math.floor(sys.uptime_seconds/3600)+'h':'N/A'}</span></div>
                        </div></div>
                        <div class="admin-card"><div class="admin-card-header"><span class="admin-card-title">Redis</span><span class="admin-badge ${redis.connected?'pass':'fail'}">${redis.connected?'Connected':'Down'}</span></div><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Version</span><span class="admin-metric-value">${this._esc(redis.version||'N/A')}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Memory</span><span class="admin-metric-value">${this._esc(redis.memory_human||'N/A')}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Keys</span><span class="admin-metric-value">${redis.total_keys??'N/A'}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Clients</span><span class="admin-metric-value">${redis.connected_clients??'N/A'}</span></div>
                        </div></div>
                        <div class="admin-card"><div class="admin-card-header"><span class="admin-card-title">Tasks</span></div><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Total</span><span class="admin-metric-value large">${tasks.total??0}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Todo</span><span class="admin-metric-value">${tasks.by_status?.todo??0}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Doing</span><span class="admin-metric-value">${tasks.by_status?.doing??0}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Done</span><span class="admin-metric-value">${tasks.by_status?.done??0}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Failed</span><span class="admin-metric-value">${tasks.by_status?.failed??0}</span></div>
                        </div></div>
                        <div class="admin-card"><div class="admin-card-header"><span class="admin-card-title">Sessions</span></div><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Total</span><span class="admin-metric-value large">${sessions.total??0}</span></div>
                        </div></div>
                        <div class="admin-card"><div class="admin-card-header"><span class="admin-card-title">Workload</span><span class="admin-badge ${sig}">${this._esc(wl.recommendation?.action||'N/A')}</span></div><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Active Tasks</span><span class="admin-metric-value">${wl.active_tasks??'N/A'}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Queue Depth</span><span class="admin-metric-value">${wl.queue_depth??'N/A'}</span></div>
                        </div></div>
                    </div>
                    <div class="admin-actions">
                        <button class="action-btn primary" id="adminRefreshBtn">Refresh</button>
                        <button class="action-btn" id="adminExportTasksBtn">Export Tasks</button>
                    </div>
                </div>`;
            document.getElementById('adminRefreshBtn')?.addEventListener('click', () => this.renderOverview());
            document.getElementById('adminExportTasksBtn')?.addEventListener('click', async () => {
                try { const d=await NexusAPI.exportData('tasks','json');const b=new Blob([JSON.stringify(d,null,2)],{type:'application/json'});const u=URL.createObjectURL(b);const a=document.createElement('a');a.href=u;a.download='tasks_export.json';a.click();URL.revokeObjectURL(u); } catch(e){alert('Export failed: '+e.message);}
            });
        } catch(e) { this._showError('Failed to load overview: '+e.message); }
    }

    // ── Security Tab (extended with panel content) ──
    async renderSecurity() {
        this._showLoading();
        try {
            const [secData, auditData] = await Promise.all([
                NexusAPI.getSecurityScan().catch(() => null),
                NexusAPI.getAuditLog({ limit: 50 }).catch(() => ({ entries: [] })),
            ]);
            if (!secData) { this._showError('Failed to load security scan'); return; }
            const grade = (secData.overall||'unknown').toLowerCase().replace(/[^a-z-]/g,'');
            const ico = (s) => s==='pass'||s===true?'&#x2705;':s==='warn'||s==='warning'?'&#x26A0;&#xFE0F;':'&#x274C;';
            let cats = '';
            for (const [n, cd] of Object.entries(secData.categories||{})) {
                const cks = (cd.checks||[]).map(c=>`<div class="security-check"><span class="security-check-icon">${ico(c.status)}</span><div class="security-check-info"><div class="security-check-name">${this._esc(c.name||c.check||'')}</div>${c.detail?`<div class="security-check-detail">${this._esc(c.detail)}</div>`:''}${c.fix?`<div class="security-check-fix">Fix: ${this._esc(c.fix)}</div>`:''}</div></div>`).join('');
                cats += `<div class="admin-card"><div class="admin-card-header"><span class="admin-card-title">${this._esc(n)}</span><span class="admin-badge ${(cd.status||'').toLowerCase()}">${cd.score??''}/100</span></div><div class="security-checks">${cks||'<div class="admin-metric-label">No checks</div>'}</div></div>`;
            }

            // Security Audit (from security-audit panel)
            const secEntries = auditData.entries || auditData.logs || [];
            const highRisk = secEntries.filter(e => e.level === 'error' || e.severity === 'high').length;
            let secAuditHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Security Audit</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Entries</span><span class="admin-metric-value">${secEntries.length}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">High Risk</span><span class="admin-metric-value" style="color:var(--error)">${highRisk}</span></div>
                        </div></div>
                    </div>
                    ${secEntries.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No audit entries</div>' :
                      secEntries.slice(0, 20).map(e => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(e.action || e.event_type || 'Audit Event')}</div>
                                <div class="panel-list-item-sub">${e.timestamp ? new Date(e.timestamp).toLocaleString() : ''} ${e.username ? '&middot; ' + this._esc(e.username) : ''}</div>
                            </div>
                            <span class="panel-badge ${e.level === 'error' || e.severity === 'high' ? 'badge-error' : e.level === 'warning' ? 'badge-warn' : 'badge-ok'}">${e.level || e.severity || 'info'}</span>
                        </div>
                    `).join('')}
                </div>`;

            // Trust Scores (from trust-score panel)
            const trustScores = secData.trust_scores || secData.scores || [];
            let trustHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Trust Scores</h3>
                    ${trustScores.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No trust scores available</div>' :
                      trustScores.map(s => {
                        const score = s.score ?? s.trust_score ?? 0;
                        const level = score >= 80 ? 'high' : score >= 50 ? 'medium' : 'low';
                        return `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(s.agent_id || s.name || 'Agent')}</div>
                                <div class="panel-list-item-sub">${this._esc(s.reason || level + ' trust level')}</div>
                            </div>
                            <div class="panel-trust-score score-${level}">
                                <span class="score-value">${score}</span><span class="score-max">/100</span>
                            </div>
                        </div>`;
                    }).join('')}
                </div>`;

            // Hook Profiles (from hook-profiles panel)
            const hooks = secData.hook_profiles || secData.hooks || [];
            let hooksHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Hook Profiles</h3>
                    ${hooks.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No hook profiles configured</div>' :
                      hooks.map(h => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(h.name || h.id || 'Hook')}</div>
                                <div class="panel-list-item-sub">${this._esc(h.type || h.event || '')} &middot; ${this._esc(h.action || 'log')}</div>
                            </div>
                            <span class="panel-badge ${h.enabled !== false ? 'badge-ok' : 'badge-muted'}">${h.enabled !== false ? 'Active' : 'Disabled'}</span>
                        </div>
                    `).join('')}
                </div>`;

            // Permissions (from permission panel)
            const permissions = secData.permissions || secData.acl || [];
            let permHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Permissions</h3>
                    ${permissions.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No permission entries</div>' :
                      permissions.map(p => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(p.subject || p.role || 'Role')}</div>
                                <div class="panel-list-item-sub">${this._esc(p.resource || p.scope || '')}: ${this._esc(p.action || p.permission || 'read')}</div>
                            </div>
                            <span class="panel-badge ${p.granted !== false ? 'badge-ok' : 'badge-error'}">${p.granted !== false ? 'Granted' : 'Denied'}</span>
                        </div>
                    `).join('')}
                </div>`;

            this.container.innerHTML = `<div class="admin-section"><div style="display:flex;align-items:center;gap:var(--spacing-md);margin-bottom:var(--spacing-lg);"><h3 class="admin-section-title" style="margin-bottom:0">Security Scan</h3><span class="admin-badge ${grade}" style="font-size:var(--text-sm);padding:4px 16px;">${secData.score}/100 — ${this._esc(secData.overall||'Unknown')}</span></div><div class="admin-cards">${cats}</div><div class="admin-actions"><button class="action-btn primary" id="adminRescanBtn">Re-scan</button></div></div>` + secAuditHtml + trustHtml + hooksHtml + permHtml;
            document.getElementById('adminRescanBtn')?.addEventListener('click', () => this.renderSecurity());
        } catch(e) { this._showError('Failed to load security scan: '+e.message); }
    }

    // ── Runtimes Tab ──
    async renderRuntimes() {
        this._showLoading();
        try {
            const data = await NexusAPI.getAgentRuntimes();
            const runtimes = data.runtimes || [];
            let cards = runtimes.map(r => `
                <div class="admin-card">
                    <div class="admin-card-header">
                        <span class="admin-card-title">${this._esc(r.name)}</span>
                        <span class="admin-badge ${r.installed ? 'pass' : 'fail'}">${r.installed ? 'Installed' : 'Not Found'}</span>
                    </div>
                    <div class="admin-card-body">
                        <div class="admin-metric"><span class="admin-metric-label">ID</span><span class="admin-metric-value">${this._esc(r.id)}</span></div>
                        <div class="admin-metric"><span class="admin-metric-label">Version</span><span class="admin-metric-value">${this._esc(r.version || 'N/A')}</span></div>
                        <div class="admin-metric"><span class="admin-metric-label">Binary</span><span class="admin-metric-value" style="font-size:var(--text-xs)">${this._esc(r.binary_path || 'N/A')}</span></div>
                        <div class="admin-metric"><span class="admin-metric-label">Auth</span><span class="admin-metric-value">${r.auth_required ? (r.authenticated ? '&#x2705; Authenticated' : '&#x274C; Not authenticated') : '&#x2796; Not required'}</span></div>
                        ${r.auth_hint && !r.authenticated ? `<div style="font-size:var(--text-xs);color:var(--primary-400);margin-top:4px;">${this._esc(r.auth_hint)}</div>` : ''}
                    </div>
                </div>
            `).join('');
            this.container.innerHTML = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Agent Runtimes</h3>
                    <p class="admin-section-desc">${data.installed_count} of ${data.total} runtimes installed</p>
                    <div class="admin-cards">${cards}</div>
                    <div class="admin-actions"><button class="action-btn primary" id="adminRuntimeRefreshBtn">Re-detect</button></div>
                </div>`;
            document.getElementById('adminRuntimeRefreshBtn')?.addEventListener('click', () => this.renderRuntimes());
        } catch(e) { this._showError('Failed to detect runtimes: '+e.message); }
    }

    // ── Search Tab ──
    renderSearch() {
        this.container.innerHTML = `<div class="admin-section"><h3 class="admin-section-title">Global Search</h3><div class="admin-search-box"><input type="text" class="form-input" id="adminSearchInput" placeholder="Search tasks, sessions..." autofocus><select class="form-input form-select" id="adminSearchType" style="width:140px;"><option value="all">All</option><option value="task">Tasks</option><option value="session">Sessions</option></select><button class="action-btn primary" id="adminSearchBtn">Search</button></div><div id="adminSearchResults" class="search-results"><div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-xl);">Enter a search query above</div></div></div>`;
        const doSearch = async () => {
            const q=document.getElementById('adminSearchInput')?.value?.trim(); if(!q)return;
            const type=document.getElementById('adminSearchType')?.value||'all';
            const res=document.getElementById('adminSearchResults');
            res.innerHTML='<div class="admin-loading">Searching...</div>';
            try {
                const data=await NexusAPI.globalSearch(q,type); const items=data.results||[];
                if(!items.length){res.innerHTML='<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-xl);">No results found</div>';return;}
                res.innerHTML=items.map(i=>`<div class="search-result-item"><span class="search-result-type"><span class="admin-badge info">${this._esc(i.type||'item')}</span></span><div class="search-result-info"><div class="search-result-title">${this._esc(i.title||i.id||'')}</div>${i.subtitle?`<div class="search-result-subtitle">${this._esc(i.subtitle)}</div>`:''}${i.excerpt?`<div class="search-result-excerpt">${this._esc(i.excerpt)}</div>`:''}</div></div>`).join('');
            } catch(e){res.innerHTML=`<div class="admin-error">Search failed: ${this._esc(e.message)}</div>`;}
        };
        document.getElementById('adminSearchBtn')?.addEventListener('click',doSearch);
        document.getElementById('adminSearchInput')?.addEventListener('keydown',e=>{if(e.key==='Enter')doSearch();});
    }

    // ── Audit Tab ──
    async renderAudit(params={}) {
        this._showLoading();
        try {
            const data=await NexusAPI.getAuditLog({limit:params.limit||100,action:params.action||''});
            const events=data.events||data.entries||[];
            let tbl='';
            if(!events.length){tbl='<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-xl);">No audit events found</div>';}
            else{const rows=events.map(e=>`<tr><td style="font-family:'JetBrains Mono',monospace;font-size:var(--text-xs);">${this._esc(e.id||e.event_id||'-')}</td><td><span class="admin-badge info">${this._esc(e.action||'')}</span></td><td>${this._esc(e.actor||e.user||'-')}</td><td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${this._esc(e.detail||e.details||'-')}</td><td style="white-space:nowrap;">${this._esc(e.timestamp||e.created_at||'-')}</td></tr>`).join('');
                tbl=`<div class="audit-table-wrapper"><table class="audit-table"><thead><tr><th>ID</th><th>Action</th><th>Actor</th><th>Detail</th><th>Timestamp</th></tr></thead><tbody>${rows}</tbody></table></div>`;}
            this.container.innerHTML=`<div class="admin-section"><h3 class="admin-section-title">Audit Log</h3><div class="admin-filter-row"><select class="form-input form-select" id="auditActionFilter"><option value="">All Actions</option><option value="task.create">task.create</option><option value="task.update">task.update</option><option value="task.delete">task.delete</option><option value="session.create">session.create</option><option value="session.delete">session.delete</option></select><button class="action-btn primary" id="auditFilterBtn">Filter</button><button class="action-btn" id="auditRefreshBtn">Refresh</button></div>${tbl}</div>`;
            document.getElementById('auditFilterBtn')?.addEventListener('click',()=>{this.renderAudit({action:document.getElementById('auditActionFilter')?.value||''});});
            document.getElementById('auditRefreshBtn')?.addEventListener('click',()=>this.renderAudit(params));
        } catch(e){this._showError('Failed to load audit log: '+e.message);}
    }

    // ── Cleanup Tab ──
    async renderCleanup() {
        this._showLoading();
        try {
            const data=await NexusAPI.getCleanupPreview();const policy=data.retention_policy||data.policy||{};const preview=data.preview||data.expired||[];
            let pol='';for(const[k,d]of Object.entries(policy)){pol+=`<div class="cleanup-policy-card"><div class="cleanup-policy-label">${this._esc(k)}</div><div class="cleanup-policy-value">${d}<span class="cleanup-policy-unit"> days</span></div></div>`;}
            let prev='';
            if(Array.isArray(preview)&&preview.length>0){const rows=preview.map(p=>`<tr><td>${this._esc(p.category||p.type||'-')}</td><td>${p.retention_days??'-'}</td><td>${this._esc(p.cutoff_date||'-')}</td><td><strong>${p.expired_count??p.count??0}</strong></td></tr>`).join('');prev=`<div class="audit-table-wrapper"><table class="audit-table"><thead><tr><th>Category</th><th>Retention (days)</th><th>Cutoff Date</th><th>Expired Count</th></tr></thead><tbody>${rows}</tbody></table></div>`;}
            else{prev='<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No expired data found</div>';}
            this.container.innerHTML=`<div class="admin-section"><h3 class="admin-section-title">Data Retention & Cleanup</h3><p class="admin-section-desc">Review retention policies and clean up expired data.</p>${pol?`<div class="cleanup-policy-cards">${pol}</div>`:''}<h4 style="font-weight:600;color:var(--text-primary);margin-bottom:var(--spacing-sm);">Expired Data Preview</h4>${prev}<div class="admin-actions" style="margin-top:var(--spacing-lg);"><button class="action-btn" id="adminDryRunBtn">Dry Run</button><button class="action-btn primary" id="adminExecuteCleanupBtn" style="background:var(--error);border-color:var(--error);">Execute Cleanup</button><button class="action-btn" id="adminCleanupRefreshBtn">Refresh</button></div><div id="cleanupResultArea"></div></div>`;
            document.getElementById('adminDryRunBtn')?.addEventListener('click',async()=>{const a=document.getElementById('cleanupResultArea');a.innerHTML='<div class="admin-loading">Running dry run...</div>';try{const r=await NexusAPI.executeCleanup(true);a.innerHTML=`<div class="admin-tool-result">${JSON.stringify(r,null,2)}</div>`;}catch(e){a.innerHTML=`<div class="admin-error">${this._esc(e.message)}</div>`;}});
            document.getElementById('adminExecuteCleanupBtn')?.addEventListener('click',async()=>{if(!confirm('Are you sure you want to execute cleanup?'))return;const a=document.getElementById('cleanupResultArea');a.innerHTML='<div class="admin-loading">Executing cleanup...</div>';try{const r=await NexusAPI.executeCleanup(false);a.innerHTML=`<div class="admin-tool-result">${JSON.stringify(r,null,2)}</div>`;setTimeout(()=>this.renderCleanup(),1500);}catch(e){a.innerHTML=`<div class="admin-error">${this._esc(e.message)}</div>`;}});
            document.getElementById('adminCleanupRefreshBtn')?.addEventListener('click',()=>this.renderCleanup());
        } catch(e){this._showError('Failed to load cleanup data: '+e.message);}
    }

    // ── Tools Tab ──
    renderTools() {
        this.container.innerHTML=`<div class="admin-section"><h3 class="admin-section-title">Tools</h3><div class="admin-tool-section"><div class="admin-tool-title">Schedule Parser</div><div class="admin-tool-desc">Parse natural language into a cron expression.</div><div style="display:flex;gap:var(--spacing-sm);"><input type="text" class="form-input" id="scheduleParseInput" placeholder="e.g., every weekday at 9am" style="flex:1;"><button class="action-btn primary" id="scheduleParseBtn">Parse</button></div><div id="scheduleParseResult"></div></div><div class="admin-tool-section"><div class="admin-tool-title">Data Export</div><div class="admin-tool-desc">Export tasks or sessions data.</div><div style="display:flex;gap:var(--spacing-sm);align-items:center;flex-wrap:wrap;"><select class="form-input form-select" id="exportType" style="width:160px;"><option value="tasks">Tasks</option><option value="sessions">Sessions</option></select><select class="form-input form-select" id="exportFormat" style="width:120px;"><option value="json">JSON</option><option value="csv">CSV</option></select><button class="action-btn primary" id="exportBtn">Download</button></div><div id="exportResult"></div></div><div class="admin-tool-section"><div class="admin-tool-title">Standup Report</div><div class="admin-tool-desc">Generate a summary report of recent task activity.</div><button class="action-btn primary" id="standupBtn">Generate Report</button><div id="standupResult"></div></div></div>`;
        document.getElementById('scheduleParseBtn')?.addEventListener('click',async()=>{const i=document.getElementById('scheduleParseInput')?.value?.trim();if(!i)return;const a=document.getElementById('scheduleParseResult');a.innerHTML='<div class="admin-loading">Parsing...</div>';try{const d=await NexusAPI.parseSchedule(i);a.innerHTML=`<div class="admin-tool-result">${JSON.stringify(d,null,2)}</div>`;}catch(e){a.innerHTML=`<div class="admin-error">${this._esc(e.message)}</div>`;}});
        document.getElementById('scheduleParseInput')?.addEventListener('keydown',e=>{if(e.key==='Enter')document.getElementById('scheduleParseBtn')?.click();});
        document.getElementById('exportBtn')?.addEventListener('click',async()=>{const t=document.getElementById('exportType')?.value||'tasks';const f=document.getElementById('exportFormat')?.value||'json';const a=document.getElementById('exportResult');a.innerHTML='<div class="admin-loading">Exporting...</div>';try{const d=await NexusAPI.exportData(t,f);const blob=new Blob([f==='csv'?d:JSON.stringify(d,null,2)],{type:f==='csv'?'text/csv':'application/json'});const u=URL.createObjectURL(blob);const l=document.createElement('a');l.href=u;l.download=`${t}_export.${f}`;l.click();URL.revokeObjectURL(u);a.innerHTML=`<div style="color:#22c55e;padding:var(--spacing-sm);">Downloaded ${f.toUpperCase()} file</div>`;}catch(e){a.innerHTML=`<div class="admin-error">${this._esc(e.message)}</div>`;}});
        document.getElementById('standupBtn')?.addEventListener('click',async()=>{const a=document.getElementById('standupResult');a.innerHTML='<div class="admin-loading">Generating report...</div>';try{const d=await NexusAPI.getStandup();a.innerHTML=`<div class="admin-tool-result">${JSON.stringify(d,null,2)}</div>`;}catch(e){a.innerHTML=`<div class="admin-error">${this._esc(e.message)}</div>`;}});
    }

    // ============================================================
    // New Tabs — Merged from Panel framework
    // ============================================================

    // ── Agents Tab ──
    async renderAgentsTab() {
        this._showLoading();
        try {
            const [agentsData, workload] = await Promise.all([
                NexusAPI.getAgents().catch(() => ({ agents: [] })),
                NexusAPI.getWorkload().catch(() => ({})),
            ]);
            const agents = agentsData.agents || [];
            const queues = workload.agents || workload.queues || [];

            // Agent Registry
            const online = agents.filter(a => a.available).length;
            let registryHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Agent Registry</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Total</span><span class="admin-metric-value large">${agents.length}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Online</span><span class="admin-metric-value" style="color:var(--success-500)">${online}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Offline</span><span class="admin-metric-value" style="color:var(--text-tertiary)">${agents.length - online}</span></div>
                        </div></div>
                    </div>
                    ${agents.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No agents found</div>' :
                      agents.map(a => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-icon ${a.available ? 'status-online' : 'status-offline'}">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="16" height="16"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
                            </div>
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(a.display_name || a.id)}</div>
                                <div class="panel-list-item-sub">${this._esc(a.agent_type || '')} &middot; ${this._esc(a.username || '')}</div>
                            </div>
                            <span class="panel-badge ${a.available ? 'badge-ok' : 'badge-muted'}">${a.available ? 'Online' : 'Offline'}</span>
                        </div>
                    `).join('')}
                </div>`;

            // Agent Heartbeat (static snapshot)
            let heartbeatHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Agent Heartbeat</h3>
                    ${agents.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No heartbeat data</div>' :
                      agents.slice(0, 10).map(a => `
                        <div class="panel-list-item">
                            <div class="timeline-dot ${a.available ? 'status-online' : 'status-offline'}"></div>
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(a.display_name || a.id)}</div>
                                <div class="panel-list-item-sub">${a.last_active ? new Date(a.last_active).toLocaleString() : 'Unknown'} &middot; ${a.available ? 'OK' : 'Offline'}</div>
                            </div>
                        </div>
                    `).join('')}
                </div>`;

            // Agent Soul
            let soulHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Agent Soul Profiles</h3>
                    ${agents.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No soul profiles</div>' :
                      agents.map(a => {
                        const soul = a.soul || a.identity;
                        return `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(a.display_name || a.id)}</div>
                                <div class="panel-list-item-sub">${this._esc(a.agent_type || '')}</div>
                                ${soul ? `<pre class="panel-code" style="margin-top:4px;font-size:var(--text-xs);">${this._esc(typeof soul === 'string' ? soul : JSON.stringify(soul, null, 2))}</pre>` : '<div style="color:var(--text-tertiary);font-size:var(--text-xs);">No soul profile configured</div>'}
                            </div>
                        </div>`;
                    }).join('')}
                </div>`;

            // Agent Queue
            const totalPending = queues.reduce((s, q) => s + (q.pending || q.queued || 0), 0);
            const totalRunning = queues.reduce((s, q) => s + (q.running || 0), 0);
            let queueHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Agent Queue</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Pending</span><span class="admin-metric-value large">${totalPending}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Running</span><span class="admin-metric-value" style="color:var(--success-500)">${totalRunning}</span></div>
                        </div></div>
                    </div>
                    ${queues.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No queue data</div>' :
                      queues.map(q => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(q.agent_id || q.name || 'Unknown')}</div>
                                <div class="panel-list-item-sub">Pending: ${q.pending || q.queued || 0} &middot; Running: ${q.running || 0}</div>
                            </div>
                            <div class="panel-queue-bar"><div class="queue-bar-fill" style="width: ${Math.min(100, ((q.running || 0) / Math.max(1, (q.capacity || 5))) * 100)}%"></div></div>
                        </div>
                    `).join('')}
                </div>`;

            // Agent Messaging
            let messagingHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Agent Messaging</h3>
                    <div id="agentMessagingContent"><div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No messages yet</div></div>
                </div>`;

            this.container.innerHTML = registryHtml + heartbeatHtml + soulHtml + queueHtml + messagingHtml;

            // Load messaging data lazily
            try {
                const msgData = await NexusAPI.getAuditLog({ action: 'message', limit: 30 });
                const messages = msgData.entries || msgData.logs || [];
                const mc = document.getElementById('agentMessagingContent');
                if (mc && messages.length > 0) {
                    mc.innerHTML = messages.map(m => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(m.from || m.agent_id || 'System')}</div>
                                <div class="panel-list-item-sub">${m.timestamp ? new Date(m.timestamp).toLocaleTimeString() : ''} &middot; ${this._esc(m.content || m.message || m.action || '')}</div>
                            </div>
                        </div>
                    `).join('');
                }
            } catch (e) { /* ignore */ }
        } catch (e) { this._showError('Failed to load agents: ' + e.message); }
    }

    // ── Activity Tab ──
    async renderActivityTab() {
        this._showLoading();
        try {
            const [auditData, diagData] = await Promise.all([
                NexusAPI.getAuditLog({ limit: 50 }).catch(() => ({ entries: [] })),
                NexusAPI.getDiagnostics().catch(() => ({})),
            ]);
            const entries = auditData.entries || auditData.logs || [];
            const tokenUsage = diagData.token_usage || diagData.usage || [];
            const costData = diagData.cost_analysis || diagData.billing || { total: 0, breakdown: [] };

            // Activity Feed
            let feedHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Activity Feed</h3>
                    ${entries.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No activity recorded</div>' :
                      entries.map(e => {
                        const time = e.timestamp ? new Date(e.timestamp).toLocaleString() : '';
                        return `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(e.action || e.event_type || 'Activity')}</div>
                                <div class="panel-list-item-sub">${time} ${e.username ? '&middot; ' + this._esc(e.username) : ''}</div>
                            </div>
                        </div>`;
                    }).join('')}
                </div>`;

            // Notifications
            const notifications = entries.filter(e => e.action === 'notification');
            const unread = notifications.filter(n => !n.read).length;
            let notifyHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Notifications ${unread > 0 ? `<span class="admin-badge warn" style="margin-left:8px;">${unread} Unread</span>` : ''}</h3>
                    ${notifications.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No notifications</div>' :
                      notifications.map(n => `
                        <div class="panel-list-item ${n.read ? '' : 'unread'}">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(n.action || n.title || 'Notification')}</div>
                                <div class="panel-list-item-sub">${this._esc(n.detail || n.message || '')}</div>
                            </div>
                            <span class="panel-badge ${n.level === 'error' ? 'badge-error' : n.level === 'warning' ? 'badge-warn' : 'badge-ok'}">${n.level || 'info'}</span>
                        </div>
                    `).join('')}
                </div>`;

            // Token Usage
            const totalTokens = tokenUsage.reduce((s, u) => s + (u.total_tokens || u.tokens || 0), 0);
            const totalCost = tokenUsage.reduce((s, u) => s + (u.cost || 0), 0);
            let tokenHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Token Usage</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Total Tokens</span><span class="admin-metric-value large">${(totalTokens / 1000).toFixed(1)}k</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Cost</span><span class="admin-metric-value">$${totalCost.toFixed(2)}</span></div>
                        </div></div>
                    </div>
                    ${tokenUsage.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No token usage data</div>' :
                      tokenUsage.map(u => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(u.provider || u.model || 'Unknown')}</div>
                                <div class="panel-list-item-sub">Prompt: ${(u.prompt_tokens || 0).toLocaleString()} &middot; Completion: ${(u.completion_tokens || 0).toLocaleString()} &middot; Total: ${(u.total_tokens || u.tokens || 0).toLocaleString()}</div>
                            </div>
                            <span class="panel-badge">${u.cost != null ? '$' + u.cost.toFixed(4) : ''}</span>
                        </div>
                    `).join('')}
                </div>`;

            // Cost Analysis
            const breakdown = costData.breakdown || [];
            const costTotal = costData.total || 0;
            let costHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Cost Analysis</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Total Cost</span><span class="admin-metric-value large">$${costTotal.toFixed(2)}</span></div>
                        </div></div>
                    </div>
                    ${breakdown.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No cost data available</div>' :
                      breakdown.map(b => {
                        const pct = costTotal > 0 ? ((b.cost / costTotal) * 100).toFixed(1) : 0;
                        return `
                        <div class="panel-bar-row">
                            <div class="panel-bar-label">${this._esc(b.provider || b.model || b.label)}</div>
                            <div class="panel-bar-track"><div class="panel-bar-fill" style="width: ${pct}%"></div></div>
                            <div class="panel-bar-value">$${(b.cost || 0).toFixed(2)} (${pct}%)</div>
                        </div>`;
                    }).join('')}
                </div>`;

            this.container.innerHTML = feedHtml + notifyHtml + tokenHtml + costHtml;
        } catch (e) { this._showError('Failed to load activity: ' + e.message); }
    }

    // ── Memory Tab ──
    async renderMemoryTab() {
        this._showLoading();
        try {
            const data = await NexusAPI.getAgents().catch(() => ({ agents: [] }));
            const agents = data.agents || [];

            // Memory Browser
            const memEntries = agents.map(a => ({
                id: a.id, agent: a.display_name || a.id,
                memory_count: a.memory_count || 0,
                last_updated: a.last_active || new Date().toISOString(),
            }));
            let browserHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Memory Browser</h3>
                    ${memEntries.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No memory entries found</div>' :
                      memEntries.map(e => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(e.agent)}</div>
                                <div class="panel-list-item-sub">${e.memory_count} entries &middot; Updated ${new Date(e.last_updated).toLocaleString()}</div>
                            </div>
                        </div>
                    `).join('')}
                </div>`;

            // Memory Tree
            const tree = agents.map(a => ({
                id: a.id, name: a.display_name || a.id,
                children: [
                    { id: `${a.id}-short`, name: 'Short-term', count: 0 },
                    { id: `${a.id}-long`, name: 'Long-term', count: 0 },
                    { id: `${a.id}-episodic`, name: 'Episodic', count: 0 },
                ],
            }));
            let treeHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Memory Tree</h3>
                    ${tree.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No memory tree data</div>' :
                      tree.map(n => `
                        <div style="margin-bottom:var(--spacing-sm);">
                            <div style="font-weight:600;color:var(--text-primary);margin-bottom:4px;">${this._esc(n.name)}</div>
                            ${n.children.map(c => `
                                <div style="display:flex;align-items:center;gap:var(--spacing-sm);padding-left:var(--spacing-lg);">
                                    <span class="tree-leaf-dot"></span>
                                    <span class="tree-label">${this._esc(c.name)}</span>
                                    <span class="panel-badge">${c.count}</span>
                                </div>
                            `).join('')}
                        </div>
                    `).join('')}
                </div>`;

            // Memory Graph
            const nodes = agents.map(a => ({ id: a.id, label: a.display_name || a.id, available: a.available }));
            const edges = [];
            for (let i = 0; i < agents.length; i++) {
                for (let j = i + 1; j < agents.length; j++) {
                    if (agents[i].username === agents[j].username) {
                        edges.push({ from: agents[i].id, to: agents[j].id });
                    }
                }
            }
            let graphHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Memory Graph</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Nodes</span><span class="admin-metric-value">${nodes.length}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Edges</span><span class="admin-metric-value">${edges.length}</span></div>
                        </div></div>
                    </div>
                    <div class="panel-graph-container"><canvas class="panel-canvas" id="memoryGraphCanvas" width="600" height="400"></canvas></div>
                </div>`;

            this.container.innerHTML = browserHtml + treeHtml + graphHtml;

            // Draw the memory graph
            const canvas = document.getElementById('memoryGraphCanvas');
            if (canvas && nodes.length > 0) {
                const ctx = canvas.getContext('2d');
                const w = canvas.width, h = canvas.height;
                ctx.clearRect(0, 0, w, h);
                const cx = w / 2, cy = h / 2, r = Math.min(w, h) * 0.35;
                const positions = {};
                nodes.forEach((node, i) => {
                    const angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
                    positions[node.id] = { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
                });
                ctx.strokeStyle = 'rgba(100, 160, 255, 0.3)'; ctx.lineWidth = 1;
                for (const edge of edges) {
                    const from = positions[edge.from], to = positions[edge.to];
                    if (from && to) { ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.lineTo(to.x, to.y); ctx.stroke(); }
                }
                const style = getComputedStyle(document.documentElement);
                for (const node of nodes) {
                    const pos = positions[node.id]; if (!pos) continue;
                    ctx.beginPath(); ctx.arc(pos.x, pos.y, 8, 0, 2 * Math.PI);
                    ctx.fillStyle = node.available ? (style.getPropertyValue('--success-500') || '#22c55e') : (style.getPropertyValue('--text-muted') || '#888');
                    ctx.fill(); ctx.strokeStyle = 'rgba(255,255,255,0.2)'; ctx.lineWidth = 1; ctx.stroke();
                    ctx.fillStyle = style.getPropertyValue('--text-primary') || '#fff'; ctx.font = '10px sans-serif'; ctx.textAlign = 'center';
                    ctx.fillText(node.label.split('/').pop(), pos.x, pos.y + 20);
                }
            }
        } catch (e) { this._showError('Failed to load memory: ' + e.message); }
    }

    // ── Integrations Tab ──
    async renderIntegrationsTab() {
        this._showLoading();
        try {
            const [diagData, projectsData, runtimeData] = await Promise.all([
                NexusAPI.getDiagnostics().catch(() => ({})),
                NexusAPI.getProjects().catch(() => ({ projects: [] })),
                NexusAPI.getAgentRuntimes('claude').catch(() => ({ runtimes: {} })),
            ]);

            // Webhooks
            const webhooks = diagData.webhooks || [];
            let webhookHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Webhooks</h3>
                    ${webhooks.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No webhooks configured</div>' :
                      webhooks.map(w => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(w.name || w.url || 'Webhook')}</div>
                                <div class="panel-list-item-sub">${this._esc(w.url || w.detail || '')} &middot; ${this._esc(w.events || 'all events')}</div>
                            </div>
                            <span class="panel-badge ${w.active !== false ? 'badge-ok' : 'badge-muted'}">${w.active !== false ? 'Active' : 'Inactive'}</span>
                        </div>
                    `).join('')}
                </div>`;

            // GitHub Sync
            const repos = (projectsData.projects || []).map(p => ({
                name: typeof p === 'string' ? p : p.name || p.path || 'Unknown',
                path: typeof p === 'string' ? p : p.path || '',
            }));
            let githubHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">GitHub Sync</h3>
                    ${repos.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No repositories connected</div>' :
                      repos.map(r => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(r.name)}</div>
                                <div class="panel-list-item-sub">${this._esc(r.path)}</div>
                            </div>
                            <span class="panel-badge badge-ok">Connected</span>
                        </div>
                    `).join('')}
                </div>`;

            // Claude Code
            const runtime = runtimeData.runtimes?.claude || runtimeData.runtime || {};
            const sessions = runtime.sessions || runtime.processes || [];
            let claudeHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Claude Code</h3>
                    ${Object.keys(runtime).length > 0 ? `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">Runtime: ${this._esc(runtime.version || 'Unknown')}</div>
                                <div class="panel-list-item-sub">${this._esc(runtime.path || 'Not found')}</div>
                            </div>
                            <span class="panel-badge ${runtime.available ? 'badge-ok' : 'badge-error'}">${runtime.available ? 'Available' : 'Not Found'}</span>
                        </div>
                    ` : '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No Claude Code runtime detected</div>'}
                    ${sessions.length > 0 ? sessions.map(s => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(s.id || s.session_id || 'Session')}</div>
                                <div class="panel-list-item-sub">${this._esc(s.project || s.cwd || '')}</div>
                            </div>
                            <span class="panel-badge badge-ok">Running</span>
                        </div>
                    `).join('') : ''}
                </div>`;

            // Teleport
            const connections = diagData.teleport_connections || diagData.connections || [];
            const activeConns = connections.filter(c => c.status === 'connected' || c.active).length;
            let teleportHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Teleport</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Active</span><span class="admin-metric-value" style="color:var(--success-500)">${activeConns}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Total</span><span class="admin-metric-value">${connections.length}</span></div>
                        </div></div>
                    </div>
                    ${connections.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No teleport connections</div>' :
                      connections.map(c => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(c.name || c.host || 'Connection')}</div>
                                <div class="panel-list-item-sub">${this._esc(c.host || '')} ${c.port ? ':' + c.port : ''} &middot; Latency: ${c.latency_ms ?? '—'}ms</div>
                            </div>
                            <span class="panel-badge ${c.status === 'connected' || c.active ? 'badge-ok' : 'badge-muted'}">${c.status || (c.active ? 'Active' : 'Inactive')}</span>
                        </div>
                    `).join('')}
                </div>`;

            this.container.innerHTML = webhookHtml + githubHtml + claudeHtml + teleportHtml;
        } catch (e) { this._showError('Failed to load integrations: ' + e.message); }
    }

    // ── Admin Tab ──
    async renderAdminTab() {
        this._showLoading();
        try {
            const [diagData, secData] = await Promise.all([
                NexusAPI.getDiagnostics().catch(() => ({})),
                NexusAPI.getSecurityScan().catch(() => ({})),
            ]);

            // Feature Flags
            const flags = diagData.feature_flags || diagData.flags || [];
            const enabled = flags.filter(f => f.enabled).length;
            let flagHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Feature Flags</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Enabled</span><span class="admin-metric-value" style="color:var(--success-500)">${enabled}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Disabled</span><span class="admin-metric-value">${flags.length - enabled}</span></div>
                        </div></div>
                    </div>
                    ${flags.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No feature flags configured</div>' :
                      flags.map(f => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(f.name || f.key)}</div>
                                <div class="panel-list-item-sub">${this._esc(f.description || '')}</div>
                            </div>
                            <label class="panel-toggle"><input type="checkbox" ${f.enabled ? 'checked' : ''} data-flag-key="${this._esc(f.name || f.key)}"><span class="toggle-slider"></span></label>
                        </div>
                    `).join('')}
                </div>`;

            // Standup Report
            let standupHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Standup Report</h3>
                    <button class="action-btn primary" id="adminStandupGenBtn" style="margin-bottom:var(--spacing-md);">Generate Report</button>
                    <div id="adminStandupResult"></div>
                </div>`;

            // RBAC
            const roles = secData.rbac || secData.roles || [
                { name: 'admin', permissions: ['*'], users: [] },
                { name: 'operator', permissions: ['task:read', 'task:write', 'agent:read'], users: [] },
                { name: 'viewer', permissions: ['task:read', 'agent:read'], users: [] },
            ];
            let rbacHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">RBAC</h3>
                    ${roles.map(r => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(r.name)}</div>
                                <div class="panel-list-item-sub">${(r.permissions || []).length} permissions</div>
                            </div>
                        </div>
                    `).join('')}
                </div>`;

            this.container.innerHTML = flagHtml + standupHtml + rbacHtml;

            // Bind standup report generation
            document.getElementById('adminStandupGenBtn')?.addEventListener('click', async () => {
                const area = document.getElementById('adminStandupResult');
                area.innerHTML = '<div class="admin-loading">Generating report...</div>';
                try {
                    const report = await NexusAPI.getStandup();
                    area.innerHTML = `
                        <div class="admin-section">
                            <div class="admin-metric"><span class="admin-metric-label">Completed</span><span class="admin-metric-value">${report.tasks_completed ?? 0}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">In Progress</span><span class="admin-metric-value">${report.tasks_in_progress ?? 0}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Agents Active</span><span class="admin-metric-value">${report.agents_active ?? 0}</span></div>
                        </div>
                        ${report.recent_completions?.length ? report.recent_completions.map(t => `<div class="panel-list-item"><div class="panel-list-item-body"><div class="panel-list-item-title">${this._esc(t.title || t.id)}</div><div class="panel-list-item-sub">${this._esc(t.agent_type || '')}</div></div></div>`).join('') : ''}
                    `;
                } catch (e) { area.innerHTML = `<div class="admin-error">${this._esc(e.message)}</div>`; }
            });

            // Bind feature flag toggles
            this.container.querySelectorAll('.panel-toggle input').forEach(input => {
                input.addEventListener('change', (e) => {
                    console.log(`Feature flag "${e.target.dataset.flagKey}" ${e.target.checked ? 'enabled' : 'disabled'}`);
                });
            });
        } catch (e) { this._showError('Failed to load admin: ' + e.message); }
    }

    // ── Scheduling Tab ──
    async renderSchedulingTab() {
        this._showLoading();
        try {
            const [schedData, taskData] = await Promise.all([
                NexusAPI.getSchedules({ pageSize: 50 }).catch(() => ({ schedules: [] })),
                NexusAPI.getTasks({ pageSize: 20 }).catch(() => ({ tasks: [] })),
            ]);
            const schedules = schedData.schedules || schedData.items || [];
            const doneTasks = (taskData.tasks || []).filter(t => t.status === 'done').slice(0, 20);

            // Cron Scheduler
            const activeSched = schedules.filter(s => s.status === 'active').length;
            const pausedSched = schedules.filter(s => s.status === 'paused').length;
            let cronHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Cron Scheduler</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Active</span><span class="admin-metric-value" style="color:var(--success-500)">${activeSched}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Paused</span><span class="admin-metric-value" style="color:var(--warning-500)">${pausedSched}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Total</span><span class="admin-metric-value">${schedules.length}</span></div>
                        </div></div>
                    </div>
                    ${schedules.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No schedules configured</div>' :
                      schedules.map(s => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(s.name || s.id)}</div>
                                <div class="panel-list-item-sub">${this._esc(s.cron || s.schedule || '')} &middot; ${this._esc(s.task_type || '')}</div>
                            </div>
                            <span class="panel-badge ${s.status === 'active' ? 'badge-ok' : s.status === 'paused' ? 'badge-warn' : 'badge-muted'}">${s.status}</span>
                        </div>
                    `).join('')}
                </div>`;

            // NLP Parser
            let nlpHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Natural Language Scheduler</h3>
                    <div style="display:flex;gap:var(--spacing-sm);">
                        <input type="text" class="form-input" id="schedulingNlpInput" placeholder='e.g. "every weekday at 9am"' style="flex:1;">
                        <button class="action-btn primary" id="schedulingNlpBtn">Parse</button>
                    </div>
                    <div id="schedulingNlpResult" style="margin-top:var(--spacing-sm);"></div>
                </div>`;

            // Template Tasks
            let templateHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Template Tasks</h3>
                    ${doneTasks.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No templates available</div>' :
                      '<div class="panel-grid">' + doneTasks.map(t => `
                        <div class="panel-card">
                            <div class="panel-card-title">${this._esc(t.title || t.id)}</div>
                            <div class="panel-card-meta">${this._esc(t.agent_type || 'any')} &middot; ${this._esc(t.priority || 'normal')}</div>
                        </div>
                    `).join('') + '</div>'}
                </div>`;

            this.container.innerHTML = cronHtml + nlpHtml + templateHtml;

            // Bind NLP parser
            document.getElementById('schedulingNlpBtn')?.addEventListener('click', async () => {
                const input = document.getElementById('schedulingNlpInput')?.value?.trim();
                if (!input) return;
                const area = document.getElementById('schedulingNlpResult');
                area.innerHTML = '<div class="admin-loading">Parsing...</div>';
                try {
                    const result = await NexusAPI.parseSchedule(input);
                    area.innerHTML = `
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Cron Expression</span><span class="admin-metric-value">${this._esc(result.cron || '')}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Human Readable</span><span class="admin-metric-value">${this._esc(result.human || result.description || '')}</span></div>
                        </div></div>
                        ${result.next_runs ? result.next_runs.map(r => `<div style="font-size:var(--text-sm);color:var(--text-secondary);">${this._esc(r)}</div>`).join('') : ''}
                    `;
                } catch (e) { area.innerHTML = `<div class="admin-error">${this._esc(e.message)}</div>`; }
            });
            document.getElementById('schedulingNlpInput')?.addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('schedulingNlpBtn')?.click(); });
        } catch (e) { this._showError('Failed to load scheduling: ' + e.message); }
    }
}

class SettingsView {
    constructor(app) {
        this.app = app;
        this.activeTab = localStorage.getItem('nexus-settings-tab') || 'overview';
        this.configSection = document.getElementById('settingsConfigSection');
        this.adminSection = document.getElementById('settingsAdminSection');
        this._skillsPanelContainer = null;
        this.bindEvents();
    }

    bindEvents() {
        document.querySelectorAll('.settings-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                this.switchTab(tab.dataset.settingsTab);
            });
        });
    }

    switchTab(tabName) {
        this.activeTab = tabName;
        localStorage.setItem('nexus-settings-tab', tabName);
        this.applyTab();
    }

    applyTab() {
        const configTabMap = {
            general: 'parameters',
            mcp: 'mcp',
        };

        // Tabs that show in admin section (with panel content merged)
        const adminTabs = [
            'overview', 'security', 'runtimes', 'audit', 'cleanup', 'tools',
            'agents', 'activity', 'memory', 'integrations', 'admin', 'scheduling',
        ];

        document.querySelectorAll('.settings-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.settingsTab === this.activeTab);
        });

        const configTab = configTabMap[this.activeTab];
        if (configTab) {
            // Pure ConfigView tabs (general, mcp)
            if (this.configSection) this.configSection.style.display = '';
            if (this.adminSection) this.adminSection.style.display = 'none';
            this._removeSkillsPanelSection();
            this.app.configView.refresh();
            this.app.configView.switchTab(configTab);
            return;
        }

        if (this.activeTab === 'skills') {
            // Skills tab: show ConfigView skills AND panel content below
            if (this.configSection) this.configSection.style.display = '';
            this.app.configView.refresh();
            this.app.configView.switchTab('skills');
            // Render panel content below config section
            this._renderSkillsPanelSection();
            return;
        }

        // All other tabs go through AdminView
        if (this.configSection) this.configSection.style.display = 'none';
        this._removeSkillsPanelSection();
        if (this.adminSection) this.adminSection.style.display = '';
        this.app.adminView.switchTab(this.activeTab);
    }

    async _renderSkillsPanelSection() {
        this._removeSkillsPanelSection();

        const section = document.createElement('div');
        section.id = 'settingsSkillsPanelSection';
        section.className = 'settings-section';
        section.style.marginTop = '0';
        section.innerHTML = '<div class="admin-content" id="skillsPanelContent"><div class="admin-loading">Loading skills panels...</div></div>';

        // Insert after configSection
        this.configSection?.after(section);
        this._skillsPanelContainer = document.getElementById('skillsPanelContent');
        if (!this._skillsPanelContainer) return;

        try {
            const [skillsData, secData] = await Promise.all([
                NexusAPI.getSkills().catch(() => ({ providers: {} })),
                NexusAPI.getSecurityScan().catch(() => ({})),
            ]);

            const providers = Object.keys(skillsData.providers || {});
            const totalSkills = providers.reduce((s, p) => s + (skillsData.providers[p]?.length || 0), 0);

            // Skill Registry
            let registryHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Skill Registry</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Providers</span><span class="admin-metric-value">${providers.length}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Total Skills</span><span class="admin-metric-value">${totalSkills}</span></div>
                        </div></div>
                    </div>
                    ${providers.map(p => {
                        const skills = skillsData.providers[p] || [];
                        return `
                        <div style="margin-bottom:var(--spacing-md);">
                            <div style="font-weight:600;color:var(--text-primary);margin-bottom:4px;">${this._esc(p)} <span class="panel-badge">${skills.length}</span></div>
                            ${skills.map(sk => `
                                <div class="panel-list-item">
                                    <div class="panel-list-item-body">
                                        <div class="panel-list-item-title">${this._esc(sk.skill_name || sk.name)}</div>
                                        <div class="panel-list-item-sub">${this._esc(sk.description || '')}</div>
                                    </div>
                                </div>
                            `).join('')}
                        </div>`;
                    }).join('')}
                </div>`;

            // Skill Security
            const pending = (secData.skills?.pending || []).map(s => ({ ...s, _status: 'pending' }));
            const approved = (secData.skills?.approved || []).map(s => ({ ...s, _status: 'approved' }));
            const allSkills = [...pending, ...approved];
            let secSkillsHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Skill Security</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Pending</span><span class="admin-metric-value" style="color:var(--warning-500)">${pending.length}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Approved</span><span class="admin-metric-value" style="color:var(--success-500)">${approved.length}</span></div>
                        </div></div>
                    </div>
                    ${allSkills.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No skill security entries</div>' :
                      allSkills.map(s => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(s.name || s.skill_name)}</div>
                                <div class="panel-list-item-sub">${this._esc(s.provider || '')} &middot; ${this._esc(s.risk_level || 'unknown risk')}</div>
                            </div>
                            <span class="panel-badge ${s._status === 'approved' ? 'badge-ok' : 'badge-warn'}">${s._status}</span>
                        </div>
                    `).join('')}
                </div>`;

            // Skill Sync
            let syncHtml = `
                <div class="admin-section" style="margin-top:var(--spacing-lg);">
                    <h3 class="admin-section-title">Skill Sync</h3>
                    ${providers.length === 0 ? '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-lg);">No providers to sync</div>' :
                      providers.map(p => {
                        const count = (skillsData.providers[p] || []).length;
                        return `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(p)}</div>
                                <div class="panel-list-item-sub">${count} skills</div>
                            </div>
                            <span class="panel-badge badge-ok">In Sync</span>
                        </div>`;
                    }).join('')}
                </div>`;

            this._skillsPanelContainer.innerHTML = registryHtml + secSkillsHtml + syncHtml;
        } catch (e) {
            this._skillsPanelContainer.innerHTML = `<div class="admin-error">Failed to load skills: ${this._esc(e.message)}</div>`;
        }
    }

    _removeSkillsPanelSection() {
        const existing = document.getElementById('settingsSkillsPanelSection');
        if (existing) existing.remove();
        this._skillsPanelContainer = null;
    }

    _esc(str) { return String(str||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

    refresh() {
        this.applyTab();
    }
}

class GlobalSearch {
    constructor(app) {
        this.app = app;
        this.modal = document.getElementById('globalSearchModal');
        this.input = document.getElementById('globalSearchInput');
        this.type = document.getElementById('globalSearchType');
        this.results = document.getElementById('globalSearchResults');
        this.submitBtn = document.getElementById('globalSearchSubmitBtn');
        this.triggerBtn = document.getElementById('globalSearchBtn');
        this.bindEvents();
    }

    bindEvents() {
        this.triggerBtn?.addEventListener('click', () => this.open());
        this.submitBtn?.addEventListener('click', () => this.search());
        this.input?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                this.search();
            }
        });

        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                this.open();
            }
        });
    }

    open() {
        this.modal?.classList.add('open');
        setTimeout(() => this.input?.focus(), 0);
    }

    _esc(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    async search() {
        const q = this.input?.value?.trim();
        if (!q || !this.results) return;
        const type = this.type?.value || 'all';
        this.results.innerHTML = '<div class="admin-loading">Searching...</div>';
        try {
            const data = await NexusAPI.globalSearch(q, type);
            const items = data.results || [];
            if (!items.length) {
                this.results.innerHTML = '<div style="color:var(--text-tertiary);text-align:center;padding:var(--spacing-xl);">No results found</div>';
                return;
            }
            this.results.innerHTML = items.map(i => `
                <div class="search-result-item">
                    <span class="search-result-type"><span class="admin-badge info">${this._esc(i.type || 'item')}</span></span>
                    <div class="search-result-info">
                        <div class="search-result-title">${this._esc(i.title || i.id || '')}</div>
                        ${i.subtitle ? `<div class="search-result-subtitle">${this._esc(i.subtitle)}</div>` : ''}
                        ${i.excerpt ? `<div class="search-result-excerpt">${this._esc(i.excerpt)}</div>` : ''}
                    </div>
                </div>
            `).join('');
        } catch (e) {
            this.results.innerHTML = `<div class="admin-error">Search failed: ${this._esc(e.message)}</div>`;
        }
    }
}

// ============================================================
// Plan Mode UI Components
// ============================================================

class PlanModeIndicator {
    /** Top-bar indicator showing plan mode status */
    constructor(app) {
        this.app = app;
        this.el = document.getElementById('planModeIndicator');
        this.statusEl = document.getElementById('planModeStatus');
        this.viewBtn = document.getElementById('planModeViewBtn');
        this.exitBtn = document.getElementById('planModeExitBtn');
        this._visible = false;
        this._bindEvents();
    }

    _bindEvents() {
        this.viewBtn?.addEventListener('click', () => this.app.planModePanel.toggle());
        this.exitBtn?.addEventListener('click', async () => {
            await this.app.planModeManager.exitPlanMode();
        });
    }

    show(status = 'Exploring') {
        this._visible = true;
        if (this.el) this.el.style.display = 'inline-flex';
        this.setStatus(status);
    }

    hide() {
        this._visible = false;
        if (this.el) this.el.style.display = 'none';
    }

    setStatus(status) {
        if (this.statusEl) this.statusEl.textContent = `— ${status}`;
    }

    get visible() { return this._visible; }
}

class PlanEditor {
    /** Plan content editor panel */
    constructor(app) {
        this.app = app;
        this.container = document.getElementById('planEditorContainer');
        this.textarea = document.getElementById('planEditor');
        this.submitBtn = document.getElementById('planSubmitBtn');
        this._bindEvents();
    }

    _bindEvents() {
        this.submitBtn?.addEventListener('click', async () => {
            const content = this.textarea?.value?.trim();
            if (!content) return;
            await this.app.planModeManager.submitPlan(content);
        });
    }

    show() {
        if (this.container) this.container.style.display = 'block';
        if (this.textarea) this.textarea.focus();
    }

    hide() {
        if (this.container) this.container.style.display = 'none';
    }

    clear() {
        if (this.textarea) this.textarea.value = '';
    }
}

class PlanApprovalWidget {
    /** Approval/rejection buttons with plan content display */
    constructor(app) {
        this.app = app;
        this.container = document.getElementById('planApprovalContainer');
        this.contentDisplay = document.getElementById('planContentDisplay');
        this.approveBtn = document.getElementById('planApproveBtn');
        this.rejectBtn = document.getElementById('planRejectBtn');
        this._bindEvents();
    }

    _bindEvents() {
        this.approveBtn?.addEventListener('click', async () => {
            await this.app.planModeManager.approvePlan();
        });
        this.rejectBtn?.addEventListener('click', async () => {
            await this.app.planModeManager.rejectPlan();
        });
    }

    show(content) {
        if (this.container) this.container.style.display = 'block';
        if (this.contentDisplay) this.contentDisplay.textContent = content;
    }

    hide() {
        if (this.container) this.container.style.display = 'none';
    }
}

class PlanModePanel {
    /** Dropdown panel for plan editing/approval */
    constructor(app) {
        this.app = app;
        this.el = document.getElementById('planModePanel');
        this.closeBtn = document.getElementById('planPanelCloseBtn');
        this._visible = false;
        this._bindEvents();
    }

    _bindEvents() {
        this.closeBtn?.addEventListener('click', () => this.hide());
        // Close on click outside
        document.addEventListener('click', (e) => {
            if (this._visible && this.el && !this.el.contains(e.target) &&
                !document.getElementById('planModeViewBtn')?.contains(e.target)) {
                this.hide();
            }
        });
    }

    toggle() {
        this._visible ? this.hide() : this.show();
    }

    show() {
        this._visible = true;
        if (this.el) this.el.style.display = 'block';
    }

    hide() {
        this._visible = false;
        if (this.el) this.el.style.display = 'none';
    }

    get visible() { return this._visible; }
}

class PlanModeManager {
    /** Manages plan mode state and API interactions */
    constructor(app) {
        this.app = app;
        this.indicator = new PlanModeIndicator(app);
        this.editor = new PlanEditor(app);
        this.approval = new PlanApprovalWidget(app);
        this.panel = new PlanModePanel(app);
        this._planMode = false;
        this._planContent = null;
    }

    async enterPlanMode() {
        try {
            await NexusAPI.enterPlanMode();
            this._planMode = true;
            this._planContent = null;
            this.indicator.show('Exploring');
            this.editor.show();
            this.approval.hide();
            this.panel.show();
        } catch (e) {
            console.error('Enter plan mode failed:', e);
            alert(e.message);
        }
    }

    async submitPlan(content) {
        try {
            await NexusAPI.submitPlan(content);
            this._planContent = content;
            this.indicator.setStatus('Awaiting Approval');
            this.editor.hide();
            this.approval.show(content);
        } catch (e) {
            console.error('Submit plan failed:', e);
            alert(e.message);
        }
    }

    async approvePlan() {
        try {
            await NexusAPI.approvePlan();
            this._planMode = false;
            this._planContent = null;
            this.indicator.hide();
            this.panel.hide();
            this.editor.clear();
        } catch (e) {
            console.error('Approve plan failed:', e);
            alert(e.message);
        }
    }

    async rejectPlan() {
        try {
            await NexusAPI.rejectPlan();
            this._planContent = null;
            this.indicator.setStatus('Exploring');
            this.approval.hide();
            this.editor.clear();
            this.editor.show();
        } catch (e) {
            console.error('Reject plan failed:', e);
            alert(e.message);
        }
    }

    async exitPlanMode() {
        try {
            await NexusAPI.exitPlanMode();
            this._planMode = false;
            this._planContent = null;
            this.indicator.hide();
            this.panel.hide();
            this.editor.clear();
        } catch (e) {
            console.error('Exit plan mode failed:', e);
            alert(e.message);
        }
    }

    async refreshStatus() {
        try {
            const data = await NexusAPI.getPlanStatus();
            this._planMode = data.plan_mode;
            this._planContent = data.plan_content;
            if (this._planMode) {
                if (this._planContent) {
                    this.indicator.show('Awaiting Approval');
                    this.editor.hide();
                    this.approval.show(this._planContent);
                } else {
                    this.indicator.show('Exploring');
                    this.editor.show();
                    this.approval.hide();
                }
            } else {
                this.indicator.hide();
            }
        } catch (e) {
            console.debug('Plan status refresh failed:', e);
        }
    }

    get isPlanMode() { return this._planMode; }
}


// ============================================================
// Main Application
// ============================================================
class NexusApp {
    constructor() {
        this.themeManager = new ThemeManager();
        this.chatView = new ChatView(this);
        // TaskBoardPanel replaces the old TaskView — instantiated as a panel
        this.taskBoardPanel = new TaskBoardPanel('task-board', {
            title: 'Task Board',
            icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4',
            refreshMs: 0,
        });
        // Legacy alias — panels and code that reference this.taskView still work
        this.taskView = {
            renderFullPage: () => this._mountTaskBoard(),
            _startAutoPolling: () => {},
            _stopAutoPolling: () => { this.taskBoardPanel._stopAutoPolling(); },
        };
        this.tabManager = new TabManager(this);
        this.layoutManager = new LayoutManager(this);
        this.configView = new ConfigView(this);
        this.adminView = new AdminView(this);
        this.settingsView = new SettingsView(this);
        this.globalSearch = new GlobalSearch(this);
        this.planModeManager = new PlanModeManager(this);
        this.planModePanel = this.planModeManager.panel;
        this.planModeIndicator = this.planModeManager.indicator;
        this.planModeEditor = this.planModeManager.editor;
        this.planModeApproval = this.planModeManager.approval;
        this.pageManager = new PageManager(this);
        this.availableAgents = [];
        this.customProviders = this.loadCustomProviders();
        this.serverDefaults = null; // loaded from GET /api/nexus/defaults

        this.deleteCallback = null;
        this.renameTabCallback = null;

        this.init();
    }

    // ============================================================
    // Custom Providers Management (localStorage persistence)
    // Storage format: [{name: string, baseProvider: string, configPath?: string, defaultModel?: string}, ...]
    // ============================================================
    loadCustomProviders() {
        try {
            const stored = localStorage.getItem('nexus-custom-providers');
            if (!stored) return [];
            const parsed = JSON.parse(stored);
            // Migrate old format (string array) to new format (object array)
            if (Array.isArray(parsed)) {
                return parsed.map(item => {
                    if (typeof item === 'string') {
                        return { name: item, baseProvider: 'claude', configPath: '', defaultModel: '' };
                    }
                    return { ...item, configPath: item.configPath || '', defaultModel: item.defaultModel || '' };
                });
            }
            return [];
        } catch (e) {
            console.error('Failed to load custom providers:', e);
            return [];
        }
    }

    saveCustomProviders() {
        try {
            localStorage.setItem('nexus-custom-providers', JSON.stringify(this.customProviders));
        } catch (e) {
            console.error('Failed to save custom providers:', e);
        }
    }

    addCustomProvider(name, baseProvider = 'claude', configPath = '') {
        if (!name || typeof name !== 'string') return false;
        const trimmed = name.trim();
        if (!trimmed) return false;

        const defaultProviders = ['nanobot', 'claude', 'gemini', 'codex', 'codebuddy'];
        
        if (defaultProviders.includes(trimmed.toLowerCase()) || 
            this.customProviders.some(p => p.name.toLowerCase() === trimmed.toLowerCase())) {
            return false;
        }

        this.customProviders.push({ name: trimmed, baseProvider: baseProvider, configPath: (configPath || '').trim(), defaultModel: '' });
        this.saveCustomProviders();
        return true;
    }

    isCustomAlias(name) {
        if (!name) return false;
        const trimmed = name.trim().toLowerCase();
        return this.customProviders.some(p => p.name.toLowerCase() === trimmed);
    }

    getCustomProviderNames() {
        return this.customProviders.map(p => p.name);
    }

    getBaseProvider(aliasName) {
        if (!aliasName) return null;
        const trimmed = aliasName.trim().toLowerCase();
        const found = this.customProviders.find(p => p.name.toLowerCase() === trimmed);
        return found ? found.baseProvider : null;
    }

    // Get config path for an alias (empty string means use baseProvider default)
    getAliasConfigPath(aliasName) {
        if (!aliasName) return '';
        const trimmed = aliasName.trim().toLowerCase();
        const found = this.customProviders.find(p => p.name.toLowerCase() === trimmed);
        return found ? (found.configPath || '') : '';
    }

    // ============================================================
    // Per-Provider/Alias Default Model Management
    // Default providers: stored in localStorage 'nexus-provider-models' ({provider: model})
    // Custom aliases: stored in customProviders[].defaultModel
    // ============================================================
    _loadProviderModels() {
        try {
            const stored = localStorage.getItem('nexus-provider-models');
            return stored ? JSON.parse(stored) : {};
        } catch { return {}; }
    }

    _saveProviderModels(models) {
        try {
            localStorage.setItem('nexus-provider-models', JSON.stringify(models));
        } catch (e) { console.error('Failed to save provider models:', e); }
    }

    getProviderDefaultModel(providerOrAlias) {
        if (!providerOrAlias) return '';
        const name = providerOrAlias.trim().toLowerCase();
        const defaultProviders = ['nanobot', 'claude', 'gemini', 'codex', 'codebuddy'];
        const models = this._loadProviderModels();
        if (defaultProviders.includes(name)) {
            return models[name] || '';
        }
        // Custom alias
        const found = this.customProviders.find(p => p.name.toLowerCase() === name);
        if (found) {
            return found.defaultModel || models[found.baseProvider] || '';
        }
        const inferredBaseProvider = defaultProviders.find(provider => name.startsWith(`${provider}-`));
        return inferredBaseProvider ? (models[inferredBaseProvider] || '') : '';
    }

    setProviderDefaultModel(providerOrAlias, model) {
        if (!providerOrAlias) return;
        const name = providerOrAlias.trim().toLowerCase();
        const val = (model || '').trim();
        const defaultProviders = ['nanobot', 'claude', 'gemini', 'codex', 'codebuddy'];
        if (defaultProviders.includes(name)) {
            const models = this._loadProviderModels();
            if (val) { models[name] = val; } else { delete models[name]; }
            this._saveProviderModels(models);
        } else {
            const found = this.customProviders.find(p => p.name.toLowerCase() === name);
            if (found) {
                found.defaultModel = val;
                this.saveCustomProviders();
            }
        }
    }

    removeCustomProvider(name) {
        if (!name || typeof name !== 'string') return false;
        const trimmed = name.trim().toLowerCase();
        
        const defaultProviders = ['nanobot', 'claude', 'gemini', 'codex', 'codebuddy'];
        if (defaultProviders.includes(trimmed)) {
            return false;
        }
        
        const index = this.customProviders.findIndex(p => p.name.toLowerCase() === trimmed);
        if (index === -1) return false;
        
        this.customProviders.splice(index, 1);
        this.saveCustomProviders();
        return true;
    }

    // Build custom_paths map for History API: alias -> config_dir
    getAliasHistoryConfigPaths() {
        const paths = {};
        for (const alias of this.customProviders) {
            if (alias.configPath) {
                const cp = (alias.configPath || '').trim();
                if (cp) paths[alias.name] = cp;
            }
        }
        return paths;
    }

    // Build custom_paths map for Skills API: alias -> skills_dir
    getAliasSkillsPaths() {
        const paths = {};
        for (const alias of this.customProviders) {
            if (alias.configPath) {
                // User specified a config dir like ~/.codex-internal → skills subdir
                let cp = alias.configPath;
                if (cp.startsWith('~/')) cp = cp; // backend will resolve ~
                paths[alias.name] = cp.endsWith('/skills') ? cp : cp + '/skills';
            }
            // If no configPath, backend will skip unknown provider names
            // unless we map it to its baseProvider's skills dir
        }
        return paths;
    }

    getDefaultProviders() {
        return ['nanobot', 'claude', 'gemini', 'codex', 'codebuddy'];
    }

    getAllProviders() {
        return [...this.getDefaultProviders(), ...this.getCustomProviderNames()];
    }

    // ============================================================
    // Default Provider Management
    // ============================================================
    getDefaultProvider() {
        return localStorage.getItem('nexus-default-provider')
            || (this.serverDefaults?.default_provider)
            || 'codebuddy';
    }

    setDefaultProvider(provider) {
        localStorage.setItem('nexus-default-provider', provider);
    }

    // ============================================================
    // Default Exec User Management
    // ============================================================
    getDefaultExecUser() {
        return (this.serverDefaults?.exec_user) || 'ubuntu';
    }

    // ============================================================
    // MCP Configuration Management
    // Storage format: { global: [...], providers: { claude: [...], ... } }
    // ============================================================
    loadMcpConfig() {
        try {
            const stored = localStorage.getItem('nexus-mcp-config');
            if (!stored) {
                return { global: [], providers: {} };
            }
            const parsed = JSON.parse(stored);
            return {
                global: Array.isArray(parsed.global) ? parsed.global : [],
                providers: parsed.providers || {}
            };
        } catch (e) {
            console.error('Failed to load MCP config:', e);
            return { global: [], providers: {} };
        }
    }

    saveMcpConfig(config) {
        try {
            localStorage.setItem('nexus-mcp-config', JSON.stringify(config));
        } catch (e) {
            console.error('Failed to save MCP config:', e);
        }
    }

    // ============================================================
    // Skills Configuration (deprecated - now API-driven)
    // Kept as no-ops for backward compatibility if referenced elsewhere
    // ============================================================
    loadSkillsConfig() {
        return { global: [], providers: {} };
    }

    saveSkillsConfig(config) {
        // No-op: skills are now managed via backend API
    }

    init() {
        // Initialize layout
        this.layoutManager.setMode(this.layoutManager.mode);

        // Load server defaults and agents
        this.loadServerDefaults();
        this.loadAgents();

        // Bind global events
        this.bindEvents();

        // Initialize TaskBoardPanel
        this.taskBoardPanel.init();

        // Trigger initial rendering for the current page (after refresh)
        const currentPage = this.pageManager.currentPage;
        if (currentPage === 'task') {
            this._mountTaskBoard();
        } else if (currentPage === 'settings' && this.settingsView) {
            this.settingsView.refresh();
        }

        // Start auto-refresh for session list and active messages
        this.chatView.startAutoRefresh();

        // Check plan mode status on load
        this.planModeManager.refreshStatus();
    }

    /**
     * Mount the TaskBoardPanel into the task page container.
     */
    _mountTaskBoard() {
        const container = document.getElementById('taskPageContainer');
        if (!container) return;
        this.taskBoardPanel.render(container);
    }


    /**
     * Load server-side defaults from .env via API.
     * These are used as fallback when localStorage has no value.
     */
    async loadServerDefaults() {
        try {
            this.serverDefaults = await NexusAPI.getDefaults();
            // Update API-level default exec_user so all API calls use it
            NexusAPI.setDefaultExecUser(this.serverDefaults.exec_user);
            // Re-render settings view if it's currently active so it picks up server defaults
            if (this.pageManager.currentPage === 'settings' && this.settingsView) {
                this.settingsView.refresh();
            }
        } catch (error) {
            console.warn('Failed to load server defaults, using built-in fallbacks:', error);
            this.serverDefaults = {};
        }
    }

    async loadAgents() {
        try {
            const data = await NexusAPI.getAgents();
            const agents = data.agents || [];
            this.availableAgents = agents;

            const select = document.getElementById('globalUserFilter');
            if (select) {
                const usernames = [...new Set(this.availableAgents.map(agent => agent.username))];
                select.innerHTML = '<option value="">All Users</option>' +
                    usernames.map(u => `<option value="${u}">${u}</option>`).join('');
            }
        } catch (error) {
            console.error('Failed to load agents:', error);
            const defUser = NexusAPI.getDefaultExecUser();
            this.availableAgents = [
                {
                    id: `${defUser}::claude`,
                    username: defUser,
                    agent_type: 'claude',
                    display_name: `${defUser} / claude`,
                    available: true
                }
            ];
            const select = document.getElementById('globalUserFilter');
            if (select) {
                select.innerHTML = `<option value="">All Users</option><option value="${defUser}">${defUser}</option>`;
            }
        }
    }

    bindEvents() {
        // Theme toggle
        const themeToggle = document.getElementById('themeToggle');
        if (themeToggle) {
            themeToggle.addEventListener('click', () => this.themeManager.toggle());
        }

        // Global user filter
        const userFilter = document.getElementById('globalUserFilter');
        if (userFilter) {
            userFilter.addEventListener('change', () => this.refresh());
        }

        // Modal events
        this.setupModals();

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            // Escape to close modals
            if (e.key === 'Escape') {
                document.querySelectorAll('.modal-backdrop.open').forEach(modal => {
                    modal.classList.remove('open');
                });
            }

            // Ctrl/Cmd + 1-4 for layout switching
            if ((e.ctrlKey || e.metaKey) && e.key >= '1' && e.key <= '4') {
                e.preventDefault();
                const modes = ['single', 'horizontal', 'vertical', 'quad'];
                this.layoutManager.setMode(modes[parseInt(e.key) - 1]);
            }
        });
    }

    setupModals() {
        // Close modal buttons
        document.querySelectorAll('[data-close-modal]').forEach(btn => {
            btn.addEventListener('click', () => {
                btn.closest('.modal-backdrop')?.classList.remove('open');
            });
        });

        // Trigger mode radio (Immediate / Cron / One-Time)
        document.querySelectorAll('input[name="triggerMode"]').forEach(radio => {
            radio.addEventListener('change', () => {
                const mode = document.querySelector('input[name="triggerMode"]:checked')?.value || 'immediate';
                const cronFields = document.getElementById('cronFields');
                const onetimeFields = document.getElementById('onetimeFields');
                const scheduleExtra = document.getElementById('scheduleExtraFields');
                const cronExtra = document.getElementById('cronExtraFields');
                if (cronFields) cronFields.style.display = mode === 'cron' ? '' : 'none';
                if (onetimeFields) onetimeFields.style.display = mode === 'onetime' ? '' : 'none';
                if (scheduleExtra) scheduleExtra.style.display = mode === 'immediate' ? 'none' : '';
                if (cronExtra) cronExtra.style.display = mode === 'cron' ? '' : 'none';
                this._updateSubmitButtonText();
            });
        });

        // Loop mode radio (Normal / Loop)
        document.querySelectorAll('input[name="loopMode"]').forEach(radio => {
            radio.addEventListener('change', () => {
                const mode = document.querySelector('input[name="loopMode"]:checked')?.value || 'normal';
                const loopFields = document.getElementById('loopFields');
                if (loopFields) loopFields.style.display = mode === 'loop' ? '' : 'none';
            });
        });

        // Submit task button
        const submitBtn = document.getElementById('submitTaskBtn');
        if (submitBtn) {
            submitBtn.addEventListener('click', () => this.submitTask());
        }

        const scheduleParseBtn = document.getElementById('scheduleNaturalParseBtn');
        if (scheduleParseBtn) {
            scheduleParseBtn.addEventListener('click', () => this.parseScheduleNaturalLanguage());
        }

        // Confirm delete button
        const confirmDeleteBtn = document.getElementById('confirmDeleteBtn');
        if (confirmDeleteBtn) {
            confirmDeleteBtn.addEventListener('click', () => {
                if (this.deleteCallback) {
                    this.deleteCallback();
                    this.deleteCallback = null;
                }
                document.getElementById('deleteModal')?.classList.remove('open');
            });
        }

        // Confirm rename button
        const confirmRenameBtn = document.getElementById('confirmRenameBtn');
        if (confirmRenameBtn) {
            confirmRenameBtn.addEventListener('click', () => {
                const input = document.getElementById('renameTabInput');
                if (this.renameTabCallback && input?.value.trim()) {
                    this.renameTabCallback(input.value.trim());
                    this.renameTabCallback = null;
                }
                document.getElementById('renameTabModal')?.classList.remove('open');
            });
        }

        // Save schedule (edit modal) button
        const saveScheduleBtn = document.getElementById('saveScheduleBtn');
        if (saveScheduleBtn) {
            saveScheduleBtn.addEventListener('click', async () => {
                const scheduleId = document.getElementById('editScheduleId')?.value;
                if (!scheduleId) return;

                const name = document.getElementById('editScheduleName')?.value.trim();
                const cronExpression = document.getElementById('editScheduleCron')?.value.trim();
                const timezone = document.getElementById('editScheduleTimezone')?.value.trim();
                const description = document.getElementById('editScheduleDescription')?.value.trim();
                const workspace = document.getElementById('editScheduleWorkspace')?.value.trim();
                const maxRunsStr = document.getElementById('editScheduleMaxRuns')?.value.trim();

                if (!name) { this.showToast('Schedule name is required', 'error'); return; }
                if (!cronExpression) { this.showToast('Cron expression is required', 'error'); return; }
                if (!description) { this.showToast('Task description is required', 'error'); return; }

                const payload = {};
                if (name) payload.name = name;
                if (cronExpression) payload.cron_expression = cronExpression;
                if (timezone) payload.timezone = timezone;
                if (description) payload.description = description;
                payload.workspace = workspace || null;
                if (maxRunsStr) {
                    const maxRuns = parseInt(maxRunsStr, 10);
                    if (!isNaN(maxRuns) && maxRuns > 0) payload.max_runs = maxRuns;
                }

                try {
                    await NexusAPI.updateSchedule(scheduleId, payload);
                    this.showToast('Schedule updated', 'success');
                    document.getElementById('editScheduleModal')?.classList.remove('open');
                    // Refresh schedule panel if visible
                    const panel = document.getElementById('schedulePanel-global');
                    if (panel && panel.style.display !== 'none') {
                        this.taskView.loadSchedules('global');
                    }
                } catch (error) {
                    this.showToast(error.message || 'Failed to update schedule', 'error');
                }
            });
        }
    }

    refresh() {
        const currentPage = this.pageManager.currentPage;

        // Clear auto-refresh cache so next poll forces a full re-render
        this.chatView._lastSessionsHash = {};
        this.chatView._lastMessageCountBySession = {};

        if (currentPage === 'chat') {
            // Refresh chat sessions in all visible panes
            const panesCount = this.layoutManager.getPanesCount();
            for (let i = 0; i < panesCount; i++) {
                const tab = this.tabManager.getActiveTab(i);
                if (tab) {
                    this.chatView.loadSessions(i);
                }
            }
        } else if (currentPage === 'task') {
            // Refresh task list in the standalone task page
            this.taskView.loadTasks('global');
        } else if (currentPage === 'settings' && this.settingsView) {
            this.settingsView.refresh();
        }
    }

    refreshChatProviders() {
        const panesCount = this.layoutManager.getPanesCount();
        for (let i = 0; i < panesCount; i++) {
            this.chatView.refreshNewSessionSelectors(i);
        }
        this.refreshTaskModalSelectors();
    }

    refreshTaskModalSelectors() {
        const modal = document.getElementById('createTaskModal');
        if (!modal || !modal.classList.contains('open')) return;

        const globalUserFilter = document.getElementById('globalUserFilter');
        const selectedUser = globalUserFilter?.value || '';
        const allAgents = this.chatView.getAvailableAgents('');
        const rawUsernames = [...new Set(allAgents.map(agent => agent.username))];
        const usernames = rawUsernames.length ? rawUsernames : [NexusAPI.getDefaultExecUser()];
        const fallbackUser = (selectedUser && usernames.includes(selectedUser))
            ? selectedUser
            : (usernames.includes(NexusAPI.getDefaultExecUser()) ? NexusAPI.getDefaultExecUser() : (usernames[0] || NexusAPI.getDefaultExecUser()));

        const buildModelOptions = (user) => {
            const agents = this.chatView.getAvailableAgents(user);
            const agentModels = [...new Set(agents.map(agent => agent.agent_type))];
            const customProviderNames = this.getCustomProviderNames ? this.getCustomProviderNames() : [];
            const defaultProviders = this.getDefaultProviders ? this.getDefaultProviders() : ['nanobot', 'claude', 'gemini', 'codex', 'codebuddy'];
            const allModels = [...new Set([...defaultProviders, ...customProviderNames, ...agentModels])];
            if (!allModels.length) {
                return '<option value="claude">claude</option>';
            }
            const getModelLabel = (model) => {
                if (this.isCustomAlias && this.isCustomAlias(model)) {
                    const baseProvider = this.getBaseProvider ? this.getBaseProvider(model) : null;
                    if (baseProvider) {
                        return `${model} (${baseProvider})`;
                    }
                }
                return model;
            };
            return allModels.map(model => {
                const label = getModelLabel(model);
                return `<option value="${this.chatView.escapeHtml(model)}">${this.chatView.escapeHtml(label)}</option>`;
            }).join('');
        };

        const updateSelectors = (userSelectId, modelSelectId) => {
            const userSelect = document.getElementById(userSelectId);
            const modelSelect = document.getElementById(modelSelectId);
            if (!modelSelect) return;

            const currentUser = userSelect?.value || fallbackUser;
            const resolvedUser = usernames.includes(currentUser) ? currentUser : fallbackUser;

            if (userSelect) {
                userSelect.innerHTML = usernames.map(u => `<option value="${this.chatView.escapeHtml(u)}">${this.chatView.escapeHtml(u)}</option>`).join('');
                userSelect.value = resolvedUser;
            }

            const currentModel = modelSelect.value;
            modelSelect.innerHTML = buildModelOptions(resolvedUser);
            const optionValues = Array.from(modelSelect.options).map(opt => opt.value);
            const defaultPref = this.getDefaultProvider();
            const selected = optionValues.includes(currentModel)
                ? currentModel
                : (optionValues.includes(defaultPref) ? defaultPref : (optionValues[0] || 'claude'));
            modelSelect.value = selected;
            this._loadTaskSourceSessionOptions(resolvedUser).catch(err => {
                console.warn('Failed to refresh source sessions:', err);
            });
        };

        updateSelectors('taskUser', 'taskProvider');
    }

    showCreateTaskModal(mode = 'single') {
        const modal = document.getElementById('createTaskModal');
        if (!modal) return;

        // Reset all fields
        const taskName = document.getElementById('taskName');
        if (taskName) taskName.value = '';
        const taskDescription = document.getElementById('taskDescription');
        if (taskDescription) taskDescription.value = '';
        const taskLlmModel = document.getElementById('taskLlmModel');
        if (taskLlmModel) taskLlmModel.value = '';
        const taskWorkspace = document.getElementById('taskWorkspace');
        if (taskWorkspace) taskWorkspace.value = '';
        const taskDependsOn = document.getElementById('taskDependsOn');
        if (taskDependsOn) taskDependsOn.value = '';
        const taskSourceSession = document.getElementById('taskSourceSession');
        if (taskSourceSession) {
            taskSourceSession.innerHTML = '<option value="">None (new task session)</option>';
            taskSourceSession.value = '';
        }

        // Reset loop fields
        const normalRadio = document.querySelector('input[name="loopMode"][value="normal"]');
        if (normalRadio) normalRadio.checked = true;
        const loopFieldsDiv = document.getElementById('loopFields');
        if (loopFieldsDiv) loopFieldsDiv.style.display = 'none';
        const loopKeywords = document.getElementById('loopKeywords');
        if (loopKeywords) loopKeywords.value = '';
        const loopMaxIterations = document.getElementById('loopMaxIterations');
        if (loopMaxIterations) loopMaxIterations.value = '5';

        // Reset trigger to Immediate
        const immediateRadio = document.querySelector('input[name="triggerMode"][value="immediate"]');
        if (immediateRadio) immediateRadio.checked = true;
        const cronFields = document.getElementById('cronFields');
        if (cronFields) cronFields.style.display = 'none';
        const onetimeFields = document.getElementById('onetimeFields');
        if (onetimeFields) onetimeFields.style.display = 'none';
        const scheduleExtra = document.getElementById('scheduleExtraFields');
        if (scheduleExtra) scheduleExtra.style.display = 'none';
        const cronExtra = document.getElementById('cronExtraFields');
        if (cronExtra) cronExtra.style.display = 'none';

        // Reset schedule fields
        const scheduleCron = document.getElementById('scheduleCron');
        if (scheduleCron) scheduleCron.value = '';
        const scheduleRunAt = document.getElementById('scheduleRunAt');
        if (scheduleRunAt) scheduleRunAt.value = '';
        const scheduleTimezone = document.getElementById('scheduleTimezone');
        if (scheduleTimezone) scheduleTimezone.value = 'UTC';
        const scheduleMaxRuns = document.getElementById('scheduleMaxRuns');
        if (scheduleMaxRuns) scheduleMaxRuns.value = '';
        const scheduleNaturalInput = document.getElementById('scheduleNaturalInput');
        if (scheduleNaturalInput) scheduleNaturalInput.value = '';
        const scheduleNaturalResult = document.getElementById('scheduleNaturalResult');
        if (scheduleNaturalResult) {
            scheduleNaturalResult.textContent = '';
            scheduleNaturalResult.style.color = 'var(--text-muted)';
        }

        // Reset submit button text
        this._updateSubmitButtonText();

        // Initialize agent/model selectors (same as New Chat)
        const globalUserFilter = document.getElementById('globalUserFilter');
        const selectedUser = globalUserFilter?.value || '';
        const allAgents = this.chatView.getAvailableAgents('');
        const rawUsernames = [...new Set(allAgents.map(agent => agent.username))];
        const usernames = rawUsernames.length ? rawUsernames : [NexusAPI.getDefaultExecUser()];
        const initialUser = (selectedUser && usernames.includes(selectedUser))
            ? selectedUser
            : (usernames.includes(NexusAPI.getDefaultExecUser()) ? NexusAPI.getDefaultExecUser() : (usernames[0] || NexusAPI.getDefaultExecUser()));

        const buildModelOptions = (user) => {
            const agents = this.chatView.getAvailableAgents(user);
            const agentModels = [...new Set(agents.map(agent => agent.agent_type))];
            const customProviderNames = this.getCustomProviderNames ? this.getCustomProviderNames() : [];
            const defaultProviders = this.getDefaultProviders ? this.getDefaultProviders() : ['nanobot', 'claude', 'gemini', 'codex', 'codebuddy'];
            const allModels = [...new Set([...defaultProviders, ...customProviderNames, ...agentModels])];
            if (!allModels.length) {
                return '<option value="claude">claude</option>';
            }
            const getModelLabel = (model) => {
                if (this.isCustomAlias && this.isCustomAlias(model)) {
                    const baseProvider = this.getBaseProvider ? this.getBaseProvider(model) : null;
                    if (baseProvider) {
                        return `${model} (${baseProvider})`;
                    }
                }
                return model;
            };
            return allModels.map(model => {
                const label = getModelLabel(model);
                return `<option value="${this.chatView.escapeHtml(model)}">${this.chatView.escapeHtml(label)}</option>`;
            }).join('');
        };

        const setupAgentSelectors = (userSelectId, modelSelectId, preferredUser = initialUser, preferredModel = null) => {
            const userSelect = document.getElementById(userSelectId);
            const modelSelect = document.getElementById(modelSelectId);
            if (!modelSelect) return;

            const defaultModel = preferredModel || this.getDefaultProvider();

            const applyModelOptions = (user) => {
                modelSelect.innerHTML = buildModelOptions(user);
                const optionValues = Array.from(modelSelect.options).map(opt => opt.value);
                const selected = optionValues.includes(defaultModel) ? defaultModel : (optionValues[0] || 'claude');
                modelSelect.value = selected;
                this._loadTaskSourceSessionOptions(user).catch(err => {
                    console.warn('Failed to load source sessions:', err);
                });
            };

            if (userSelect) {
                userSelect.innerHTML = usernames.map(u => `<option value="${this.chatView.escapeHtml(u)}">${this.chatView.escapeHtml(u)}</option>`).join('');
                userSelect.value = preferredUser;
                applyModelOptions(preferredUser);
                userSelect.onchange = () => {
                    const user = userSelect.value || preferredUser;
                    applyModelOptions(user);
                };
            } else {
                applyModelOptions(preferredUser);
            }
        };

        setupAgentSelectors('taskUser', 'taskProvider');

        modal.classList.add('open');
    }

    async _loadTaskSourceSessionOptions(username) {
        const sourceSelect = document.getElementById('taskSourceSession');
        if (!sourceSelect) return;

        const selected = sourceSelect.value || '';
        sourceSelect.innerHTML = '<option value="">None (new task session)</option>';

        try {
            const data = await NexusAPI.getSessions({
                username: username || undefined,
                page: 1,
                pageSize: 100,
            });
            const sessions = Array.isArray(data?.sessions) ? data.sessions : [];
            sessions.forEach((session) => {
                const sid = session?.id || '';
                if (!sid) return;
                const title = session?.title || sid;
                const label = `${title} (${sid.slice(0, 8)})`;
                sourceSelect.insertAdjacentHTML(
                    'beforeend',
                    `<option value="${this.chatView.escapeHtml(sid)}">${this.chatView.escapeHtml(label)}</option>`,
                );
            });
            if (selected && sessions.some((s) => (s?.id || '') === selected)) {
                sourceSelect.value = selected;
            }
        } catch (error) {
            console.warn('Unable to load task source sessions', error);
        }
    }

    async parseScheduleNaturalLanguage() {
        const inputEl = document.getElementById('scheduleNaturalInput');
        const resultEl = document.getElementById('scheduleNaturalResult');
        const input = inputEl?.value?.trim();

        if (!input) {
            if (resultEl) {
                resultEl.textContent = 'Enter a natural-language schedule first.';
                resultEl.style.color = 'var(--warning)';
            }
            return;
        }

        try {
            const parsed = await NexusAPI.parseSchedule(input);
            const cronExpr = parsed?.cronExpr || parsed?.cron_expr;
            const humanReadable = parsed?.humanReadable || parsed?.human_readable || '';

            if (!cronExpr) {
                if (resultEl) {
                    resultEl.textContent = parsed?.error || 'Could not parse schedule expression.';
                    resultEl.style.color = 'var(--error)';
                }
                return;
            }

            const cronInput = document.getElementById('scheduleCron');
            if (cronInput) cronInput.value = cronExpr;

            const cronRadio = document.querySelector('input[name="triggerMode"][value="cron"]');
            if (cronRadio) {
                cronRadio.checked = true;
                cronRadio.dispatchEvent(new Event('change'));
            }

            if (resultEl) {
                resultEl.textContent = humanReadable
                    ? `${humanReadable} → ${cronExpr}`
                    : `Parsed cron: ${cronExpr}`;
                resultEl.style.color = 'var(--success)';
            }
        } catch (error) {
            if (resultEl) {
                resultEl.textContent = error.message || 'Failed to parse schedule expression.';
                resultEl.style.color = 'var(--error)';
            }
        }
    }

    /** Update submit button text based on trigger mode */
    _updateSubmitButtonText() {
        const btn = document.getElementById('submitTaskBtn');
        if (!btn) return;
        const triggerMode = document.querySelector('input[name="triggerMode"]:checked')?.value || 'immediate';
        if (triggerMode === 'cron' || triggerMode === 'onetime') {
            btn.textContent = 'Create Schedule';
        } else {
            btn.textContent = 'Create Task';
        }
    }

    getTaskAgentSelection() {
        const globalUserFilter = document.getElementById('globalUserFilter');
        const execUser = document.getElementById('taskUser')?.value || globalUserFilter?.value || NexusAPI.getDefaultExecUser();
        const providerSelection = document.getElementById('taskProvider')?.value || this.getDefaultProvider();
        return { execUser, providerSelection };
    }

    resolveProviderSelection(providerSelection) {
        const normalizedSelection = (providerSelection || this.getDefaultProvider() || 'codebuddy').trim().toLowerCase();
        const defaultProviders = this.getDefaultProviders ? this.getDefaultProviders() : ['nanobot', 'claude', 'gemini', 'codex', 'codebuddy'];
        const baseProvider = defaultProviders.includes(normalizedSelection)
            ? normalizedSelection
            : ((this.getBaseProvider && this.getBaseProvider(normalizedSelection))
                || defaultProviders.find(providerName => normalizedSelection.startsWith(`${providerName}-`))
                || normalizedSelection);
        return {
            provider: baseProvider,
            alias: normalizedSelection,
        };
    }

    resolveTaskModel(selectedProvider, aliasValue, explicitModel) {
        return explicitModel
            || this.getProviderDefaultModel(aliasValue)
            || this.getProviderDefaultModel(selectedProvider)
            || undefined;
    }

    getLoopConfig() {
        const loopEnabled = document.querySelector('input[name="loopMode"]:checked')?.value === 'loop';
        if (!loopEnabled) {
            return null;
        }

        const keywordsStr = document.getElementById('loopKeywords')?.value.trim();
        if (!keywordsStr) {
            throw new Error('Please enter at least one stop keyword for Ralph Loop');
        }

        const keywords = keywordsStr.split(',').map(keyword => keyword.trim()).filter(Boolean);
        if (keywords.length === 0) {
            throw new Error('Please enter at least one valid stop keyword');
        }

        const maxIterations = parseInt(document.getElementById('loopMaxIterations')?.value.trim(), 10);
        if (Number.isNaN(maxIterations) || maxIterations < 1 || maxIterations > 100) {
            throw new Error('Max iterations must be between 1 and 100');
        }

        return {
            loop_enabled: true,
            loop_max_iterations: maxIterations,
            loop_keywords: keywords,
        };
    }

    async submitTask() {
        const { execUser, providerSelection } = this.getTaskAgentSelection();
        const triggerMode = document.querySelector('input[name="triggerMode"]:checked')?.value || 'immediate';

        try {
            if (triggerMode === 'cron' || triggerMode === 'onetime') {
                await this._submitSchedule(execUser, providerSelection, triggerMode);
            } else {
                await this._submitSingleTask(execUser, providerSelection);
            }

            document.getElementById('createTaskModal')?.classList.remove('open');
            this.refresh();
            // Start auto-polling so kanban updates as tasks transition to doing/done
            this.taskView._startAutoPolling('global');
        } catch (error) {
            console.error('Failed to create task:', error);
            this.showToast(error.message || 'Failed to create task', 'error');
        }
    }

    async _submitSingleTask(execUser, providerSelection) {
        const description = document.getElementById('taskDescription')?.value.trim();
        const workspace = document.getElementById('taskWorkspace')?.value.trim();
        const dependsOnStr = document.getElementById('taskDependsOn')?.value.trim();
        const llmModel = document.getElementById('taskLlmModel')?.value.trim();
        const { provider: selectedProvider, alias: aliasValue } = this.resolveProviderSelection(providerSelection);
        const loopConfig = this.getLoopConfig();

        if (!description) {
            throw new Error('Description is required');
        }

        const sourceSessionId = document.getElementById('taskSourceSession')?.value?.trim();

        const payload = {
            description,
            provider: selectedProvider,
            alias: aliasValue,
            model: this.resolveTaskModel(selectedProvider, aliasValue, llmModel),
            workspace: workspace || undefined,
            source_session_id: sourceSessionId || undefined,
            depends_on: dependsOnStr ? dependsOnStr.split(',').map(s => s.trim()).filter(Boolean) : undefined,
            ...(loopConfig || {}),
        };

        await NexusAPI.createTask(payload, { execUser });
        const msg = loopConfig
            ? `Loop task created (max ${loopConfig.loop_max_iterations} iterations)`
            : 'Task created successfully';
        this.showToast(msg, 'success');
    }

    async _submitSchedule(execUser, providerSelection, triggerMode) {
        const description = document.getElementById('taskDescription')?.value.trim();
        const name = document.getElementById('taskName')?.value.trim();
        const timezone = document.getElementById('scheduleTimezone')?.value.trim() || 'UTC';
        const workspace = document.getElementById('taskWorkspace')?.value.trim();
        const llmModel = document.getElementById('taskLlmModel')?.value.trim();
        const maxRunsStr = document.getElementById('scheduleMaxRuns')?.value.trim();
        const { provider: selectedProvider, alias: aliasValue } = this.resolveProviderSelection(providerSelection);
        const loopConfig = this.getLoopConfig();

        if (!description) throw new Error('Description is required');
        if (!name) throw new Error('Please enter a name for the schedule');

        const payload = {
            name,
            timezone,
            description,
            provider: selectedProvider,
            alias: aliasValue,
            exec_user: execUser,
        };

        if (triggerMode === 'cron') {
            const cronExpression = document.getElementById('scheduleCron')?.value.trim();
            if (!cronExpression) throw new Error('Please enter a cron expression');
            payload.cron_expression = cronExpression;
        } else {
            const runAtStr = document.getElementById('scheduleRunAt')?.value.trim();
            if (!runAtStr) throw new Error('Please select a date and time');
            const runAtDate = new Date(runAtStr);
            if (Number.isNaN(runAtDate.getTime())) throw new Error('Invalid date/time value');
            payload.run_at = runAtDate.toISOString();
        }

        if (workspace) payload.workspace = workspace;
        if (llmModel) payload.model = llmModel;
        if (maxRunsStr) {
            const maxRuns = parseInt(maxRunsStr, 10);
            if (!Number.isNaN(maxRuns) && maxRuns > 0) payload.max_runs = maxRuns;
        }
        if (loopConfig) {
            payload.context = {
                ...(payload.context || {}),
                ...loopConfig,
            };
        }

        await NexusAPI.createSchedule(payload);
        const schedLabel = triggerMode === 'cron' ? `Schedule "${name}"` : `One-time schedule "${name}"`;
        this.showToast(`${schedLabel} created`, 'success');

        // Refresh schedule panel if visible
        const panel = document.getElementById('schedulePanel-global');
        if (panel && panel.style.display !== 'none') {
            this.taskView.loadSchedules('global');
        }
    }

    showDeleteModal(type, id, callback) {
        const modal = document.getElementById('deleteModal');
        const message = document.getElementById('deleteModalMessage');
        
        if (!modal || !message) return;

        message.textContent = type === 'session' 
            ? 'Are you sure you want to delete this session? This action cannot be undone.'
            : 'Are you sure you want to delete this task? This action cannot be undone.';

        this.deleteCallback = callback;
        modal.classList.add('open');
    }

    showRenameTabModal(paneId, tabId) {
        const modal = document.getElementById('renameTabModal');
        const input = document.getElementById('renameTabInput');
        
        if (!modal || !input) return;

        const tab = this.tabManager.panes[paneId]?.tabs.find(t => t.id === tabId);
        if (tab) {
            input.value = tab.title;
        }

        this.renameTabCallback = (newTitle) => {
            this.tabManager.renameTab(paneId, tabId, newTitle);
        };

        modal.classList.add('open');
        input.focus();
        input.select();
    }

    showNewSessionModal(paneId) {
        const modal = document.getElementById('newSessionModal');
        if (!modal) {
            // Create modal if it doesn't exist
            this.createNewSessionModal();
        }
        
        const modalEl = document.getElementById('newSessionModal');
        if (modalEl) {
            // Reset form
            const titleInput = document.getElementById('newSessionTitle');
            if (titleInput) titleInput.value = '';
            
            this.newSessionPaneId = paneId;
            modalEl.classList.add('open');
            titleInput?.focus();
        }
    }

    createNewSessionModal() {
        const modal = document.createElement('div');
        modal.id = 'newSessionModal';
        modal.className = 'modal-backdrop';
        modal.innerHTML = `
            <div class="modal" style="max-width: 400px;">
                <div class="modal-header">
                    <h3 class="modal-title">New Session</h3>
                    <button class="modal-close" data-close-modal>
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                        </svg>
                    </button>
                </div>
                <div class="modal-body">
                    <div class="form-group">
                        <label class="form-label">Session Title</label>
                        <input id="newSessionTitle" type="text" class="form-input" placeholder="Enter session title (optional)">
                    </div>
                    <p style="font-size: 12px; color: var(--text-muted); margin-top: 8px;">
                        Note: New session will be created via API. This feature may not be available if your system doesn't support session creation.
                    </p>
                </div>
                <div class="modal-footer">
                    <button class="action-btn" data-close-modal>Cancel</button>
                    <button id="confirmNewSessionBtn" class="action-btn primary">Create</button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        // Bind events
        modal.querySelectorAll('[data-close-modal]').forEach(btn => {
            btn.addEventListener('click', () => modal.classList.remove('open'));
        });

        modal.querySelector('#confirmNewSessionBtn').addEventListener('click', async () => {
            const title = document.getElementById('newSessionTitle')?.value.trim();
            await this.createNewSession(this.newSessionPaneId, title);
            modal.classList.remove('open');
        });

        // Enter key to submit
        modal.querySelector('#newSessionTitle').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                modal.querySelector('#confirmNewSessionBtn').click();
            }
        });
    }

    async createNewSession(paneId, title) {
        try {
            // Try to create a new session via API
            const globalUserFilter = document.getElementById('globalUserFilter');
            const result = await NexusAPI.createSession({
                title: title || `New Session ${new Date().toLocaleTimeString()}`,
                username: globalUserFilter?.value || NexusAPI.getDefaultExecUser()
            });
            
            this.showToast('Session created successfully', 'success');
            
            // Reload sessions
            this.chatView.loadSessions(paneId);
        } catch (error) {
            console.error('Failed to create session:', error);
            this.showToast('Failed to create session: ' + (error.message || 'Unknown error'), 'error');
        }
    }

    showToast(message, type = 'info') {
        const container = document.getElementById('toastContainer');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `
            <svg class="toast-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                ${type === 'success' 
                    ? '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>'
                    : type === 'error'
                    ? '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>'
                    : '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>'}
            </svg>
            <span class="toast-message">${message}</span>
            <button class="toast-close">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="14" height="14">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>
            </button>
        `;

        toast.querySelector('.toast-close').addEventListener('click', () => {
            toast.remove();
        });

        container.appendChild(toast);

        // Auto remove after 5 seconds
        setTimeout(() => {
            toast.style.animation = 'fadeOut 0.3s forwards';
            setTimeout(() => toast.remove(), 300);
        }, 5000);
    }

    showAddTabDropdown(btn, paneId) {
        // Simplified: directly add a new chat tab without showing dropdown
        this.tabManager.addTab(paneId, 'chat');
    }

    positionDropdown(dropdown, anchorEl) {
        const rect = anchorEl.getBoundingClientRect();
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;

        // First, set position fixed and make visible to get accurate dimensions
        dropdown.style.cssText = `
            position: fixed;
            visibility: hidden;
            z-index: 1000;
        `;

        // Use requestAnimationFrame to ensure the dropdown is rendered
        requestAnimationFrame(() => {
            const dropdownRect = dropdown.getBoundingClientRect();

            // Calculate position - align dropdown right edge with button right edge
            let top = rect.bottom + 4;
            let left = rect.right - dropdownRect.width;

            // Adjust if dropdown goes off the left edge
            if (left < 8) {
                left = 8;
            }

            // Adjust if dropdown goes off the right edge
            if (left + dropdownRect.width > viewportWidth - 8) {
                left = viewportWidth - dropdownRect.width - 8;
            }

            // Adjust if dropdown goes off the bottom edge
            if (top + dropdownRect.height > viewportHeight - 8) {
                top = rect.top - dropdownRect.height - 4;
            }

            dropdown.style.cssText = `
                position: fixed;
                top: ${top}px;
                left: ${left}px;
                z-index: 1000;
            `;
        });
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', async () => {
    // Check authentication status first
    try {
        const authStatus = await NexusAPI.getAuthStatus();
        
        if (authStatus.auth_required && !authStatus.authenticated) {
            // Show login overlay
            showLoginOverlay();
            setupLoginHandlers();
        } else {
            // Show main app
            showMainApp(authStatus.auth_required);
        }
    } catch (error) {
        console.error('Failed to check auth status:', error);
        // On error, try to show main app anyway
        showMainApp(false);
    }
});

function showLoginOverlay() {
    const loginOverlay = document.getElementById('loginOverlay');
    const mainApp = document.getElementById('app');
    if (loginOverlay) loginOverlay.style.display = 'flex';
    if (mainApp) mainApp.style.display = 'none';
}

function showMainApp(authRequired) {
    const loginOverlay = document.getElementById('loginOverlay');
    const mainApp = document.getElementById('app');
    const logoutBtn = document.getElementById('logoutBtn');
    
    if (loginOverlay) loginOverlay.style.display = 'none';
    if (mainApp) mainApp.style.display = '';
    if (logoutBtn) logoutBtn.style.display = authRequired ? '' : 'none';
    
    // Initialize main app
    window.app = new NexusApp();
    window.nexusApp = window.app;
    
    // Setup logout handler
    if (logoutBtn) {
        logoutBtn.addEventListener('click', async () => {
            try {
                await NexusAPI.logout();
                window.location.reload();
            } catch (error) {
                console.error('Logout failed:', error);
            }
        });
    }
}

function setupLoginHandlers() {
    const loginForm = document.getElementById('loginForm');
    const loginPassword = document.getElementById('loginPassword');
    const loginError = document.getElementById('loginError');
    const loginBtn = document.getElementById('loginBtn');
    
    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const password = loginPassword?.value || '';
            if (!password) {
                if (loginError) {
                    loginError.textContent = 'Please enter a password';
                    loginError.style.display = 'block';
                }
                return;
            }
            
            // Disable button during login
            if (loginBtn) {
                loginBtn.disabled = true;
                loginBtn.innerHTML = '<span>Logging in...</span>';
            }
            
            try {
                await NexusAPI.login(password);
                // Login successful, reload to show main app
                window.location.reload();
            } catch (error) {
                if (loginError) {
                    loginError.textContent = error.message || 'Login failed';
                    loginError.style.display = 'block';
                }
                if (loginBtn) {
                    loginBtn.disabled = false;
                    loginBtn.innerHTML = '<span>Login</span>';
                }
            }
        });
    }
    
    // Focus password input
    if (loginPassword) {
        loginPassword.focus();
    }
}
