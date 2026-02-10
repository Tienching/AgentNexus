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
// Page Manager - Handles Project/Config page switching
// ============================================================
class PageManager {
    constructor(app) {
        this.app = app;
        this.currentPage = localStorage.getItem('nexus-page') || 'project';
        this.projectView = document.getElementById('projectView');
        this.configView = document.getElementById('configView');
        this.projectHeaderCenter = document.getElementById('projectHeaderCenter');
        this.projectHeaderRight = document.getElementById('projectHeaderRight');
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
        this.currentPage = page;
        localStorage.setItem('nexus-page', page);
        this.apply();
        
        // Refresh config view when switching to config page
        if (page === 'config' && this.app.configView) {
            this.app.configView.refresh();
        }

        // Refresh project selectors when switching back to project page
        if (page === 'project' && this.app.refreshProjectProviders) {
            this.app.refreshProjectProviders();
        }
    }

    apply() {
        // Update nav button states
        document.querySelectorAll('.page-nav-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.page === this.currentPage);
        });

        // Show/hide page views
        if (this.projectView) {
            this.projectView.classList.toggle('active', this.currentPage === 'project');
        }
        if (this.configView) {
            this.configView.classList.toggle('active', this.currentPage === 'config');
        }

        // Show/hide project-specific header elements
        if (this.projectHeaderCenter) {
            this.projectHeaderCenter.style.display = this.currentPage === 'project' ? '' : 'none';
        }
        if (this.projectHeaderRight) {
            this.projectHeaderRight.style.display = this.currentPage === 'project' ? '' : 'none';
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

        // View switcher buttons
        document.addEventListener('click', (e) => {
            const btn = e.target.closest('.view-btn');
            if (btn) {
                const switcher = btn.closest('.view-switcher');
                const paneId = parseInt(switcher.dataset.pane);
                const viewType = btn.dataset.view;
                this.switchView(paneId, viewType);
                
                // Update button states
                switcher.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            }
        });
    }

    switchView(paneId, viewType) {
        const pane = this.panes[paneId];
        if (!pane || !pane.activeTabId) return;

        // Switch the current active tab's type (not create new tab)
        const tab = pane.tabs.find(t => t.id === pane.activeTabId);
        if (tab && tab.type !== viewType) {
            tab.type = viewType;
            tab.title = viewType === 'chat' ? 'Chat' : 'Task';
            tab.data = {}; // Reset data when switching type
            this.renderTabs(paneId);
            this.renderContent(paneId);
        }
    }

    updateViewSwitcher(paneId) {
        const pane = this.panes[paneId];
        const switcher = document.querySelector(`.view-switcher[data-pane="${paneId}"]`);
        if (!pane || !switcher) return;

        const activeTab = pane.tabs.find(t => t.id === pane.activeTabId);
        if (activeTab) {
            switcher.querySelectorAll('.view-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.view === activeTab.type);
            });
        }
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
        this.updateViewSwitcher(paneId);
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
        this.updateViewSwitcher(paneId);
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

