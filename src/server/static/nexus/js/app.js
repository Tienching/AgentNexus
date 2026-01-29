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
            tab.title = viewType === 'chat' ? 'Chat' : 'Tasks';
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
            title: title || (type === 'chat' ? 'Chat' : 'Tasks'),
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
            tab.title = newType === 'chat' ? 'Chat' : 'Tasks';
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
        this.currentSession = {};
    }

    async render(paneId, tab, container) {
        container.innerHTML = `
            <div class="chat-container">
                <div class="session-list" id="sessionList-${paneId}">
                    <div class="session-list-header">
                        <div class="session-header-row">
                            <span class="session-header-title">会话列表</span>
                            <button class="action-btn compact" data-action="new-session" data-pane="${paneId}">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                                </svg>
                                新建会话
                            </button>
                        </div>
                        <div class="session-search">
                            <svg class="session-search-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                            </svg>
                            <input type="text" class="session-search-input" placeholder="搜索会话..." data-pane="${paneId}">
                        </div>
                        <div class="session-filter">
                            <select class="session-filter-select" data-pane="${paneId}" data-filter="status">
                                <option value="">所有状态</option>
                                <option value="running">运行中</option>
                                <option value="completed">已完成</option>
                                <option value="error">错误</option>
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
                        <p class="empty-state-title">选择一个会话</p>
                        <p class="empty-state-text">从左侧列表选择会话查看消息</p>
                    </div>
                </div>
            </div>
        `;

        this.bindEvents(paneId);
        await this.loadSessions(paneId);
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
    }

    showNewSessionView(paneId) {
        const detail = document.getElementById(`chatDetail-${paneId}`);
        if (!detail) return;

        // Clear current session selection
        this.currentSession[paneId] = null;
        const container = document.getElementById(`sessionItems-${paneId}`);
        container?.querySelectorAll('.session-item').forEach(item => {
            item.classList.remove('active');
        });

        // Get agent options from global user filter
        const globalUserFilter = document.getElementById('globalUserFilter');
        const options = globalUserFilter ? globalUserFilter.innerHTML : '<option value="ubuntu">ubuntu</option>';

        // Render new session view with input and agent selector
        detail.innerHTML = `
            <div class="new-session-view">
                <div class="new-session-content">
                    <div class="new-session-icon">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="64" height="64">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
                        </svg>
                    </div>
                    <h2 class="new-session-title">开始新对话</h2>
                    <p class="new-session-hint">选择 Agent 并输入您的问题或需求</p>
                </div>
                <div class="new-session-agent-selector">
                    <label for="newSessionAgent-${paneId}">选择 Agent:</label>
                    <select id="newSessionAgent-${paneId}" class="new-session-agent-select">
                        ${options.replace('<option value="">All Users</option>', '')}
                    </select>
                </div>
                <div class="new-session-input-container">
                    <textarea 
                        id="newSessionInput-${paneId}" 
                        class="new-session-input" 
                        placeholder="输入您的消息..."
                        rows="3"
                    ></textarea>
                    <button class="new-session-send-btn" data-pane="${paneId}">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="20" height="20">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
                        </svg>
                        发送
                    </button>
                </div>
            </div>
        `;

        // Set default agent to ubuntu
        const agentSelect = document.getElementById(`newSessionAgent-${paneId}`);
        if (agentSelect) {
            agentSelect.value = 'ubuntu';
        }

        // Bind events
        const textarea = document.getElementById(`newSessionInput-${paneId}`);
        const sendBtn = detail.querySelector('.new-session-send-btn');

        if (textarea) {
            textarea.focus();
            textarea.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    const selectedAgent = agentSelect?.value || 'ubuntu';
                    this.createNewSession(paneId, textarea.value, selectedAgent);
                }
            });
        }

        if (sendBtn) {
            sendBtn.addEventListener('click', () => {
                const selectedAgent = agentSelect?.value || 'ubuntu';
                this.createNewSession(paneId, textarea?.value || '', selectedAgent);
            });
        }
    }

    async createNewSession(paneId, message, agentName = 'ubuntu') {
        if (!message.trim()) {
            this.app.showToast('请输入消息内容', 'warning');
            return;
        }

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
                    <span class="chat-header-meta">新会话 - ${agentName}</span>
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
                            <span class="thinking-text">思考中...</span>
                        </div>
                    </div>
                </div>
            </div>
            <div class="chat-input-container">
                <textarea 
                    id="chatInput-${paneId}" 
                    class="chat-input" 
                    placeholder="输入消息继续对话..."
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
            // Build legacy (易事厅) request payload 
            // The backend auto-detects protocol, default is legacy format
            const payload = {
                content: message,
                user: agentName,
                session_id: sessionId,
                msg_type: 'text'
            };

            // Call streaming API
            await this.streamChatResponse(paneId, agentName, payload, `thinking-${paneId}`);
            
            // After successful response, set current session and reload everything
            this.currentSession[paneId] = sessionId;
            
            // Reload sessions list first, then load messages after a delay to ensure backend has saved them
            await this.loadSessions(paneId);
            setTimeout(() => {
                this.loadMessages(paneId, sessionId);
            }, 500);
            
        } catch (error) {
            console.error('Failed to create session:', error);
            this.app.showToast(error.message || '创建会话失败', 'error');
            
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
                            <span>${this.escapeHtml(error.message || '请求失败')}</span>
                            <button class="retry-btn" onclick="nexusApp.chatView.showNewSessionView('${paneId}')">重试</button>
                        </div>
                    </div>
                `;
            }
        }
    }

    async streamChatResponse(paneId, agentName, payload, thinkingId) {
        const messagesContainer = document.getElementById(`chatMessages-${paneId}`);
        const thinkingEl = document.getElementById(thinkingId);
        
        // Replace thinking indicator with streaming response container
        if (thinkingEl) {
            thinkingEl.innerHTML = `
                <div class="message-avatar assistant">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="18" height="18">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                    </svg>
                </div>
                <div class="message-content">
                    <div class="message-text streaming" id="streaming-content-${thinkingId}"></div>
                </div>
            `;
        }
        
        const contentEl = document.getElementById(`streaming-content-${thinkingId}`);
        let fullContent = '';
        
        // Call streaming API
        const response = await NexusAPI.chatStream(agentName, payload);
        
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
                                fullContent += data.response;
                                if (contentEl) {
                                    contentEl.innerHTML = this.formatMessageContent(fullContent);
                                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                                }
                            }
                            // Check if stream is finished
                            if (data.finished === true) {
                                // Stream completed, remove streaming indicator
                                if (contentEl) {
                                    contentEl.classList.remove('streaming');
                                }
                            }
                        }
                        // Handle legacy format (event:delta, data.delta)
                        else if (eventType === 'delta' && data.delta) {
                            fullContent += data.delta;
                            if (contentEl) {
                                contentEl.innerHTML = this.formatMessageContent(fullContent);
                                messagesContainer.scrollTop = messagesContainer.scrollHeight;
                            }
                        }
                        // Handle AGUI format
                        else if (data.type === 'TEXT_MESSAGE_CONTENT' && data.delta) {
                            fullContent += data.delta;
                            if (contentEl) {
                                contentEl.innerHTML = this.formatMessageContent(fullContent);
                                messagesContainer.scrollTop = messagesContainer.scrollHeight;
                            }
                        }
                        // Handle generic delta
                        else if (data.delta && !data.type) {
                            fullContent += data.delta;
                            if (contentEl) {
                                contentEl.innerHTML = this.formatMessageContent(fullContent);
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
        if (contentEl) {
            contentEl.classList.remove('streaming');
        }
        
        // Re-enable input
        const textarea = document.getElementById(`chatInput-${paneId}`);
        const sendBtn = document.querySelector(`.chat-send-btn[data-pane="${paneId}"]`);
        if (textarea) textarea.disabled = false;
        if (sendBtn) sendBtn.disabled = false;
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
            item.addEventListener('click', () => {
                this.selectSession(paneId, item.dataset.sessionId);
            });
        });
    }

    renderSessionItem(session, paneId) {
        const statusClass = session.status === 'running' ? 'running' : 
                           session.status === 'error' ? 'error' : 'completed';
        const timeStr = this.formatTime(session.updated_at || session.created_at);
        const isActive = this.currentSession[paneId] === session.id;

        return `
            <div class="session-item ${isActive ? 'active' : ''}" data-session-id="${session.id}">
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
                    ${session.username ? `<span>@${session.username}</span>` : ''}
                </div>
            </div>
        `;
    }

    async selectSession(paneId, sessionId) {
        this.currentSession[paneId] = sessionId;
        
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
                    <button class="action-btn" data-action="delete-session" data-session-id="${sessionId}">
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
                    placeholder="输入消息继续对话..."
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
                        <span class="thinking-text">思考中...</span>
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
            this.app.showToast(error.message || '发送消息失败', 'error');
            
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
                            <span>${this.escapeHtml(error.message || '发送失败')}</span>
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
        // Get agent name from global filter
        const globalUserFilter = document.getElementById('globalUserFilter');
        const agentName = globalUserFilter?.value || 'ubuntu';
        
        // Build legacy (易事厅) request payload with session_id to continue conversation
        const payload = {
            content: message,
            user: agentName,
            session_id: sessionId,
            msg_type: 'text'
        };
        
        // Use the shared streaming method
        await this.streamChatResponse(paneId, agentName, payload, thinkingId);
        
        // Refresh session list to update last_message
        this.loadSessions(paneId);
    }

    renderMessage(msg, toolCalls) {
        const isUser = msg.role === 'user';
        const avatar = isUser ? 'U' : 'A';
        const timeStr = this.formatTime(msg.timestamp);
        const hasContent = msg.content && msg.content.trim();

        // Find tool calls for this message
        const messageToolCalls = toolCalls.filter(tc => tc.parent_message_id === msg.id || tc.message_id === msg.id);

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
            bubbleContent = '<span class="message-empty">(空消息)</span>';
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
            pending: { icon: '⏳', color: 'var(--text-muted)', bgColor: 'rgba(148, 163, 184, 0.1)', label: '等待中' },
            executing: { icon: '▶️', color: 'var(--primary-500)', bgColor: 'rgba(59, 130, 246, 0.1)', label: '执行中' },
            completed: { icon: '✓', color: 'var(--success)', bgColor: 'rgba(16, 185, 129, 0.1)', label: '已完成' },
            failed: { icon: '✗', color: 'var(--error)', bgColor: 'rgba(239, 68, 68, 0.1)', label: '失败' }
        };
        const cfg = statusConfig[status] || statusConfig.pending;
        
        // Calculate execution time
        let execTime = '';
        if (tc.start_time && tc.end_time) {
            const ms = tc.end_time - tc.start_time;
            execTime = ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(2)}s`;
        }
        
        // Format args and result
        const argsContent = tc.args ? JSON.stringify(tc.args, null, 2) : tc.args_string || '';
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
                        ${tc.error ? `<span class="tool-call-standalone-error-badge">⚠ 错误</span>` : ''}
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
                                        输入参数
                                    </span>
                                    <button class="tool-call-standalone-copy-btn" onclick="event.stopPropagation(); nexusApp.chatView.copyToClipboard('${toolId}-args')">
                                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                                        </svg>
                                        复制
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
                                        执行结果
                                    </span>
                                    <button class="tool-call-standalone-copy-btn" onclick="event.stopPropagation(); nexusApp.chatView.copyToClipboard('${toolId}-result')">
                                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                                        </svg>
                                        复制
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
                                        错误信息
                                    </span>
                                    <button class="tool-call-standalone-copy-btn" onclick="event.stopPropagation(); nexusApp.chatView.copyToClipboard('${toolId}-error')">
                                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                                        </svg>
                                        复制
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
            pending: { icon: '⏳', color: 'var(--text-muted)', label: '等待中' },
            executing: { icon: '▶️', color: 'var(--primary-500)', label: '执行中' },
            completed: { icon: '✓', color: 'var(--success)', label: '已完成' },
            failed: { icon: '✗', color: 'var(--error)', label: '失败' }
        };
        const cfg = statusConfig[status] || statusConfig.pending;
        
        // Calculate execution time
        let execTime = '';
        if (tc.start_time && tc.end_time) {
            const ms = tc.end_time - tc.start_time;
            execTime = ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(2)}s`;
        }
        
        // Format args and result
        const argsContent = tc.args ? JSON.stringify(tc.args, null, 2) : tc.args_string || '';
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
                    ${tc.error ? `<span class="tool-call-error-badge">错误</span>` : ''}
                    <svg class="tool-call-toggle" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                    </svg>
                </div>
                <div class="tool-call-body">
                    ${argsContent ? `
                        <div class="tool-call-section">
                            <div class="tool-call-section-header">
                                <span class="tool-call-section-title">输入参数</span>
                                <button class="tool-call-copy-btn" onclick="event.stopPropagation(); nexusApp.chatView.copyToClipboard('${toolId}-args')">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                                    </svg>
                                    复制
                                </button>
                            </div>
                            <div class="tool-call-content" id="${toolId}-args">${this.escapeHtml(argsContent)}</div>
                        </div>
                    ` : ''}
                    ${resultContent ? `
                        <div class="tool-call-section">
                            <div class="tool-call-section-header">
                                <span class="tool-call-section-title">执行结果</span>
                                <button class="tool-call-copy-btn" onclick="event.stopPropagation(); nexusApp.chatView.copyToClipboard('${toolId}-result')">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                                    </svg>
                                    复制
                                </button>
                            </div>
                            <div class="tool-call-content tool-call-result" id="${toolId}-result">${this.escapeHtml(resultContent)}</div>
                        </div>
                    ` : ''}
                    ${tc.error ? `
                        <div class="tool-call-section">
                            <div class="tool-call-section-header">
                                <span class="tool-call-section-title" style="color: var(--error);">错误信息</span>
                                <button class="tool-call-copy-btn" onclick="event.stopPropagation(); nexusApp.chatView.copyToClipboard('${toolId}-error')">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                                    </svg>
                                    复制
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
            this.app.showToast('已复制到剪贴板', 'success');
        }).catch(err => {
            console.error('复制失败:', err);
            this.app.showToast('复制失败', 'error');
        });
    }

    async deleteSession(paneId, sessionId) {
        try {
            await NexusAPI.deleteSession(sessionId);
            this.app.showToast('Session deleted', 'success');
            this.currentSession[paneId] = null;
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
}

// ============================================================
// Task View
// ============================================================
class TaskView {
    constructor(app) {
        this.app = app;
        this.tasks = {};
        this.selectedTask = {};
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
                        </div>
                        <div class="task-toolbar-right">
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

        // Search input
        const searchInput = document.getElementById(`taskSearch-${paneId}`);
        if (searchInput) {
            let timeout;
            searchInput.addEventListener('input', () => {
                clearTimeout(timeout);
                timeout = setTimeout(() => this.loadTasks(paneId), 300);
            });
        }
    }

    async loadTasks(paneId) {
        const searchInput = document.getElementById(`taskSearch-${paneId}`);
        const globalUserFilter = document.getElementById('globalUserFilter');

        try {
            const options = {
                agentName: globalUserFilter?.value || 'ubuntu',
                pageSize: 100,
                search: searchInput?.value || ''
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
                        card.addEventListener('click', () => {
                            this.selectTask(paneId, card.dataset.taskId);
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

        return `
            <div class="task-card ${isSelected ? 'selected' : ''}" data-task-id="${task.id}">
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
                agentName: globalUserFilter?.value || 'ubuntu' 
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
                agentName: globalUserFilter?.value || 'ubuntu' 
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

        this.deleteCallback = null;
        this.renameTabCallback = null;
        this.activeModalTab = 'single';

        this.init();
    }

    init() {
        // Initialize layout
        this.layoutManager.setMode(this.layoutManager.mode);

        // Load usernames for filter
        this.loadUsernames();

        // Bind global events
        this.bindEvents();
    }

    async loadUsernames() {
        try {
            const data = await NexusAPI.getUsernames();
            const select = document.getElementById('globalUserFilter');
            if (select && data.usernames) {
                select.innerHTML = '<option value="">All Users</option>' +
                    data.usernames.map(u => `<option value="${u}">${u}</option>`).join('');
            }
        } catch (error) {
            console.error('Failed to load usernames:', error);
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

    showCreateTaskModal(mode = 'single') {
        const modal = document.getElementById('createTaskModal');
        if (!modal) return;

        // Reset form
        document.getElementById('taskDescription').value = '';
        document.getElementById('taskWorkspace').value = '';
        document.getElementById('taskDependsOn').value = '';
        document.getElementById('bulkTasks').value = '';
        document.getElementById('chainTasks').value = '';

        // Set active tab
        this.activeModalTab = mode;
        modal.querySelectorAll('.modal-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.tab === mode);
        });
        modal.querySelectorAll('.modal-tab-content').forEach(content => {
            content.classList.toggle('active', content.dataset.tabContent === mode);
        });

        modal.classList.add('open');
    }

    async submitTask() {
        const globalUserFilter = document.getElementById('globalUserFilter');
        const agentName = document.getElementById('taskAgent')?.value || 
                         globalUserFilter?.value || 'ubuntu';

        try {
            if (this.activeModalTab === 'single') {
                await this.submitSingleTask(agentName);
            } else if (this.activeModalTab === 'bulk') {
                await this.submitBulkTasks(agentName);
            } else if (this.activeModalTab === 'chain') {
                await this.submitTaskChain(agentName);
            }

            document.getElementById('createTaskModal')?.classList.remove('open');
            this.refresh();
        } catch (error) {
            console.error('Failed to create task:', error);
            this.showToast(error.message || 'Failed to create task', 'error');
        }
    }

    async submitSingleTask(agentName) {
        const description = document.getElementById('taskDescription')?.value.trim();
        const workspace = document.getElementById('taskWorkspace')?.value.trim();
        const provider = document.getElementById('taskProvider')?.value || 'claude';
        const dependsOnStr = document.getElementById('taskDependsOn')?.value.trim();

        if (!description) {
            throw new Error('Description is required');
        }

        const payload = {
            description,
            provider,
            workspace: workspace || undefined,
            depends_on: dependsOnStr ? dependsOnStr.split(',').map(s => s.trim()).filter(Boolean) : undefined
        };

        await NexusAPI.createTask(payload, { agentName });
        this.showToast('Task created successfully', 'success');
    }

    async submitBulkTasks(agentName) {
        const tasksText = document.getElementById('bulkTasks')?.value.trim();
        const workspace = document.getElementById('bulkWorkspace')?.value.trim();
        const provider = document.getElementById('bulkProvider')?.value || 'claude';

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
            provider,
            workspace: workspace || undefined
        }));

        const result = await NexusAPI.bulkCreateTasks(tasks, { agentName });
        
        if (result.errors && result.errors.length > 0) {
            this.showToast(`Created ${result.created.length} tasks, ${result.errors.length} failed`, 'warning');
        } else {
            this.showToast(`Created ${result.created.length} tasks`, 'success');
        }
    }

    async submitTaskChain(agentName) {
        const tasksText = document.getElementById('chainTasks')?.value.trim();
        const workspace = document.getElementById('chainWorkspace')?.value.trim();
        const provider = document.getElementById('chainProvider')?.value || 'claude';

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
            provider,
            workspace: workspace || undefined,
            depends_on: index > 0 ? [`temp_${index - 1}`] : undefined
        }));

        const result = await NexusAPI.bulkCreateTasks(tasks, { agentName });
        
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
                    <h3 class="modal-title">新建会话</h3>
                    <button class="modal-close" data-close-modal>
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                        </svg>
                    </button>
                </div>
                <div class="modal-body">
                    <div class="form-group">
                        <label class="form-label">会话标题</label>
                        <input id="newSessionTitle" type="text" class="form-input" placeholder="输入会话标题（可选）">
                    </div>
                    <p style="font-size: 12px; color: var(--text-muted); margin-top: 8px;">
                        注意：新建会话将通过 API 创建。如果您的系统不支持创建会话，此功能可能不可用。
                    </p>
                </div>
                <div class="modal-footer">
                    <button class="action-btn" data-close-modal>取消</button>
                    <button id="confirmNewSessionBtn" class="action-btn primary">创建</button>
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
            
            this.showToast('会话创建成功', 'success');
            
            // Reload sessions
            this.chatView.loadSessions(paneId);
        } catch (error) {
            console.error('Failed to create session:', error);
            this.showToast('创建会话失败：' + (error.message || '未知错误'), 'error');
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
            <div class="tab-add-dropdown-header">新建标签页</div>
            <button class="tab-add-option" data-type="chat">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
                </svg>
                <span>新建 Chat</span>
                <span class="tab-add-option-desc">对话会话视图</span>
            </button>
            <button class="tab-add-option" data-type="task">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>
                </svg>
                <span>新建 Task</span>
                <span class="tab-add-option-desc">任务看板视图</span>
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
document.addEventListener('DOMContentLoaded', () => {
    window.app = new NexusApp();
});