    switchTabType(paneId, tabId, newType) {
        const pane = this.panes[paneId];
        if (!pane) return;

        const tab = pane.tabs.find(t => t.id === tabId);
        if (tab && tab.type !== newType) {
            tab.type = newType;
            tab.title = newType === 'chat' ? 'Chat' : 'Task';
            tab.data = {};
            this.renderTabs(paneId);
            this.renderContent(paneId);
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
                    ${tab.type === 'chat' 
                        ? '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>'
                        : '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>'}
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

        if (tab.type === 'chat') {
            this.app.chatView.render(paneId, tab, container);
        } else {
            this.app.taskView.render(paneId, tab, container);
        }
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
    }

    async render(paneId, tab, container) {
        // Initialize selection state for this pane
        if (!this.selectionMode[paneId]) {
            this.selectionMode[paneId] = false;
        }
        if (!this.selectedSessionIds[paneId]) {
            this.selectedSessionIds[paneId] = new Set();
        }

        if (tab?.id && this.currentSessionByTab[tab.id] === undefined) {
            this.currentSessionByTab[tab.id] = tab.data?.sessionId || null;
        }

        container.innerHTML = `
            <div class="chat-container">
                <div class="session-list" id="sessionList-${paneId}">
                    <div class="session-list-header">
                        <div class="session-header-row">
                            <span class="session-header-title">Sessions</span>
                            <div class="session-header-actions">
                                <button class="action-btn primary" data-action="new-session" data-pane="${paneId}">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                                    </svg>
                                    <span>New Chat</span>
                                </button>
                                <button class="action-btn" data-action="toggle-session-selection" data-pane="${paneId}" title="Batch select">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>
                                    </svg>
                                    <span>Select</span>
                                </button>
                            </div>
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
                        <div class="session-search">
                            <svg class="session-search-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                            </svg>
                            <input type="text" class="session-search-input" placeholder="Search sessions..." data-pane="${paneId}">
                        </div>
                        <div class="session-filter">
                            <select class="session-filter-select" data-pane="${paneId}" data-filter="status">
                                <option value="">All Status</option>
                                <option value="running">Running</option>
                                <option value="completed">Completed</option>
                                <option value="error">Error</option>
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
        if (activeSessionId) {
            await this.selectSession(paneId, activeSessionId, { silent: true });
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
        const searchInput = document.querySelector(`.session-search-input[data-pane="${paneId}"]`);
        if (searchInput) {
            let timeout;
            searchInput.addEventListener('input', () => {
                clearTimeout(timeout);
                timeout = setTimeout(() => this.loadSessions(paneId), 300);
            });
        }

        const statusFilter = document.querySelector(`.session-filter-select[data-pane="${paneId}"]`);
        if (statusFilter) {
            statusFilter.addEventListener('change', () => this.loadSessions(paneId));
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
        return sessions.find(session => session.id === sessionId) || null;
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
        const fallback = { username: 'ubuntu', agentType: 'claude', label: 'ubuntu / claude' };
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
        const username = parts[0] || 'ubuntu';
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
        const usernames = rawUsernames.length ? rawUsernames : ['ubuntu'];
        const initialUser = (selectedUser && usernames.includes(selectedUser))
            ? selectedUser
            : (usernames.includes('ubuntu') ? 'ubuntu' : (usernames[0] || 'ubuntu'));

        const buildModelOptions = (user) => {
            const agents = this.getAvailableAgents(user);
            const agentModels = [...new Set(agents.map(agent => agent.agent_type))];
            // Merge with custom providers (use getCustomProviderNames for new format)
            const customProviderNames = this.app.getCustomProviderNames ? this.app.getCustomProviderNames() : [];
            const defaultProviders = this.app.getDefaultProviders ? this.app.getDefaultProviders() : ['claude', 'gemini', 'codex', 'codebuddy'];
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
                    const selectedUser = userSelect?.value || initialUser || 'ubuntu';
                    const selectedModel = modelSelect?.value || this.app.getDefaultProvider();
                    this.createNewSession(paneId, textarea.value, selectedUser, selectedModel, selectedModel);
                }
            });
        }

        if (sendBtn) {
            sendBtn.addEventListener('click', () => {
                const selectedUser = userSelect?.value || initialUser || 'ubuntu';
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
        const usernames = rawUsernames.length ? rawUsernames : ['ubuntu'];
        const fallbackUser = (selectedUser && usernames.includes(selectedUser))
            ? selectedUser
            : (usernames.includes('ubuntu') ? 'ubuntu' : (usernames[0] || 'ubuntu'));

        const buildModelOptions = (user) => {
            const agents = this.getAvailableAgents(user);
            const agentModels = [...new Set(agents.map(agent => agent.agent_type))];
            const customProviderNames = this.app.getCustomProviderNames ? this.app.getCustomProviderNames() : [];
            const defaultProviders = this.app.getDefaultProviders ? this.app.getDefaultProviders() : ['claude', 'gemini', 'codex', 'codebuddy'];
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

    async createNewSession(paneId, message, execUser = 'ubuntu', agentType = 'claude', alias = null) {
        if (!message.trim()) {
            this.app.showToast('Please enter a message', 'warning');
            return;
        }

        const agentLabel = `${execUser} / ${agentType}`;

        const detail = document.getElementById(`chatDetail-${paneId}`);
        if (!detail) return;
        
        // Generate a unique session ID
        const sessionId = `chat_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
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
                        <div class="message-text">${this.escapeHtml(message)}</div>
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
                            <span class="thinking-text">Thinking...</span>
                        </div>
                    </div>
                </div>
            </div>
            <div class="chat-input-container">
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
            await this.streamChatResponse(paneId, execUser, payload, `thinking-${paneId}`);
            
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
            
            // Reload sessions list first, then load messages after a delay to ensure backend has saved them
            await this.loadSessions(paneId);
            setTimeout(() => {
                this.loadMessages(paneId, sessionId);
            }, 500);
            
        } catch (error) {
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
        const messagesContainer = document.getElementById(`chatMessages-${paneId}`);
        const thinkingEl = document.getElementById(thinkingId);
        
        // Replace thinking indicator with streaming response container
        // Start with an empty bubble - content will be added dynamically
        if (thinkingEl) {
            thinkingEl.innerHTML = `
                <div class="message-avatar assistant">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="18" height="18">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                    </svg>
                </div>
                <div class="message-content">
                    <div class="message-bubble streaming-bubble" id="streaming-bubble-${thinkingId}"></div>
                </div>
            `;
        }
        
        const bubbleEl = document.getElementById(`streaming-bubble-${thinkingId}`);
        let currentTextEl = null; // Will be created on demand when text arrives
        let currentTextContent = ''; // Current text segment content
        let textSegmentIndex = 0; // Track text segments for unique IDs
        
        // Helper function to ensure we have a text element to write to
        const ensureTextElement = () => {
            if (!currentTextEl && bubbleEl) {
                const textId = `streaming-content-${thinkingId}-seg${textSegmentIndex}`;
                bubbleEl.insertAdjacentHTML('beforeend', `<div class="message-text streaming" id="${textId}"></div>`);
                currentTextEl = document.getElementById(textId);
                currentTextContent = '';
            }
            return currentTextEl;
        };
        
        // Track streaming tool calls
        const streamingToolCalls = new Map(); // toolCallId -> { name, args, status }
        
        // Call streaming API
        const response = await NexusAPI.chatStream(execUser, payload);
        
        const reader = response.body?.getReader();
        const decoder = new TextDecoder();
        
        if (!reader) {
            throw new Error('No response body');
        }
        
        let buffer = '';
        
        try {
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                buffer += decoder.decode(value, { stream: true });
                
                // Process complete SSE events
                const events = buffer.split('\n\n');
                buffer = events.pop() || ''; // Keep incomplete event in buffer
                
                for (const event of events) {
                    if (!event.trim()) continue;
                    
                    // Parse legacy SSE format: event:delta\ndata:{"delta":"...","finished":false}
                    const lines = event.split('\n');
                    let eventType = '';
                    let eventData = '';
                    
                    for (const line of lines) {
                        if (line.startsWith('event:')) {
                            eventType = line.slice(6).trim();
                        } else if (line.startsWith('data:')) {
                            eventData = line.slice(5).trim();
                        } else if (line.startsWith('data: ')) {
                            eventData = line.slice(6).trim();
                        }
                    }
                    
                    if (!eventData) continue;
                    if (eventData === '[DONE]') continue;
                    
                    try {
                        const data = JSON.parse(eventData);
                        
                        // Handle legacy format with response field (event:delta, data.response)
                        if (eventType === 'delta' && data.response !== undefined) {
                            if (data.response) {
                                currentTextContent += data.response;
                                const textEl = ensureTextElement();
                                if (textEl) {
                                    textEl.innerHTML = this.formatMessageContent(currentTextContent);
                                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                                }
                            }
                            // Check if stream is finished
                            if (data.finished === true) {
                                // Stream completed, remove streaming indicator
                                if (currentTextEl) {
                                    currentTextEl.classList.remove('streaming');
                                }
                            }
                        }
                        // Handle legacy format (event:delta, data.delta)
                        else if (eventType === 'delta' && data.delta) {
                            currentTextContent += data.delta;
                            const textEl = ensureTextElement();
                            if (textEl) {
                                textEl.innerHTML = this.formatMessageContent(currentTextContent);
                                messagesContainer.scrollTop = messagesContainer.scrollHeight;
                            }
                        }
                        // Handle AGUI format - TEXT_MESSAGE_CONTENT
                        else if (data.type === 'TEXT_MESSAGE_CONTENT' && data.delta) {
                            currentTextContent += data.delta;
                            const textEl = ensureTextElement();
                            if (textEl) {
                                textEl.innerHTML = this.formatMessageContent(currentTextContent);
                                messagesContainer.scrollTop = messagesContainer.scrollHeight;
                            }
                        }
                        // Handle AGUI format - TOOL_CALL_START
                        else if (data.type === 'TOOL_CALL_START') {
                            const toolCallId = data.toolCallId || `tool-${Date.now()}`;
                            const toolName = data.toolCallName || 'Tool';
                            
                            // Initialize tool call state
                            streamingToolCalls.set(toolCallId, {
                                name: toolName,
                                args: '',
                                status: 'executing',
                                result: ''
                            });
                            
                            // Close current text element (if any) and prepare for new one after tool call
                            if (currentTextEl) {
                                currentTextEl.classList.remove('streaming');
                            }
                            currentTextEl = null; // Reset so next text creates a new element after the tool call
                            textSegmentIndex++;
                            
                            // Create tool call UI element in the bubble
                            if (bubbleEl) {
                                const toolCallHtml = this.renderStreamingToolCall(toolCallId, toolName, 'executing');
                                bubbleEl.insertAdjacentHTML('beforeend', toolCallHtml);
                                messagesContainer.scrollTop = messagesContainer.scrollHeight;
                            }
                        }
                        // Handle AGUI format - TOOL_CALL_ARGS
                        else if (data.type === 'TOOL_CALL_ARGS') {
                            const toolCallId = data.toolCallId;
                            const argsDelta = data.delta || '';
                            
                            if (toolCallId && streamingToolCalls.has(toolCallId)) {
                                const tc = streamingToolCalls.get(toolCallId);
                                tc.args += argsDelta;
                                
                                // Update the args display
                                const argsEl = document.getElementById(`streaming-tool-args-${toolCallId}`);
                                if (argsEl) {
                                    argsEl.textContent = tc.args;
                                }
                            }
                        }
                        // Handle AGUI format - TOOL_CALL_END
                        else if (data.type === 'TOOL_CALL_END') {
                            const toolCallId = data.toolCallId;
                            const result = data.result || '';
                            const error = data.error;
                            
                            if (toolCallId && streamingToolCalls.has(toolCallId)) {
                                const tc = streamingToolCalls.get(toolCallId);
                                tc.status = error ? 'failed' : 'completed';
                                tc.result = result;
                                tc.error = error;
                                
                                // Update status icon
                                const statusEl = document.querySelector(`[data-streaming-tool-id="${toolCallId}"] .tool-call-status-icon`);
                                if (statusEl) {
                                    statusEl.textContent = error ? '✗' : '✓';
                                    statusEl.parentElement.style.color = error ? 'var(--error)' : 'var(--success)';
                                }
                                
                                // Show result section
                                const resultSection = document.getElementById(`streaming-tool-result-section-${toolCallId}`);
                                const resultEl = document.getElementById(`streaming-tool-result-${toolCallId}`);
                                if (resultSection && resultEl && result) {
                                    resultSection.style.display = 'block';
                                    resultEl.textContent = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
                                }
                                
                                // Show error if any
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
                        }
                        // Handle AGUI format - TOOL_CALL_RESULT (alternative format)
                        else if (data.type === 'TOOL_CALL_RESULT') {
                            const toolCallId = data.toolCallId;
                            const result = data.result || '';
                            
                            if (toolCallId && streamingToolCalls.has(toolCallId)) {
                                const tc = streamingToolCalls.get(toolCallId);
                                tc.result = result;
                                
                                // Show result section
                                const resultSection = document.getElementById(`streaming-tool-result-section-${toolCallId}`);
                                const resultEl = document.getElementById(`streaming-tool-result-${toolCallId}`);
                                if (resultSection && resultEl && result) {
                                    resultSection.style.display = 'block';
                                    resultEl.textContent = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
                                }
                            }
                        }
                        // Handle generic delta
                        else if (data.delta && !data.type) {
                            currentTextContent += data.delta;
                            const textEl = ensureTextElement();
                            if (textEl) {
                                textEl.innerHTML = this.formatMessageContent(currentTextContent);
                                messagesContainer.scrollTop = messagesContainer.scrollHeight;
                            }
                        }
                        // Handle errors
                        else if (data.type === 'RUN_ERROR' || data.error) {
                            throw new Error(data.message || data.error || 'Stream error');
                        }
                    } catch (e) {
                        if (e.message && (e.message.includes('Stream error') || e.message.includes('RUN_ERROR'))) {
                            throw e;
                        }
                        // Skip invalid JSON
                    }
                }
            }
        } finally {
            reader.releaseLock();
        }
        
        // Remove streaming class when done
        if (currentTextEl) {
            currentTextEl.classList.remove('streaming');
        }
        
        // Remove empty text segments
        if (bubbleEl) {
            bubbleEl.querySelectorAll('.message-text:empty').forEach(el => el.remove());
        }
        
        // Re-enable input
        const textarea = document.getElementById(`chatInput-${paneId}`);
        const sendBtn = document.querySelector(`.chat-send-btn[data-pane="${paneId}"]`);
        if (textarea) textarea.disabled = false;
        if (sendBtn) sendBtn.disabled = false;
    }
    
    /**
     * Render a streaming tool call UI element (simplified version for real-time display)
     */
    renderStreamingToolCall(toolCallId, toolName, status = 'executing') {
        const statusConfig = {
            pending: { icon: '⏳', color: 'var(--text-muted)' },
            executing: { icon: '▶️', color: 'var(--primary-500)' },
            completed: { icon: '✓', color: 'var(--success)' },
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

        const searchInput = document.querySelector(`.session-search-input[data-pane="${paneId}"]`);
        const statusFilter = document.querySelector(`.session-filter-select[data-pane="${paneId}"]`);
        const globalUserFilter = document.getElementById('globalUserFilter');

        try {
            const options = {
                pageSize: 50,
                search: searchInput?.value || '',
                status: statusFilter?.value || '',
                username: globalUserFilter?.value || ''
            };

            const data = await NexusAPI.getSessions(options);
            this.sessions[paneId] = data.sessions || [];
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

    renderSessionItem(session, paneId) {
        const statusClass = session.status === 'running' ? 'running' :
                           session.status === 'error' ? 'error' : 'completed';
        const timeStr = this.formatTime(session.updated_at || session.created_at);
        const activeTabId = this.getActiveTabId(paneId);
        const isActive = activeTabId ? this.currentSessionByTab[activeTabId] === session.id : false;
        const isInSelectionMode = this.selectionMode[paneId];
        const isChecked = this.selectedSessionIds[paneId]?.has(session.id);

        return `
            <div class="session-item ${isActive ? 'active' : ''} ${isChecked ? 'checked' : ''}" data-session-id="${session.id}">
                ${isInSelectionMode ? `
                    <div class="session-item-checkbox" data-session-id="${session.id}">
                        <input type="checkbox" ${isChecked ? 'checked' : ''}>
                    </div>
                ` : ''}
                <div class="session-item-content">
                    <div class="session-item-header">
                        <span class="session-item-title">${this.escapeHtml(session.title || session.id)}</span>
                        <span class="session-item-time">${timeStr}</span>
                    </div>
                    ${session.last_message ? `<p class="session-item-preview">${this.escapeHtml(session.last_message)}</p>` : ''}
                    <div class="session-item-meta">
                        <span class="session-item-status ${statusClass}">
                            <span class="status-dot"></span>
                            ${session.status || 'idle'}
                        </span>
                        ${session.username ? `<span>@${session.username}${session.provider ? ' / ' + session.provider : ''}</span>` : ''}
                    </div>
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

        // Load and display messages
        await this.loadMessages(paneId, sessionId);
    }

    async loadMessages(paneId, sessionId) {
        const detail = document.getElementById(`chatDetail-${paneId}`);
        if (!detail) return;

        detail.innerHTML = `
            <div class="empty-state">
                <div class="loading-spinner"></div>
            </div>
        `;

        try {
            const data = await NexusAPI.getSessionMessages(sessionId);
            this.renderMessages(paneId, sessionId, data);
        } catch (error) {
            console.error('Failed to load messages:', error);
            detail.innerHTML = `
                <div class="empty-state">
                    <p class="empty-state-text" style="color: var(--error)">Failed to load messages</p>
                </div>
            `;
        }
    }

    renderMessages(paneId, sessionId, data) {
        const detail = document.getElementById(`chatDetail-${paneId}`);
        if (!detail) return;

        const messages = data.messages || [];
        const toolCalls = data.tool_calls || [];

        detail.innerHTML = `
            <div class="chat-header">
                <div class="chat-header-info">
                    <h2 class="chat-header-title">${this.escapeHtml(data.session?.title || sessionId)}</h2>
                    <span class="chat-header-meta">${messages.length} messages</span>
                </div>
                <div class="chat-header-actions">
                    <button class="action-btn" data-action="show-files" data-session-id="${sessionId}" title="Files">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="16" height="16">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
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
        `;

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

    async sendMessage(paneId, sessionId, message) {
        if (!message.trim()) return;

        const textarea = document.getElementById(`chatInput-${paneId}`);
        const sendBtn = document.querySelector(`.chat-send-btn[data-pane="${paneId}"]`);
        const messagesContainer = document.getElementById(`chatMessages-${paneId}`);
        
        if (!messagesContainer) return;

        // Clear input and disable
        if (textarea) {
            textarea.value = '';
            textarea.style.height = 'auto';
            textarea.disabled = true;
        }
        if (sendBtn) sendBtn.disabled = true;

        // Add user message to UI immediately
        const userMsgHtml = `
            <div class="message user">
                <div class="message-avatar user">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="18" height="18">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
                    </svg>
                </div>
                <div class="message-content">
                    <div class="message-text">${this.escapeHtml(message)}</div>
                </div>
            </div>
        `;
        
        // Remove empty state if present
        const emptyState = messagesContainer.querySelector('.empty-state');
        if (emptyState) emptyState.remove();
        
        messagesContainer.insertAdjacentHTML('beforeend', userMsgHtml);

        // Add thinking indicator
        const thinkingId = `thinking-${Date.now()}`;
        const thinkingHtml = `
            <div class="message assistant" id="${thinkingId}">
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
                        <span class="thinking-text">Thinking...</span>
                    </div>
                </div>
            </div>
        `;
        messagesContainer.insertAdjacentHTML('beforeend', thinkingHtml);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;

        try {
            // Send message via streaming API
            await this.streamMessage(paneId, sessionId, message, thinkingId);
            
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
        const execUser = sessionMeta?.username || globalUserFilter?.value || 'ubuntu';
        const provider = sessionMeta?.provider || '';
        
        // Build legacy (易事厅) request payload with session_id to continue conversation
        const payload = {
            content: message,
            user: execUser,
            session_id: sessionId,
            msg_type: 'text',
            provider: provider || undefined
        };
        
        // Use the shared streaming method
        await this.streamChatResponse(paneId, execUser, payload, thinkingId);
        
        // Refresh session list to update last_message
        this.loadSessions(paneId);
    }

    renderMessage(msg, toolCalls) {
        const isUser = msg.role === 'user';
        const avatar = isUser ? 'U' : 'A';
        const timeStr = this.formatTime(msg.timestamp);
        const hasContent = msg.content && msg.content.trim();

        // Find tool calls for this message
        const messageToolCallIds = new Set([
            ...(msg.tool_call_ids || []),
            ...((msg.content_segments || [])
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
        if (msg.content_segments && msg.content_segments.length > 0) {
            // Sort segments by sequence number
            const sortedSegments = [...msg.content_segments].sort((a, b) => (a.sequence || 0) - (b.sequence || 0));
            
            for (const segment of sortedSegments) {
                if (segment.type === 'text' && segment.content) {
                    bubbleContent += this.formatMessageContent(segment.content);
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
                bubbleContent += this.formatMessageContent(msg.content);
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
        const statusConfig = {
            pending: { icon: '⏳', color: 'var(--text-muted)', bgColor: 'rgba(148, 163, 184, 0.1)', label: 'Pending' },
            executing: { icon: '▶️', color: 'var(--primary-500)', bgColor: 'rgba(59, 130, 246, 0.1)', label: 'Executing' },
            completed: { icon: '✓', color: 'var(--success)', bgColor: 'rgba(16, 185, 129, 0.1)', label: 'Completed' },
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
                        <span class="tool-call-standalone-name">${this.escapeHtml(tc.tool_name || tc.name || 'Tool Call')}</span>
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
                    <span class="tool-call-name">${this.escapeHtml(tc.tool_name || tc.name || 'Tool Call')}</span>
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
        if (!content) return '';
        // Basic markdown-like formatting
        return this.escapeHtml(content)
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/`([^`]+)`/g, '<code style="background: var(--bg-tertiary); padding: 2px 4px; border-radius: 4px;">$1</code>')
            .replace(/\n/g, '<br>');
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

        // Show confirmation modal
        this.app.showDeleteModal('sessions', `${sessionIds.length} session(s)`, async () => {
            try {
                const result = await NexusAPI.bulkDeleteSessions(sessionIds);

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
        const execUser = document.getElementById('globalUserFilter')?.value || 'ubuntu';

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
            { key: 'todo', title: 'To Do', color: 'var(--status-todo)' },
            { key: 'doing', title: 'Doing', color: 'var(--status-doing)' },
            { key: 'done', title: 'Done', color: 'var(--status-done)' },
            { key: 'failed', title: 'Failed', color: 'var(--status-failed)' },
            { key: 'cancelled', title: 'Cancelled', color: 'var(--status-cancelled)' },
            { key: 'archived', title: 'Archived', color: 'var(--status-archived)' },
        ];
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
                </div>
                <div class="task-detail hidden" id="taskDetail-${paneId}">
                    <!-- Task detail will be rendered here -->
                </div>
            </div>
        `;

        this.bindEvents(paneId);
        await this.loadTasks(paneId);
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
                execUser: globalUserFilter?.value || 'ubuntu'
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
                execUser: globalUserFilter?.value || 'ubuntu',
                pageSize: 100,
                search: searchInput?.value || '',
                projectId: projectFilter?.value || ''
            };

            const data = await NexusAPI.getTasks(options);
            this.tasks[paneId] = data.tasks || [];
            this.renderKanban(paneId);
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

    renderKanban(paneId) {
        const tasks = this.tasks[paneId] || [];
        
        // Group tasks by status
        const grouped = {};
        this.statusColumns.forEach(col => {
            grouped[col.key] = [];
        });

        tasks.forEach(task => {
            const status = (task.status || 'todo').toLowerCase();
            if (grouped[status]) {
                grouped[status].push(task);
            } else {
                grouped['todo'].push(task);
            }
        });

        // Render each column
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
    }

    renderTaskCard(task, paneId) {
        const priorityClass = task.priority === 'critical' ? 'critical' :
                             task.priority === 'serious' ? 'serious' : 'normal';
        const timeStr = this.formatTime(task.updated_at || task.created_at);
        const isSelected = this.selectedTask[paneId] === task.id;
        const isInSelectionMode = this.selectionMode[paneId];
        const isChecked = this.selectedTaskIds[paneId]?.has(task.id);

        return `
            <div class="task-card ${isSelected ? 'selected' : ''} ${isChecked ? 'checked' : ''}" data-task-id="${task.id}">
                ${isInSelectionMode ? `
                    <div class="task-card-checkbox" data-task-id="${task.id}">
                        <input type="checkbox" ${isChecked ? 'checked' : ''}>
                    </div>
                ` : ''}
                <div class="task-card-content">
                    <div class="task-card-header">
                        <span class="task-card-id">#${task.id.slice(0, 8)}</span>
                        ${task.priority ? `<span class="task-card-priority ${priorityClass}">${task.priority}</span>` : ''}
                    </div>
                    <p class="task-card-title">${this.escapeHtml(task.description || 'No description')}</p>
                    <div class="task-card-meta">
                        <span class="task-card-meta-item">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                            </svg>
                            ${timeStr}
                        </span>
                        ${task.provider ? `
                            <span class="task-card-meta-item">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                                </svg>
                                ${task.provider}
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
                execUser: globalUserFilter?.value || 'ubuntu' 
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

        const statusClass = task.status?.toLowerCase() || 'todo';

        detailPanel.innerHTML = `
            <div class="task-detail-header">
                <span class="task-detail-title">#${task.id.slice(0, 8)}</span>
                <button class="task-detail-close" data-action="close-detail">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>
            <div class="task-detail-content">
                <div class="task-detail-section">
                    <div class="task-detail-section-title">Status</div>
                    <div class="task-detail-section-content">
                        <span class="status-badge ${statusClass}">
                            <span class="status-dot"></span>
                            ${task.status || 'TODO'}
                        </span>
                    </div>
                </div>

                <div class="task-detail-section">
                    <div class="task-detail-section-title">Description</div>
                    <div class="task-detail-section-content">${this.escapeHtml(task.description || 'No description')}</div>
                </div>

                ${task.workspace ? `
                    <div class="task-detail-section">
                        <div class="task-detail-section-title">Workspace</div>
                        <div class="task-detail-section-content" style="font-family: var(--font-mono); font-size: 12px;">${this.escapeHtml(task.workspace)}</div>
                    </div>
                ` : ''}

                ${task.provider ? `
                    <div class="task-detail-section">
                        <div class="task-detail-section-title">Provider</div>
                        <div class="task-detail-section-content">${this.escapeHtml(task.provider)}</div>
                    </div>
                ` : ''}

                ${task.depends_on && task.depends_on.length > 0 ? `
                    <div class="task-detail-section">
                        <div class="task-detail-section-title">Dependencies</div>
                        <div class="task-detail-section-content">
                            ${task.depends_on.map(dep => `<span class="task-card-dep" style="margin-right: 4px;">${dep}</span>`).join('')}
                        </div>
                    </div>
                ` : ''}

                ${task.error_message ? `
                    <div class="task-detail-section">
                        <div class="task-detail-section-title">Error</div>
                        <div class="task-detail-section-content" style="color: var(--error);">${this.escapeHtml(task.error_message)}</div>
                    </div>
                ` : ''}

                <div class="task-detail-section">
                    <div class="task-detail-section-title">Actions</div>
                    <div style="display: flex; gap: 8px; flex-wrap: wrap;">
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
                detailPanel.classList.add('hidden');
                this.selectedTask[paneId] = null;
                
                // Clear selection
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
    }

    async deleteTask(paneId, taskId) {
        try {
            const globalUserFilter = document.getElementById('globalUserFilter');
            await NexusAPI.deleteTask(taskId, { 
                execUser: globalUserFilter?.value || 'ubuntu' 
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
                    execUser: globalUserFilter?.value || 'ubuntu'
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

        // Parameters tab events
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
                this.app.refreshProjectProviders?.();
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
        
        if (!nameInput || !baseSelect) return;

        const name = nameInput.value.trim();
        const base = baseSelect.value;

        if (!name) {
            this.app.showToast('Please enter an alias name', 'error');
            return;
        }

        if (this.app.addCustomProvider(name, base)) {
            this.app.showToast(`Alias "${name}" added`, 'success');
            nameInput.value = '';
            this.renderParameters();
            this.app.refreshProjectProviders?.();
        } else {
            this.app.showToast('Alias already exists or is invalid', 'error');
        }
    }

    deleteAlias(name) {
        if (this.app.removeCustomProvider(name)) {
            this.app.showToast(`Alias "${name}" removed`, 'success');
            this.renderParameters();
            this.app.refreshProjectProviders?.();
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
    // Skills Tab
    // ============================================================
    bindSkillsEvents() {
        // Add global skill button
        const addGlobalSkillBtn = document.getElementById('addGlobalSkillBtn');
        if (addGlobalSkillBtn) {
            addGlobalSkillBtn.addEventListener('click', () => this.addGlobalSkill());
        }

        // Add skill on Enter key
        const globalSkillName = document.getElementById('globalSkillName');
        if (globalSkillName) {
            globalSkillName.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') this.addGlobalSkill();
            });
        }
    }

    renderSkills() {
        const skillsConfig = this.app.loadSkillsConfig();
        
        // Render global skills list
        this.renderSkillsList('globalSkillsList', skillsConfig.global, null);
        
        // Render provider panels
        this.renderProviderSkillsPanels(skillsConfig.providers);
    }

    renderSkillsList(containerId, skills, provider) {
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!skills || skills.length === 0) {
            container.innerHTML = '<div class="skills-empty">No skills configured</div>';
            return;
        }

        container.innerHTML = skills.map((skill, index) => `
            <div class="skill-item" data-index="${index}" data-provider="${provider || 'global'}">
                <span>${skill}</span>
                <button class="skill-item-delete" title="Remove skill">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>
        `).join('');

        // Bind delete buttons
        container.querySelectorAll('.skill-item-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const item = e.target.closest('.skill-item');
                const index = parseInt(item?.dataset.index);
                const prov = item?.dataset.provider;
                if (!isNaN(index)) {
                    this.deleteSkill(prov === 'global' ? null : prov, index);
                }
            });
        });
    }

    renderProviderSkillsPanels(providersSkills) {
        const container = document.getElementById('providerSkillsPanels');
        if (!container) return;

        const providers = this.app.getDefaultProviders();
        
        container.innerHTML = providers.map(provider => {
            const skillsList = providersSkills[provider] || [];
            return `
                <div class="provider-panel" data-provider="${provider}">
                    <div class="provider-panel-header">
                        <div class="provider-panel-title">
                            ${provider}
                            <span class="provider-panel-count">${skillsList.length}</span>
                        </div>
                        <svg class="provider-panel-toggle" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </div>
                    <div class="provider-panel-body">
                        <div class="skill-form">
                            <input type="text" class="form-input provider-skill-name" placeholder="Skill name">
                            <button class="action-btn primary provider-skill-add">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:16px;height:16px;">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                                </svg>
                                Add
                            </button>
                        </div>
                        <div class="skills-list" id="providerSkillsList-${provider}">
                            ${this.renderProviderSkillsItems(skillsList, provider)}
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
        container.querySelectorAll('.provider-skill-add').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const panel = e.target.closest('.provider-panel');
                const provider = panel?.dataset.provider;
                if (provider) {
                    this.addProviderSkill(provider, panel);
                }
            });
        });

        // Bind delete buttons
        container.querySelectorAll('.skill-item-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const item = e.target.closest('.skill-item');
                const index = parseInt(item?.dataset.index);
                const prov = item?.dataset.provider;
                if (!isNaN(index) && prov) {
                    this.deleteSkill(prov, index);
                }
            });
        });
    }

    renderProviderSkillsItems(skillsList, provider) {
        if (!skillsList || skillsList.length === 0) {
            return '<div class="skills-empty">No skills for this provider</div>';
        }

        return skillsList.map((skill, index) => `
            <div class="skill-item" data-index="${index}" data-provider="${provider}">
                <span>${skill}</span>
                <button class="skill-item-delete" title="Remove skill">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>
        `).join('');
    }

    addGlobalSkill() {
        const nameInput = document.getElementById('globalSkillName');
        if (!nameInput) return;

        const name = nameInput.value.trim();
        if (!name) {
            this.app.showToast('Please enter a skill name', 'error');
            return;
        }

        const config = this.app.loadSkillsConfig();
        if (config.global.includes(name)) {
            this.app.showToast('Skill already exists', 'error');
            return;
        }

        config.global.push(name);
        this.app.saveSkillsConfig(config);

        nameInput.value = '';
        this.app.showToast(`Skill "${name}" added`, 'success');
        this.renderSkills();
    }

    addProviderSkill(provider, panel) {
        const nameInput = panel.querySelector('.provider-skill-name');
        if (!nameInput) return;

        const name = nameInput.value.trim();
        if (!name) {
            this.app.showToast('Please enter a skill name', 'error');
            return;
        }

        const config = this.app.loadSkillsConfig();
        if (!config.providers[provider]) {
            config.providers[provider] = [];
        }
        if (config.providers[provider].includes(name)) {
            this.app.showToast('Skill already exists for this provider', 'error');
            return;
        }

        config.providers[provider].push(name);
        this.app.saveSkillsConfig(config);

        nameInput.value = '';
        this.app.showToast(`Skill "${name}" added to ${provider}`, 'success');
        this.renderSkills();
    }

    deleteSkill(provider, index) {
        const config = this.app.loadSkillsConfig();
        
        if (provider === null) {
            // Global
            if (config.global[index]) {
                const name = config.global[index];
                config.global.splice(index, 1);
                this.app.saveSkillsConfig(config);
                this.app.showToast(`Skill "${name}" removed`, 'success');
                this.renderSkills();
            }
        } else {
            // Provider specific
            if (config.providers[provider] && config.providers[provider][index]) {
                const name = config.providers[provider][index];
                config.providers[provider].splice(index, 1);
                this.app.saveSkillsConfig(config);
                this.app.showToast(`Skill "${name}" removed from ${provider}`, 'success');
                this.renderSkills();
            }
        }
    }
}

// ============================================================
// Main Application
// ============================================================
class NexusApp {
    constructor() {
        this.themeManager = new ThemeManager();
        this.chatView = new ChatView(this);
        this.taskView = new TaskView(this);
        this.tabManager = new TabManager(this);
        this.layoutManager = new LayoutManager(this);
        this.configView = new ConfigView(this);
        this.pageManager = new PageManager(this);
        this.availableAgents = [];
        this.customProviders = this.loadCustomProviders();

        this.deleteCallback = null;
        this.renameTabCallback = null;
        this.activeModalTab = 'single';

        this.init();
    }

    // ============================================================
    // Custom Providers Management (localStorage persistence)
    // Storage format: [{name: string, baseProvider: string}, ...]
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
                        // Old format: convert string to object with default baseProvider
                        return { name: item, baseProvider: 'claude' };
                    }
                    // New format: already an object
                    return item;
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

    addCustomProvider(name, baseProvider = 'claude') {
        if (!name || typeof name !== 'string') return false;
        const trimmed = name.trim();
        if (!trimmed) return false;

        // Default providers that shouldn't be duplicated
        const defaultProviders = ['claude', 'gemini', 'codex', 'codebuddy'];
        
        // Check if already exists in defaults or custom list
        if (defaultProviders.includes(trimmed.toLowerCase()) || 
            this.customProviders.some(p => p.name.toLowerCase() === trimmed.toLowerCase())) {
            return false;
        }

        this.customProviders.push({ name: trimmed, baseProvider: baseProvider });
        this.saveCustomProviders();
        return true;
    }

    // Check if a name is a custom alias (not a default provider)
    isCustomAlias(name) {
        if (!name) return false;
        const trimmed = name.trim().toLowerCase();
        return this.customProviders.some(p => p.name.toLowerCase() === trimmed);
    }

    // Get all custom provider names (for dropdown options)
    getCustomProviderNames() {
        return this.customProviders.map(p => p.name);
    }

    // Get base provider for an alias
    getBaseProvider(aliasName) {
        if (!aliasName) return null;
        const trimmed = aliasName.trim().toLowerCase();
        const found = this.customProviders.find(p => p.name.toLowerCase() === trimmed);
        return found ? found.baseProvider : null;
    }

    // Remove a custom provider alias
    removeCustomProvider(name) {
        if (!name || typeof name !== 'string') return false;
        const trimmed = name.trim().toLowerCase();
        
        // Can't remove default providers
        const defaultProviders = ['claude', 'gemini', 'codex', 'codebuddy'];
        if (defaultProviders.includes(trimmed)) {
            return false;
        }
        
        const index = this.customProviders.findIndex(p => p.name.toLowerCase() === trimmed);
        if (index === -1) return false;
        
        this.customProviders.splice(index, 1);
        this.saveCustomProviders();
        return true;
    }

    getDefaultProviders() {
        return ['claude', 'gemini', 'codex', 'codebuddy'];
    }

    getAllProviders() {
        return [...this.getDefaultProviders(), ...this.getCustomProviderNames()];
    }

    // ============================================================
    // Default Provider Management
    // ============================================================
    getDefaultProvider() {
        return localStorage.getItem('nexus-default-provider') || 'claude';
    }

    setDefaultProvider(provider) {
        localStorage.setItem('nexus-default-provider', provider);
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
    // Skills Configuration Management
    // Storage format: { global: [...], providers: { claude: [...], ... } }
    // ============================================================
    loadSkillsConfig() {
        try {
            const stored = localStorage.getItem('nexus-skills-config');
            if (!stored) {
                return { global: [], providers: {} };
            }
            const parsed = JSON.parse(stored);
            return {
                global: Array.isArray(parsed.global) ? parsed.global : [],
                providers: parsed.providers || {}
            };
        } catch (e) {
            console.error('Failed to load skills config:', e);
            return { global: [], providers: {} };
        }
    }

    saveSkillsConfig(config) {
        try {
            localStorage.setItem('nexus-skills-config', JSON.stringify(config));
        } catch (e) {
            console.error('Failed to save skills config:', e);
        }
    }

    init() {
        // Initialize layout
        this.layoutManager.setMode(this.layoutManager.mode);

        // Load agents for filter
        this.loadAgents();

        // Bind global events
        this.bindEvents();
    }

    async loadAgents() {
        try {
            const data = await NexusAPI.getAgents();
            const agents = data.agents || [];
            this.availableAgents = agents.filter(agent => {
                const agentType = (agent.agent_type || '').toLowerCase();
                return !agentType.endsWith('-internal');
            });

            const select = document.getElementById('globalUserFilter');
            if (select) {
                const usernames = [...new Set(this.availableAgents.map(agent => agent.username))];
                select.innerHTML = '<option value="">All Users</option>' +
                    usernames.map(u => `<option value="${u}">${u}</option>`).join('');
            }
        } catch (error) {
            console.error('Failed to load agents:', error);
            this.availableAgents = [
                {
                    id: 'ubuntu::claude',
                    username: 'ubuntu',
                    agent_type: 'claude',
                    display_name: 'ubuntu / claude',
                    available: true
                }
            ];
            const select = document.getElementById('globalUserFilter');
            if (select) {
                select.innerHTML = '<option value="">All Users</option><option value="ubuntu">ubuntu</option>';
            }
        }
    }

    bindEvents() {
        // Theme toggle
        const themeToggle = document.getElementById('themeToggle');
        if (themeToggle) {
            themeToggle.addEventListener('click', () => this.themeManager.toggle());
        }

        // Refresh button
        const refreshBtn = document.getElementById('refreshBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.refresh());
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

        // Modal tab switching
        document.querySelectorAll('.modal-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                const tabId = tab.dataset.tab;
                this.activeModalTab = tabId;

                // Update tab states
                tab.closest('.modal-tabs').querySelectorAll('.modal-tab').forEach(t => {
                    t.classList.toggle('active', t.dataset.tab === tabId);
                });

                // Update content visibility
                tab.closest('.modal-body').querySelectorAll('.modal-tab-content').forEach(content => {
                    content.classList.toggle('active', content.dataset.tabContent === tabId);
                });
            });
        });

        // Submit task button
        const submitBtn = document.getElementById('submitTaskBtn');
        if (submitBtn) {
            submitBtn.addEventListener('click', () => this.submitTask());
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
    }

    refresh() {
        const panesCount = this.layoutManager.getPanesCount();
        for (let i = 0; i < panesCount; i++) {
            const tab = this.tabManager.getActiveTab(i);
            if (tab) {
                if (tab.type === 'chat') {
                    this.chatView.loadSessions(i);
                } else {
                    this.taskView.loadTasks(i);
                }
            }
        }
    }

    refreshProjectProviders() {
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
        const usernames = rawUsernames.length ? rawUsernames : ['ubuntu'];
        const fallbackUser = (selectedUser && usernames.includes(selectedUser))
            ? selectedUser
            : (usernames.includes('ubuntu') ? 'ubuntu' : (usernames[0] || 'ubuntu'));

        const buildModelOptions = (user) => {
            const agents = this.chatView.getAvailableAgents(user);
            const agentModels = [...new Set(agents.map(agent => agent.agent_type))];
            const customProviderNames = this.getCustomProviderNames ? this.getCustomProviderNames() : [];
            const defaultProviders = this.getDefaultProviders ? this.getDefaultProviders() : ['claude', 'gemini', 'codex', 'codebuddy'];
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
        };

        updateSelectors('taskUser', 'taskModel');
        updateSelectors('bulkUser', 'bulkModel');
        updateSelectors('chainUser', 'chainModel');
    }

    showCreateTaskModal(mode = 'single') {
        const modal = document.getElementById('createTaskModal');
        if (!modal) return;

        // Reset form - safely check element exists before setting value
        const taskDesc = document.getElementById('taskDescription');
        if (taskDesc) taskDesc.value = '';
        const taskWorkspace = document.getElementById('taskWorkspace');
        if (taskWorkspace) taskWorkspace.value = '';
        const taskDependsOn = document.getElementById('taskDependsOn');
        if (taskDependsOn) taskDependsOn.value = '';
        const taskAlias = document.getElementById('taskAlias');
        if (taskAlias) taskAlias.value = '';
        const bulkTasks = document.getElementById('bulkTasks');
        if (bulkTasks) bulkTasks.value = '';
        const bulkAlias = document.getElementById('bulkAlias');
        if (bulkAlias) bulkAlias.value = '';
        const chainTasks = document.getElementById('chainTasks');
        if (chainTasks) chainTasks.value = '';
        const chainAlias = document.getElementById('chainAlias');
        if (chainAlias) chainAlias.value = '';
        const bulkWorkspace = document.getElementById('bulkWorkspace');
        if (bulkWorkspace) bulkWorkspace.value = '';
        const chainWorkspace = document.getElementById('chainWorkspace');
        if (chainWorkspace) chainWorkspace.value = '';

        // Set active tab
        this.activeModalTab = mode;
        modal.querySelectorAll('.modal-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.tab === mode);
        });
        modal.querySelectorAll('.modal-tab-content').forEach(content => {
            content.classList.toggle('active', content.dataset.tabContent === mode);
        });

        // Initialize agent/model selectors (same as New Chat)
        const globalUserFilter = document.getElementById('globalUserFilter');
        const selectedUser = globalUserFilter?.value || '';
        const allAgents = this.chatView.getAvailableAgents('');
        const rawUsernames = [...new Set(allAgents.map(agent => agent.username))];
        const usernames = rawUsernames.length ? rawUsernames : ['ubuntu'];
        const initialUser = (selectedUser && usernames.includes(selectedUser))
            ? selectedUser
            : (usernames.includes('ubuntu') ? 'ubuntu' : (usernames[0] || 'ubuntu'));

        const buildModelOptions = (user) => {
            const agents = this.chatView.getAvailableAgents(user);
            const agentModels = [...new Set(agents.map(agent => agent.agent_type))];
            // Merge with custom providers (use getCustomProviderNames for new format)
            const customProviderNames = this.getCustomProviderNames ? this.getCustomProviderNames() : [];
            const defaultProviders = this.getDefaultProviders ? this.getDefaultProviders() : ['claude', 'gemini', 'codex', 'codebuddy'];
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

        setupAgentSelectors('taskUser', 'taskModel');
        setupAgentSelectors('bulkUser', 'bulkModel');
        setupAgentSelectors('chainUser', 'chainModel');

        modal.classList.add('open');
    }

    getTaskAgentSelection(mode) {
        const globalUserFilter = document.getElementById('globalUserFilter');
        const mapping = {
            single: { userId: 'taskUser', modelId: 'taskModel' },
            bulk: { userId: 'bulkUser', modelId: 'bulkModel' },
            chain: { userId: 'chainUser', modelId: 'chainModel' },
        };
        const ids = mapping[mode] || mapping.single;
        const execUser = document.getElementById(ids.userId)?.value || globalUserFilter?.value || 'ubuntu';
        const provider = document.getElementById(ids.modelId)?.value || 'claude';
        return { execUser, provider };
    }

    async submitTask() {
        const { execUser, provider } = this.getTaskAgentSelection(this.activeModalTab);

        try {
            if (this.activeModalTab === 'single') {
                await this.submitSingleTask(execUser, provider);
            } else if (this.activeModalTab === 'bulk') {
                await this.submitBulkTasks(execUser, provider);
            } else if (this.activeModalTab === 'chain') {
                await this.submitTaskChain(execUser, provider);
            }

            document.getElementById('createTaskModal')?.classList.remove('open');
            this.refresh();
        } catch (error) {
            console.error('Failed to create task:', error);
            this.showToast(error.message || 'Failed to create task', 'error');
        }
    }

    async submitSingleTask(execUser, provider) {
        const description = document.getElementById('taskDescription')?.value.trim();
        const workspace = document.getElementById('taskWorkspace')?.value.trim();
        const dependsOnStr = document.getElementById('taskDependsOn')?.value.trim();
        const selectedProvider = provider || this.getDefaultProvider();
        const aliasValue = selectedProvider;

        if (!description) {
            throw new Error('Description is required');
        }

        const payload = {
            description,
            provider: selectedProvider,
            alias: aliasValue,
            workspace: workspace || undefined,
            depends_on: dependsOnStr ? dependsOnStr.split(',').map(s => s.trim()).filter(Boolean) : undefined
        };

        await NexusAPI.createTask(payload, { execUser });
        this.showToast('Task created successfully', 'success');
    }

    async submitBulkTasks(execUser, provider) {
        const tasksText = document.getElementById('bulkTasks')?.value.trim();
        const workspace = document.getElementById('bulkWorkspace')?.value.trim();
        const selectedProvider = provider || this.getDefaultProvider();
        const aliasValue = selectedProvider;

        if (!tasksText) {
            throw new Error('Please enter at least one task');
        }

        const taskDescriptions = tasksText.split('\n')
            .map(line => line.trim())
            .filter(line => line.length > 0);

        if (taskDescriptions.length === 0) {
            throw new Error('Please enter at least one task');
        }

        // Use bulk create API
        const tasks = taskDescriptions.map(description => ({
            description,
            provider: selectedProvider,
            alias: aliasValue,
            workspace: workspace || undefined
        }));

        const result = await NexusAPI.bulkCreateTasks(tasks, { execUser });
        
        if (result.errors && result.errors.length > 0) {
            this.showToast(`Created ${result.created.length} tasks, ${result.errors.length} failed`, 'warning');
        } else {
            this.showToast(`Created ${result.created.length} tasks`, 'success');
        }
    }

    async submitTaskChain(execUser, provider) {
        const tasksText = document.getElementById('chainTasks')?.value.trim();
        const workspace = document.getElementById('chainWorkspace')?.value.trim();
        const selectedProvider = provider || this.getDefaultProvider();
        const aliasValue = selectedProvider;

        if (!tasksText) {
            throw new Error('Please enter at least one task');
        }

        const taskDescriptions = tasksText.split('\n')
            .map(line => line.trim().replace(/^\d+\.\s*/, '')) // Remove numbering
            .filter(line => line.length > 0);

        if (taskDescriptions.length === 0) {
            throw new Error('Please enter at least one task');
        }

        // Use bulk create API with temp_id dependencies for chain
        const tasks = taskDescriptions.map((description, index) => ({
            description,
            provider: selectedProvider,
            alias: aliasValue,
            workspace: workspace || undefined,
            depends_on: index > 0 ? [`temp_${index - 1}`] : undefined
        }));

        const result = await NexusAPI.bulkCreateTasks(tasks, { execUser });
        
        if (result.errors && result.errors.length > 0) {
            this.showToast(`Created ${result.created.length} tasks in chain, ${result.errors.length} failed`, 'warning');
        } else {
            this.showToast(`Created task chain with ${result.created.length} tasks`, 'success');
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
                username: globalUserFilter?.value || 'ubuntu'
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
        // Remove any existing dropdown
        const existing = document.querySelector('.tab-add-dropdown');
        if (existing) existing.remove();

        const dropdown = document.createElement('div');
        dropdown.className = 'tab-add-dropdown';
        dropdown.innerHTML = `
            <div class="tab-add-dropdown-header">New Tab</div>
            <button class="tab-add-option" data-type="chat">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
                </svg>
                <span>New Chat</span>
                <span class="tab-add-option-desc">Chat session view</span>
            </button>
            <button class="tab-add-option" data-type="task">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>
                </svg>
                <span>New Task</span>
                <span class="tab-add-option-desc">Task kanban view</span>
            </button>
        `;

        document.body.appendChild(dropdown);

        // Position dropdown below button with proper alignment
        this.positionDropdown(dropdown, btn);

        // Bind option clicks
        dropdown.querySelectorAll('.tab-add-option').forEach(option => {
            option.addEventListener('click', () => {
                const type = option.dataset.type;
                this.tabManager.addTab(paneId, type);
                dropdown.remove();
            });
        });

        // Close on outside click
        const closeHandler = (e) => {
            if (!dropdown.contains(e.target) && e.target !== btn) {
                dropdown.remove();
                document.removeEventListener('click', closeHandler);
            }
        };
        setTimeout(() => document.addEventListener('click', closeHandler), 0);
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
