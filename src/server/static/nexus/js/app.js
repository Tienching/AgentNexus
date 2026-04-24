/**
 * Nexus Application - Enhanced UI
 * Supports split-view layouts, multi-tab panes, chat and task views
 */

const { ThemeManager, PageManager, LayoutManager, TabManager } = window.NexusShellManagers || {};
const { SettingsPage } = window.NexusSettingsPage || {};
const { AgentsViewShell } = window;

if (!ThemeManager || !PageManager || !LayoutManager || !TabManager) {
    throw new Error('Nexus shell managers failed to load before app.js');
}

if (!SettingsPage) {
    throw new Error('Nexus settings page failed to load before app.js');
}

// ============================================================
// Chat View
// ============================================================
class ChatView {
    constructor(app) {
        this.app = app;
        this.sessions = {};
        this.currentSessionByTab = {}; // tabId -> sessionId for the currently active source
        this.currentSessionByTabSource = {}; // tabId -> { runtime: sessionId|null, history: sessionId|null }
        this.selectionMode = {};  // paneId -> boolean
        this.selectedSessionIds = {}; // paneId -> Set<sessionId>
        this.sessionSource = {};  // paneId -> 'runtime' | 'history'
        this.historyProjectPath = {}; // paneId -> string
        this.historyExpandedProviders = {}; // paneId -> Set<providerKey>
        this.historyExpandedAliases = {}; // paneId -> Set<provider::alias>
        this.taskSessionStreams = {}; // paneId -> EventSource (for task_* sessions)
        this.promotedRuntimeMeta = {}; // runtimeSessionId -> synthetic meta (fallback when backend promote API unavailable)
        this.pendingBootstrapBySessionId = {}; // runtimeSessionId -> one-time bootstrap context text
        this._chatStreaming = {}; // paneId -> boolean, true when fetch streaming is active (prevents auto-refresh from overwriting DOM)
        this._pendingNewSession = {}; // paneId -> { id: string, createdAt: number }
        this._chatSessionStates = {}; // `${paneId}:${sessionId}` -> explicit lifecycle state
        this._chatSessionStateHistory = {}; // `${paneId}:${sessionId}` -> [{ state, at, meta }]
        this._dataStore = (typeof AppDataStore !== 'undefined') ? AppDataStore.getInstance() : null;

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

    _normalizeSessionSource(source) {
        return String(source || 'runtime').trim().toLowerCase() === 'history' ? 'history' : 'runtime';
    }

    _ensureTabSessionState(tab) {
        if (!tab?.id) return null;
        if (this.currentSessionByTab[tab.id] === undefined) {
            this.currentSessionByTab[tab.id] = tab.data?.sessionId || null;
        }
        if (!this.currentSessionByTabSource[tab.id]) {
            const stored = tab.data?.sessionIdBySource || {};
            const fallbackSource = this._normalizeSessionSource(tab.data?.sessionSource || tab.data?.source || 'runtime');
            const fallbackSessionId = tab.data?.sessionId || this.currentSessionByTab[tab.id] || null;
            this.currentSessionByTabSource[tab.id] = {
                runtime: stored.runtime || (fallbackSource === 'runtime' ? fallbackSessionId : null),
                history: stored.history || (fallbackSource === 'history' ? fallbackSessionId : null),
            };
        }
        return this.currentSessionByTabSource[tab.id];
    }

    _setCurrentSessionForPane(paneId, sessionId, source = null) {
        const tab = this.getActiveTab(paneId);
        if (!tab?.id) return;
        const sourceKey = this._normalizeSessionSource(source || this.sessionSource[paneId] || 'runtime');
        const sourceMap = this._ensureTabSessionState(tab) || { runtime: null, history: null };
        sourceMap[sourceKey] = sessionId || null;
        this.currentSessionByTabSource[tab.id] = sourceMap;
        this.currentSessionByTab[tab.id] = sessionId || null;
        tab.data = tab.data || {};
        tab.data.sessionId = sessionId || null;
        tab.data.sessionSource = sourceKey;
        tab.data.sessionIdBySource = { ...sourceMap };
    }

    _getRememberedSessionForPane(paneId, source = null) {
        const tab = this.getActiveTab(paneId);
        if (!tab?.id) return null;
        const sourceKey = this._normalizeSessionSource(source || this.sessionSource[paneId] || 'runtime');
        const sourceMap = this._ensureTabSessionState(tab);
        return sourceMap?.[sourceKey] || null;
    }

    _clearCurrentSessionForPane(paneId, source = null) {
        this._setCurrentSessionForPane(paneId, null, source || this.sessionSource[paneId] || 'runtime');
    }

    _chatStateKey(paneId, sessionId) {
        return `${paneId}:${sessionId || ''}`;
    }

    _getChatSessionState(paneId, sessionId) {
        return this._chatSessionStates[this._chatStateKey(paneId, sessionId)] || 'idle';
    }

    _transitionChatSessionState(paneId, sessionId, nextState, meta = {}) {
        const key = this._chatStateKey(paneId, sessionId);
        const state = String(nextState || 'idle').trim().toLowerCase() || 'idle';
        const record = {
            state,
            at: Date.now(),
            meta: { ...meta },
        };
        this._chatSessionStates[key] = state;
        if (!this._chatSessionStateHistory[key]) {
            this._chatSessionStateHistory[key] = [];
        }
        this._chatSessionStateHistory[key].push(record);
        if (this._chatSessionStateHistory[key].length > 20) {
            this._chatSessionStateHistory[key].shift();
        }
        return record;
    }

    _ensureHistoryExpansionState(paneId) {
        if (!this.historyExpandedProviders[paneId]) {
            this.historyExpandedProviders[paneId] = new Set();
        }
        if (!this.historyExpandedAliases[paneId]) {
            this.historyExpandedAliases[paneId] = new Set();
        }
        if (!this.historyAutoExpanded) {
            this.historyAutoExpanded = {};
        }
    }

    /**
     * Auto-expand every provider group the first time we render history for a pane.
     * Without this, users see only collapsed provider headers and often miss that
     * multiple providers are present.
     */
    _autoExpandHistoryProvidersOnce(paneId, groups) {
        this._ensureHistoryExpansionState(paneId);
        if (this.historyAutoExpanded[paneId]) return;
        if (!groups || !groups.length) return;
        const expanded = this.historyExpandedProviders[paneId];
        for (const group of groups) {
            if (group && group.providerKey) {
                expanded.add(this._buildHistoryProviderKey(group.providerKey));
            }
        }
        this.historyAutoExpanded[paneId] = true;
    }

    _buildHistoryProviderKey(provider) {
        return String(provider || 'unknown').trim().toLowerCase() || 'unknown';
    }

    _buildHistoryAliasKey(provider, alias) {
        const providerKey = this._buildHistoryProviderKey(provider);
        const aliasValue = String(alias || provider || 'unknown').trim().toLowerCase() || 'unknown';
        if (aliasValue.includes('::')) return aliasValue;
        return `${providerKey}::${aliasValue}`;
    }

    _toggleHistoryProviderGroup(paneId, providerKey) {
        this._ensureHistoryExpansionState(paneId);
        const normalized = this._buildHistoryProviderKey(providerKey);
        const expanded = this.historyExpandedProviders[paneId];
        if (expanded.has(normalized)) {
            expanded.delete(normalized);
        } else {
            expanded.add(normalized);
        }
    }

    _toggleHistoryAliasGroup(paneId, providerKey, aliasKey) {
        this._ensureHistoryExpansionState(paneId);
        const providerNormalized = this._buildHistoryProviderKey(providerKey);
        const aliasNormalized = this._buildHistoryAliasKey(providerKey, aliasKey);
        this.historyExpandedProviders[paneId].add(providerNormalized);
        const expanded = this.historyExpandedAliases[paneId];
        if (expanded.has(aliasNormalized)) {
            expanded.delete(aliasNormalized);
        } else {
            expanded.add(aliasNormalized);
        }
    }

    _isHistoryProviderExpanded(paneId, providerKey) {
        this._ensureHistoryExpansionState(paneId);
        return this.historyExpandedProviders[paneId].has(this._buildHistoryProviderKey(providerKey));
    }

    _isHistoryAliasExpanded(paneId, providerKey, aliasKey) {
        this._ensureHistoryExpansionState(paneId);
        return this.historyExpandedAliases[paneId].has(this._buildHistoryAliasKey(providerKey, aliasKey));
    }

    _expandHistoryPathForSession(paneId, session) {
        if (!session) return;
        this._ensureHistoryExpansionState(paneId);
        const providerKey = this._buildHistoryProviderKey(session.provider);
        const aliasKey = this._buildHistoryAliasKey(session.provider, session.alias || session.provider);
        this.historyExpandedProviders[paneId].add(providerKey);
        this.historyExpandedAliases[paneId].add(aliasKey);
    }

    /**
     * Paint a provider skeleton before the real history data arrives.
     * Shows the four configured provider buckets immediately so users aren't
     * staring at a spinner for ~12s on first load (cold-scan of ~1500 JSONL files).
     * Replaced by `renderHistorySessions` once the fetch resolves.
     */
    _renderHistoryProviderSkeleton(paneId, container) {
        if (!container) container = document.getElementById(`sessionItems-${paneId}`);
        if (!container) return;
        const { aliases } = this._getHistoryConfiguredOrder();
        const providerOf = (name) => {
            const lower = String(name || '').toLowerCase();
            for (const p of ['claude', 'codex', 'codebuddy', 'gemini']) {
                if (lower === p || lower.startsWith(p)) return p;
            }
            return lower || 'unknown';
        };
        const buckets = new Map();
        for (const alias of aliases) {
            const prov = providerOf(alias);
            if (!buckets.has(prov)) buckets.set(prov, new Set());
            buckets.get(prov).add(alias);
        }
        if (buckets.size === 0) return;

        const providerLabel = (p) => (this.app?.normalizeProviderName ? this.app.normalizeProviderName(p) : p || '').toString().toUpperCase();
        const aliasLabel = (a) => (this.app?.normalizeProviderName ? this.app.normalizeProviderName(a) : a);
        const providerHtml = Array.from(buckets.entries()).map(([prov, aliasSet]) => {
            const aliasesHtml = Array.from(aliasSet).map(a => `
                <div class="history-alias-group collapsed is-skeleton">
                    <button class="history-group-toggle history-alias-group-header" type="button" disabled aria-expanded="false">
                        <span class="history-group-title-wrap">
                            <span class="history-group-chevron">▸</span>
                            <span class="history-alias-group-title">${this.escapeHtml(aliasLabel(a))}</span>
                        </span>
                        <span class="history-alias-group-count">…</span>
                    </button>
                </div>
            `).join('');
            return `
                <section class="history-provider-group expanded is-skeleton">
                    <button class="history-group-toggle history-provider-group-header" type="button" disabled aria-expanded="true">
                        <span class="history-group-title-wrap">
                            <span class="history-group-chevron">▾</span>
                            <span class="history-provider-group-title">${this.escapeHtml(providerLabel(prov))}</span>
                        </span>
                        <span class="history-provider-group-count">
                            <span class="loading-spinner sm history-provider-loading-spinner"></span>Loading…
                        </span>
                    </button>
                    <div class="history-group-body">
                        ${aliasesHtml}
                    </div>
                </section>
            `;
        }).join('');

        container.innerHTML = `
            <div class="history-sessions-summary">
                Scanning configured providers… (first load can take a few seconds)
            </div>
            ${providerHtml}
        `;
    }

    _getHistoryConfiguredOrder() {
        // `nexus` 本身不会产生历史 JSONL（它只是 orchestrator），所以在 History 侧
        // 统一剔除，避免骨架屏 / 过滤下拉 / 分组里出现一个永远为空的 NEXUS 桶。
        const HISTORY_EXCLUDED = new Set(['nexus']);
        const defaultProviders = (this.app?.getDefaultProviders ? this.app.getDefaultProviders() : ['nexus', 'claude', 'gemini', 'codex', 'codebuddy'])
            .map(name => String(name || '').trim().toLowerCase())
            .filter(name => name && !HISTORY_EXCLUDED.has(name));
        const aliases = (this.app?.getAllProviders ? this.app.getAllProviders() : defaultProviders)
            .map(name => String(name || '').trim().toLowerCase())
            .filter(name => name && !HISTORY_EXCLUDED.has(name));
        const providerRanks = new Map();
        defaultProviders.forEach((name, idx) => providerRanks.set(name, idx));
        const aliasRanks = new Map();
        aliases.forEach((name, idx) => aliasRanks.set(name, idx));
        return { providerRanks, aliasRanks, aliases };
    }

    _buildHistoryProviderFilterOptions() {
        const { aliases } = this._getHistoryConfiguredOrder();
        const seen = new Set();
        const options = aliases.filter(name => {
            if (!name || seen.has(name)) return false;
            seen.add(name);
            return true;
        });
        return options.map(name => {
            const label = this.app?.normalizeProviderName ? this.app.normalizeProviderName(name) : name;
            return `<option value="${this.escapeHtml(name)}">${this.escapeHtml(label)}</option>`;
        }).join('');
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
                const sessionQuery = {
                    pageSize: 50,
                    search: searchInput?.value || '',
                    status: statusFilter?.value || '',
                    username: globalUserFilter?.value || '',
                };
                const data = this._dataStore
                    ? await this._dataStore.fetch('sessions', sessionQuery)
                    : await NexusAPI.getSessions(sessionQuery);

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

        const tabSessionState = this._ensureTabSessionState(tab);
        const currentSourceKey = this._normalizeSessionSource(this.sessionSource[paneId]);
        if (tab?.id) {
            const remembered = tabSessionState?.[currentSourceKey] || null;
            this.currentSessionByTab[tab.id] = remembered;
            tab.data = tab.data || {};
            tab.data.sessionId = remembered;
            tab.data.sessionSource = currentSourceKey;
            tab.data.sessionIdBySource = { ...(tabSessionState || { runtime: null, history: null }) };
        }

        const isHistory = this.sessionSource[paneId] === 'history';
        const sourceToggleLabel = isHistory ? 'Back to Chats' : 'History';
        const searchPlaceholder = isHistory ? 'Search history sessions...' : 'Search chats...';
        const headerTitle = isHistory ? 'History' : 'Chats';

        container.innerHTML = `
            <div class="chat-container">
                <div class="session-list" id="sessionList-${paneId}">
                    <div class="session-list-header">
                        <div class="session-header-row">
                            <span class="session-header-title">${headerTitle}</span>
                            <div class="session-header-actions">
                                <button class="action-btn primary ${isHistory ? 'is-hidden' : ''}" data-action="new-session" data-pane="${paneId}">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                                    </svg>
                                    <span>New Chat</span>
                                </button>
                                <button class="action-btn" data-action="toggle-session-source" data-pane="${paneId}">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7h18M3 12h18M3 17h18"/>
                                    </svg>
                                    <span>${sourceToggleLabel}</span>
                                </button>
                                <button class="action-btn ${isHistory ? 'is-hidden' : ''}" data-action="toggle-session-selection" data-pane="${paneId}" title="Batch select">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>
                                    </svg>
                                    <span>Select</span>
                                </button>
                            </div>
                        </div>
                        <div class="session-selection-actions" id="sessionSelectionActions-${paneId}">
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
                        ${isHistory ? `
                            <div class="history-banner">
                                <div class="history-banner-copy">
                                    <strong>History</strong>
                                    <span>Read-only by default. History is aggregated across all projects, then grouped by configured Provider → Alias. Click a group to expand newest-first sessions.</span>
                                </div>
                            </div>
                        ` : ''}
                        <div class="session-search">
                            <svg class="session-search-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                            </svg>
                            <input type="text" class="session-search-input" placeholder="${searchPlaceholder}" data-pane="${paneId}">
                        </div>
                        <div class="session-filter ${isHistory ? 'is-hidden' : ''}" id="sessionFilter-${paneId}">
                            <select class="session-filter-select" data-pane="${paneId}" data-filter="status">
                                <option value="">All Status</option>
                                <option value="running">Running</option>
                                <option value="completed">Completed</option>
                                <option value="error">Error</option>
                            </select>
                        </div>
                        <div class="session-filter ${isHistory ? '' : 'is-hidden'}" id="historyProviderFilter-${paneId}">
                            <select class="session-filter-select history-provider-filter" data-pane="${paneId}" data-filter="provider">
                                <option value="">All configured Providers / Aliases</option>
                                ${this._buildHistoryProviderFilterOptions()}
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
                        <p class="empty-state-title">Select a chat</p>
                        <p class="empty-state-text">Choose a chat from the list to view messages, or switch to History for read-only sessions.</p>
                    </div>
                </div>
            </div>
        `;

        this.bindEvents(paneId);
        await this.loadSessions(paneId);

        const activeSessionId = tab?.id ? (this.currentSessionByTab[tab.id] || null) : null;
        // Restore session from URL hash (e.g. #task_56c45bfc) if no source-scoped selection exists.
        const hashSessionId = !activeSessionId && location.hash ? location.hash.slice(1) : null;
        const targetSessionId = activeSessionId || hashSessionId;
        if (targetSessionId) {
            const inList = (this.sessions[paneId] || []).some(s => s.id === targetSessionId);
            const isPending = this._isPendingNewSession(paneId, targetSessionId);
            if (!inList) {
                if (isPending) {
                    return;
                }
                if (activeSessionId === targetSessionId) {
                    this._clearCurrentSessionForPane(paneId, currentSourceKey);
                }
                return;
            }
            await this.selectSession(paneId, targetSessionId, { silent: true, source: currentSourceKey });
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

        // History toggle — single entry point for read-only history browsing
        const toggleSourceBtn = document.querySelector(`[data-action="toggle-session-source"][data-pane="${paneId}"]`);
        if (toggleSourceBtn) {
            toggleSourceBtn.addEventListener('click', () => {
                const nextSource = this.sessionSource[paneId] === 'history' ? 'runtime' : 'history';
                if (this.sessionSource[paneId] === nextSource) return;
                this.sessionSource[paneId] = nextSource;
                const tab = this.getActiveTab(paneId);
                if (tab?.id) {
                    const remembered = this._getRememberedSessionForPane(paneId, nextSource);
                    this.currentSessionByTab[tab.id] = remembered;
                    tab.data = tab.data || {};
                    tab.data.sessionId = remembered;
                    tab.data.sessionSource = this._normalizeSessionSource(nextSource);
                    tab.data.sessionIdBySource = { ...(this.currentSessionByTabSource[tab.id] || { runtime: null, history: null }) };
                }
                const container = document.getElementById(`sessionList-${paneId}`)?.parentElement?.parentElement;
                if (container) {
                    this.render(paneId, tab, container);
                }
            });
        }

        // Hidden History scope input hook (kept for advanced/manual integrations)
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

    _setHistoryProjectPath(paneId, projectPath) {
        const normalized = String(projectPath || '').trim();
        this.historyProjectPath[paneId] = normalized;
        const input = document.getElementById(`historyProjectPath-${paneId}`);
        if (input && input.value !== normalized) {
            input.value = normalized;
        }
        return normalized;
    }

    _collectHistoryProjectCandidates(paneId) {
        const candidates = [];
        const seen = new Set();
        const pushCandidate = (value) => {
            const normalized = String(value || '').trim();
            if (!normalized || seen.has(normalized)) return;
            seen.add(normalized);
            candidates.push(normalized);
        };

        const activeTabId = this.getActiveTabId(paneId);
        const activeSessionId = activeTabId ? this.currentSessionByTab[activeTabId] : null;
        if (activeSessionId) {
            const meta = this.getSessionMeta(paneId, activeSessionId);
            pushCandidate(meta?.exec_dir);
            pushCandidate(meta?.work_dir);
            pushCandidate(meta?.project_path);
            pushCandidate(meta?.cwd);
        }

        const sessions = this.sessions[paneId] || [];
        for (const session of sessions) {
            if ((session?.source || '').toLowerCase() === 'history') continue;
            pushCandidate(session?.exec_dir);
            pushCandidate(session?.work_dir);
            pushCandidate(session?.project_path);
            pushCandidate(session?.cwd);
        }

        return candidates;
    }

    async resolveDefaultHistoryProjectPath(paneId) {
        const existing = (this.historyProjectPath[paneId] || '').trim();
        if (existing) {
            return existing;
        }

        const runtimeCandidates = this._collectHistoryProjectCandidates(paneId);
        if (runtimeCandidates.length > 0) {
            return runtimeCandidates[0];
        }

        try {
            const globalUserFilter = document.getElementById('globalUserFilter');
            const customPaths = this.app?.getAliasHistoryConfigPaths ? this.app.getAliasHistoryConfigPaths() : {};
            const projects = await NexusAPI.getHistoryProjects({
                execUser: globalUserFilter?.value ?? '',
                customPaths: Object.keys(customPaths || {}).length ? customPaths : undefined,
            });
            if (!Array.isArray(projects) || projects.length === 0) {
                return '';
            }

            const preferredWorkspace = String(this.app?.serverDefaults?.current_workdir || '').trim().replace(/\/+$/, '');
            if (preferredWorkspace) {
                const preferredProject = projects.find(project => {
                    const projectPath = String(project?.path || '').trim().replace(/\/+$/, '');
                    return projectPath && projectPath === preferredWorkspace;
                });
                if (preferredProject?.path) {
                    return String(preferredProject.path).trim();
                }
            }

            const firstProject = projects.find(project => String(project?.path || '').trim());
            return String(firstProject?.path || '').trim();
        } catch (error) {
            console.warn('Failed to auto-discover history projects:', error);
            return '';
        }
    }

    resolvePreferredWorkspace(paneId) {
        const candidates = this._collectHistoryProjectCandidates(paneId);
        if (candidates.length > 0) {
            return candidates[0];
        }
        const currentWorkdir = String(this.app?.serverDefaults?.current_workdir || '').trim();
        if (currentWorkdir) {
            return currentWorkdir;
        }
        return '';
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
                const agentType = this.app?.normalizeProviderName
                    ? this.app.normalizeProviderName(agent.agent_type)
                    : String(agent.agent_type || '').trim().toLowerCase();
                const label = agent.display_name || `${agent.username} / ${agentType}`;
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
            const agentType = this.app?.normalizeProviderName
                ? this.app.normalizeProviderName(matched.agent_type || 'claude')
                : String(matched.agent_type || 'claude').trim().toLowerCase();
            return {
                username: matched.username,
                agentType,
                label: matched.display_name || `${matched.username} / ${agentType}`
            };
        }

        const parts = value.split('::');
        const username = parts[0] || NexusAPI.getDefaultExecUser();
        const agentType = this.app?.normalizeProviderName
            ? this.app.normalizeProviderName(parts[1] || 'claude')
            : String(parts[1] || 'claude').trim().toLowerCase();
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
        this._clearCurrentSessionForPane(paneId, this.sessionSource[paneId] || 'runtime');
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
            const agentModels = [...new Set(agents.map(agent => this.app?.normalizeProviderName ? this.app.normalizeProviderName(agent.agent_type) : String(agent.agent_type || '').trim().toLowerCase()))];
            // Merge with custom providers (use getCustomProviderNames for new format)
            const customProviderNames = this.app.getCustomProviderNames ? this.app.getCustomProviderNames() : [];
            const defaultProviders = this.app.getDefaultProviders ? this.app.getDefaultProviders() : ['nexus', 'claude', 'gemini', 'codex', 'codebuddy'];
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
                <div class="new-session-agent-selector">
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
            const agentModels = [...new Set(agents.map(agent => this.app?.normalizeProviderName ? this.app.normalizeProviderName(agent.agent_type) : String(agent.agent_type || '').trim().toLowerCase()))];
            const customProviderNames = this.app.getCustomProviderNames ? this.app.getCustomProviderNames() : [];
            const defaultProviders = this.app.getDefaultProviders ? this.app.getDefaultProviders() : ['nexus', 'claude', 'gemini', 'codex', 'codebuddy'];
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
            const workspace = this.resolvePreferredWorkspace(paneId);
            // Build legacy (易事厅) request payload 
            // The backend auto-detects protocol, default is legacy format
            const payload = {
                content: message,
                user: execUser,
                session_id: sessionId,
                msg_type: 'text',
                provider: agentType,
                alias: aliasValue,
                cwd: workspace || undefined,
                cwd_mode: workspace ? 'inplace' : undefined,
                forwardedProps: { alias: aliasValue },
            };

            // Call streaming API
            const hadContent = await this.streamChatResponse(paneId, execUser, payload, `thinking-${paneId}`);
            
            // After successful response, set current session and reload everything
            this._setCurrentSessionForPane(paneId, sessionId, 'runtime');
            
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
                            <button class="retry-btn" type="button" data-action="retry-new-session" data-pane="${paneId}">Retry</button>
                        </div>
                    </div>
                `;
            }
        }
    }

    async streamChatResponse(paneId, execUser, payload, thinkingId) {
        this._chatStreaming[paneId] = true;
        this._transitionChatSessionState(paneId, payload?.session_id || payload?.sessionId || '', 'streaming', {
            paneId,
            execUser,
            phase: 'fetch-stream',
        });

        const messagesContainer = document.getElementById(`chatMessages-${paneId}`);
        const thinkingEl = document.getElementById(thinkingId);
        const streamingView = this._createStreamingSessionView({
            container: messagesContainer,
            replaceElement: thinkingEl,
            bubbleIdPrefix: `chat-stream-bubble-${paneId}`,
            textIdPrefix: `chat-stream-text-${thinkingId}`,
            messageHtmlFactory: (messageId, bubbleId) => `
                <div class="message assistant" id="${messageId}">
                    <div class="message-avatar">A</div>
                    <div class="message-content">
                        <div class="message-bubble streaming-bubble" id="${bubbleId}"></div>
                    </div>
                </div>
            `,
        });

        const streamingController = streamingView.createController({
            onRunStarted: () => {
                this.loadSessions(paneId);
            },
            onRunFinished: () => {
                this.loadSessions(paneId);
            },
        });

        try {
            console.log('[streamChatResponse] fetching chat stream...', { paneId, execUser, thinkingId });
            const response = await NexusAPI.chatStream(execUser, payload);
            console.log('[streamChatResponse] consuming response stream...');
            await NexusStreamingController.consumeReadableStream(response, streamingController);
        } finally {
            this._chatStreaming[paneId] = false;
            streamingView.finalize();
        }

        const hasContent = streamingView.hasVisibleContent();
        if (!hasContent && payload.session_id) {
            console.log('[streamChatResponse] No content rendered during stream, fallback to snapshot reload');
            const sessionId = payload.session_id;
            this._transitionChatSessionState(paneId, sessionId, 'syncing', { phase: 'snapshot-reload' });
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
                        this._transitionChatSessionState(paneId, sessionId, 'error', { phase: 'snapshot-reload', message: e?.message || 'snapshot reload failed' });
                    }
                }
                await new Promise(r => setTimeout(r, 300));
            }
        } else if (payload.session_id) {
            this._transitionChatSessionState(paneId, payload.session_id, 'ready', { phase: 'stream-complete' });
        }

        const textarea = document.getElementById(`chatInput-${paneId}`);
        const sendBtn = document.querySelector(`.chat-send-btn[data-pane="${paneId}"]`);
        if (textarea) textarea.disabled = false;
        if (sendBtn) sendBtn.disabled = false;

        return hasContent;
    }

    _createStreamingSessionView(options = {}) {
        return new NexusStreamSessionView({
            renderMessageContent: (text) => this.formatMessageContent(text),
            renderStreamingToolCall: (toolCallId, toolName, status) => this.renderStreamingToolCall(toolCallId, toolName, status),
            formatToolCallTitle: (toolName, args, argsString = '') => this.formatToolCallTitle(toolName, args, argsString),
            escapeHtml: (value) => this.escapeHtml(value),
            ...options,
        });
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
                <div class="tool-call-header" data-action="toggle-tool-call">
                    <div class="tool-call-status status-${status}">
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
                    <div class="tool-call-section is-hidden" id="streaming-tool-result-section-${toolCallId}">
                        <div class="tool-call-section-header">
                            <span class="tool-call-section-title">Output</span>
                        </div>
                        <div class="tool-call-content tool-call-result" id="streaming-tool-result-${toolCallId}"></div>
                    </div>
                    <div class="tool-call-section is-hidden" id="streaming-tool-error-section-${toolCallId}">
                        <div class="tool-call-section-header">
                            <span class="tool-call-section-title is-error">Error</span>
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
        const sourceKey = this._normalizeSessionSource(isHistory ? 'history' : 'runtime');
        const searchInput = document.querySelector(`.session-search-input:not(.history-path-input)[data-pane="${paneId}"]`);
        const globalUserFilter = document.getElementById('globalUserFilter');

        // For history, paint a provider skeleton immediately so users see the
        // configured providers (claude / codex / codebuddy / gemini + aliases)
        // right away, instead of a blank spinner for ~12s during first-time
        // disk scans. The skeleton is replaced by the real list once data arrives.
        if (isHistory) {
            this._renderHistoryProviderSkeleton(paneId, container);
        }

        try {
            let data;

            if (isHistory) {
                const providerFilter = document.querySelector(`.history-provider-filter[data-pane="${paneId}"]`);
                const customPaths = this.app.getAliasHistoryConfigPaths();
                const historyQuery = {
                    // Take the N most-recent sessions for EACH (provider, alias) bucket so
                    // every configured provider is represented in the first response.
                    // Without this, claude alone tends to fill the first page and other
                    // providers (codex / codebuddy / gemini) never surface in the UI.
                    perAliasLimit: 50,
                    pageSize: 2000, // upper bound; ignored when per_alias_limit kicks in server-side
                    search: searchInput?.value || '',
                    provider: providerFilter?.value || '',
                    execUser: globalUserFilter?.value ?? '',
                    customPaths: Object.keys(customPaths).length ? customPaths : undefined,
                };
                data = this._dataStore
                    ? await this._dataStore.fetch('historySessions', historyQuery)
                    : await NexusAPI.getHistorySessions(historyQuery);
            } else {
                const statusFilter = document.querySelector(`.session-filter-select[data-pane="${paneId}"][data-filter="status"]`);
                const runtimeQuery = {
                    pageSize: 50,
                    search: searchInput?.value || '',
                    status: statusFilter?.value || '',
                    username: globalUserFilter?.value || ''
                };
                data = this._dataStore
                    ? await this._dataStore.fetch('sessions', runtimeQuery)
                    : await NexusAPI.getSessions(runtimeQuery);
            }

            this.sessions[paneId] = data.sessions || [];
            const pending = this._pendingNewSession[paneId];
            if (pending && this.sessions[paneId].some(s => s.id === pending.id)) {
                this._clearPendingNewSession(paneId, pending.id);
            }
            this.sessionTotals = this.sessionTotals || {};
            this.sessionTotals[paneId] = data.total || this.sessions[paneId].length;
            this.renderSessionList(paneId);

            if (!isHistory) {
                const runtimeSessions = this.sessions[paneId] || [];
                const rememberedSessionId = this._getRememberedSessionForPane(paneId, sourceKey);
                const rememberedVisible = rememberedSessionId && runtimeSessions.some(session => session.id === rememberedSessionId);

                if (runtimeSessions.length === 0) {
                    this._clearCurrentSessionForPane(paneId, sourceKey);
                    this.showNewSessionView(paneId);
                    return;
                }

                if (!rememberedVisible) {
                    const firstSession = runtimeSessions[0];
                    if (firstSession?.id) {
                        await this.selectSession(paneId, firstSession.id, {
                            silent: true,
                            source: sourceKey,
                            provider: firstSession.provider || '',
                            alias: firstSession.alias || '',
                        });
                    }
                }
            }
        } catch (error) {
            console.error('Failed to load sessions:', error);
            container.innerHTML = `
                <div class="empty-state">
                    <p class="empty-state-text text-error">Failed to load sessions</p>
                </div>
            `;
        }
    }

    renderSessionList(paneId) {
        const container = document.getElementById(`sessionItems-${paneId}`);
        if (!container) return;

        const sessions = this.sessions[paneId] || [];
        const isHistory = this.sessionSource[paneId] === 'history';
        
        if (sessions.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <svg class="empty-state-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"/>
                    </svg>
                    <p class="empty-state-title">${isHistory ? 'No history found' : 'No chats found'}</p>
                    <p class="empty-state-text">${isHistory ? 'Try another configured Provider / Alias filter.' : 'Chats will appear here'}</p>
                </div>
            `;
            return;
        }

        if (isHistory) {
            this.renderHistorySessions(paneId);
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

    groupHistorySessionsByProviderAlias(sessions = []) {
        const sortedSessions = [...sessions].sort((a, b) => {
            const left = new Date(b.updated_at || b.created_at || 0).getTime();
            const right = new Date(a.updated_at || a.created_at || 0).getTime();
            return left - right;
        });

        const { providerRanks, aliasRanks } = this._getHistoryConfiguredOrder();
        const providerMap = new Map();
        for (const session of sortedSessions) {
            const rawProvider = String(session.provider || 'unknown').trim() || 'unknown';
            const rawAlias = String(session.alias || session.provider || 'unknown').trim() || 'unknown';
            // nexus 不产生历史 JSONL，若后端异常返回也直接丢弃，保持 History 面板干净。
            if (rawProvider.toLowerCase() === 'nexus' || rawAlias.toLowerCase() === 'nexus') {
                continue;
            }
            const providerLabel = this.app?.normalizeProviderName
                ? this.app.normalizeProviderName(rawProvider)
                : rawProvider;
            const aliasLabel = rawAlias;

            const providerKey = rawProvider.toLowerCase();
            const aliasKey = `${providerKey}::${aliasLabel.toLowerCase()}`;
            const sessionTime = new Date(session.updated_at || session.created_at || 0).getTime();
            const providerRank = providerRanks.has(providerKey) ? providerRanks.get(providerKey) : Number.MAX_SAFE_INTEGER;
            const aliasRank = aliasRanks.has(aliasLabel.toLowerCase()) ? aliasRanks.get(aliasLabel.toLowerCase()) : Number.MAX_SAFE_INTEGER;

            if (!providerMap.has(providerKey)) {
                providerMap.set(providerKey, {
                    label: providerLabel,
                    providerKey,
                    latest: sessionTime,
                    total: 0,
                    providerRank,
                    aliases: new Map(),
                });
            }
            const providerGroup = providerMap.get(providerKey);
            providerGroup.latest = Math.max(providerGroup.latest, sessionTime);
            providerGroup.total += 1;

            if (!providerGroup.aliases.has(aliasKey)) {
                providerGroup.aliases.set(aliasKey, {
                    label: aliasLabel,
                    aliasKey,
                    latest: sessionTime,
                    total: 0,
                    aliasRank,
                    sessions: [],
                });
            }
            const aliasGroup = providerGroup.aliases.get(aliasKey);
            aliasGroup.latest = Math.max(aliasGroup.latest, sessionTime);
            aliasGroup.total += 1;
            aliasGroup.sessions.push(session);
        }

        return [...providerMap.values()]
            .sort((a, b) => {
                const aRank = a.providerRank ?? Number.MAX_SAFE_INTEGER;
                const bRank = b.providerRank ?? Number.MAX_SAFE_INTEGER;
                if (aRank !== bRank) {
                    return aRank - bRank;
                }
                if (b.latest !== a.latest) return b.latest - a.latest;
                return String(a.label || '').localeCompare(String(b.label || ''));
            })
            .map(providerGroup => ({
                ...providerGroup,
                aliases: [...providerGroup.aliases.values()]
                    .sort((a, b) => {
                        const aRank = a.aliasRank ?? Number.MAX_SAFE_INTEGER;
                        const bRank = b.aliasRank ?? Number.MAX_SAFE_INTEGER;
                        if (aRank !== bRank) {
                            return aRank - bRank;
                        }
                        if (b.latest !== a.latest) return b.latest - a.latest;
                        return String(a.label || '').localeCompare(String(b.label || ''));
                    })
                    .map(aliasGroup => ({
                        ...aliasGroup,
                        sessions: aliasGroup.sessions.sort((a, b) => {
                            const left = new Date(b.updated_at || b.created_at || 0).getTime();
                            const right = new Date(a.updated_at || a.created_at || 0).getTime();
                            return left - right;
                        }),
                    })),
            }));
    }

    renderHistorySessions(paneId) {
        const container = document.getElementById(`sessionItems-${paneId}`);
        if (!container) return;

        const providerFilter = document.querySelector(`.history-provider-filter[data-pane="${paneId}"]`);
        const providerValue = (providerFilter?.value || '').trim().toLowerCase();
        const sessions = (this.sessions[paneId] || []).filter(session => {
            if (!providerValue) return true;
            const provider = String(session.provider || '').trim().toLowerCase();
            const alias = String(session.alias || '').trim().toLowerCase();
            return provider === providerValue || alias === providerValue;
        });

        if (sessions.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <svg class="empty-state-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
                    </svg>
                    <p class="empty-state-title">No history found</p>
                    <p class="empty-state-text">Try another configured Provider / Alias filter.</p>
                </div>
            `;
            return;
        }

        this._ensureHistoryExpansionState(paneId);
        const activeHistorySessionId = this._getRememberedSessionForPane(paneId, 'history');
        if (activeHistorySessionId) {
            const activeHistorySession = sessions.find(session => session.id === activeHistorySessionId);
            if (activeHistorySession) {
                this._expandHistoryPathForSession(paneId, activeHistorySession);
            }
        }

        const groups = this.groupHistorySessionsByProviderAlias(sessions);
        this._autoExpandHistoryProvidersOnce(paneId, groups);
        const totalSessionsShown = groups.reduce((acc, g) => acc + (g.total || 0), 0);
        const providerCount = groups.length;
        const aliasCount = groups.reduce((acc, g) => acc + (g.aliases?.length || 0), 0);
        container.innerHTML = `
            <div class="history-sessions-summary">
                ${providerCount} provider${providerCount === 1 ? '' : 's'} · ${aliasCount} alias${aliasCount === 1 ? '' : 'es'} · ${totalSessionsShown} session${totalSessionsShown === 1 ? '' : 's'} shown (latest per alias)
            </div>
            ${groups.map(providerGroup => {
                const providerExpanded = this._isHistoryProviderExpanded(paneId, providerGroup.providerKey);
                return `
                <section class="history-provider-group ${providerExpanded ? 'expanded' : 'collapsed'}" data-provider-key="${this.escapeHtml(providerGroup.providerKey)}">
                    <button class="history-group-toggle history-provider-group-header" type="button" data-action="toggle-history-provider" data-provider-key="${this.escapeHtml(providerGroup.providerKey)}" aria-expanded="${providerExpanded ? 'true' : 'false'}">
                        <span class="history-group-title-wrap">
                            <span class="history-group-chevron">${providerExpanded ? '▾' : '▸'}</span>
                            <span class="history-provider-group-title">${this.escapeHtml(providerGroup.label)}</span>
                        </span>
                        <span class="history-provider-group-count">${providerGroup.total} session${providerGroup.total === 1 ? '' : 's'}</span>
                    </button>
                    <div class="history-group-body" ${providerExpanded ? '' : 'hidden'}>
                        ${providerGroup.aliases.map(aliasGroup => {
                            const aliasExpanded = this._isHistoryAliasExpanded(paneId, providerGroup.providerKey, aliasGroup.aliasKey);
                            return `
                            <div class="history-alias-group ${aliasExpanded ? 'expanded' : 'collapsed'}" data-alias-key="${this.escapeHtml(aliasGroup.aliasKey)}">
                                <button class="history-group-toggle history-alias-group-header" type="button" data-action="toggle-history-alias" data-provider-key="${this.escapeHtml(providerGroup.providerKey)}" data-alias-key="${this.escapeHtml(aliasGroup.aliasKey)}" aria-expanded="${aliasExpanded ? 'true' : 'false'}">
                                    <span class="history-group-title-wrap">
                                        <span class="history-group-chevron">${aliasExpanded ? '▾' : '▸'}</span>
                                        <span class="history-alias-group-title">${this.escapeHtml(aliasGroup.label)}</span>
                                    </span>
                                    <span class="history-alias-group-count">${aliasGroup.total} session${aliasGroup.total === 1 ? '' : 's'}</span>
                                </button>
                                <div class="history-group-body history-alias-group-body" ${aliasExpanded ? '' : 'hidden'}>
                                    ${aliasGroup.sessions.map(session => this.renderSessionItem(session, paneId)).join('')}
                                </div>
                            </div>
                            `;
                        }).join('')}
                    </div>
                </section>
                `;
            }).join('')}
        `;

        container.querySelectorAll('[data-action="toggle-history-provider"]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this._toggleHistoryProviderGroup(paneId, btn.dataset.providerKey || '');
                this.renderHistorySessions(paneId);
            });
        });

        container.querySelectorAll('[data-action="toggle-history-alias"]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this._toggleHistoryAliasGroup(paneId, btn.dataset.providerKey || '', btn.dataset.aliasKey || '');
                this.renderHistorySessions(paneId);
            });
        });

        // Bind click events
        container.querySelectorAll('.session-item').forEach(item => {
            item.addEventListener('click', (e) => {
                if (e.target.closest('.session-item-action')) return;
                if (e.target.closest('.session-item-checkbox')) return;
                this.selectSession(paneId, item.dataset.sessionId);
            });
        });

        container.querySelectorAll('[data-action="open-history-session"]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.selectSession(paneId, btn.dataset.sessionId, { silent: true });
            });
        });

        container.querySelectorAll('[data-action="continue-history-session"]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.continueHistorySession(paneId, btn.dataset.sessionId);
            });
        });
    }

    renderSessionItem(session, paneId) {
        const isHistory = this.sessionSource[paneId] === 'history';
        const statusClass = ['running', 'pending', 'queued'].includes(session.status) ? 'running' :
                           session.status === 'error' ? 'error' : 'completed';
        const timeStr = this.formatTime(session.updated_at || session.created_at);
        const activeTabId = this.getActiveTabId(paneId);
        const sourceKey = this._normalizeSessionSource(isHistory ? 'history' : 'runtime');
        const activeSessionId = activeTabId
            ? (this.currentSessionByTabSource[activeTabId]?.[sourceKey] || (this.sessionSource[paneId] === sourceKey ? this.currentSessionByTab[activeTabId] : null))
            : null;
        const isActive = activeSessionId === session.id;
        const isInSelectionMode = this.selectionMode[paneId];
        const isChecked = this.selectedSessionIds[paneId]?.has(session.id);

        const providerBadge = isHistory && session.provider
            ? `<span class="history-provider-badge">${this.escapeHtml(this.app?.normalizeProviderName ? this.app.normalizeProviderName(session.provider) : session.provider)}${session.alias && session.alias !== session.provider ? ` <span class="history-provider-badge-sep">→</span> ${this.escapeHtml(session.alias)}` : ''}</span>`
            : '';
        const sourceBadge = isHistory
            ? `<span class="history-source-badge">Read-only</span>`
            : '';
        const historyWorkspace = isHistory ? String(session.exec_dir || session.work_dir || '').trim() : '';
        const historyWorkspaceLabel = historyWorkspace
            ? historyWorkspace.split('/').filter(Boolean).slice(-2).join('/')
            : '';

        return `
            <div class="session-item ${isActive ? 'active' : ''} ${isChecked ? 'checked' : ''}"
                 data-session-id="${session.id}"
                 data-provider="${this.escapeHtml(session.provider || '')}"
                 data-alias="${this.escapeHtml(session.alias || '')}"
                 data-source="${isHistory ? 'history' : 'runtime'}"
                 data-status="${this.escapeHtml(session.status || 'idle')}">
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
                                ${this.escapeHtml(session.status || 'idle')}
                            </span>
                        `}
                        ${session.username ? `<span>@${this.escapeHtml(session.username)}${session.provider ? ' / ' + this.escapeHtml(this.app?.normalizeProviderName ? this.app.normalizeProviderName(session.provider) : session.provider) : ''}</span>` : ''}
                        ${isHistory && session.message_count ? `<span>${session.message_count} msgs</span>` : ''}
                    </div>
                    ${isHistory ? `
                    ${historyWorkspace ? `
                    <div class="session-item-details">
                        <span class="session-item-path" title="${this.escapeHtml(historyWorkspace)}">📂 ${this.escapeHtml(historyWorkspaceLabel || historyWorkspace)}</span>
                    </div>
                    ` : ''}
                    <div class="history-session-actions">
                        <button class="session-item-action history-session-action" data-action="open-history-session" data-session-id="${session.id}" type="button">View</button>
                        <button class="session-item-action history-session-action primary" data-action="continue-history-session" data-session-id="${session.id}" type="button">Continue</button>
                    </div>
                    ` : !isHistory && session.exec_dir ? `
                    <div class="session-item-details">
                        <span class="session-item-path" title="${this.escapeHtml(session.exec_dir)}">📂 ${this.escapeHtml(session.exec_dir.split('/').slice(-2).join('/'))}</span>
                    </div>
                    ` : ''}
                </div>
            </div>
        `;
    }

    async selectSession(paneId, sessionId, options = {}) {
        // Update active state in list
        const container = document.getElementById(`sessionItems-${paneId}`);
        const sessionItem = container?.querySelector(`.session-item[data-session-id="${sessionId}"]`);
        const provider = options.provider || sessionItem?.dataset.provider || '';
        const alias = options.alias || sessionItem?.dataset.alias || '';
        const source = this._normalizeSessionSource(options.source || sessionItem?.dataset.source || this.sessionSource[paneId] || 'runtime');
        this._setCurrentSessionForPane(paneId, sessionId, source);

        container?.querySelectorAll('.session-item').forEach(item => {
            item.classList.toggle('active', item.dataset.sessionId === sessionId);
        });

        // Get provider info from the clicked item (for history sessions)

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

        const source = this._normalizeSessionSource(options.source || this.sessionSource[paneId] || 'runtime');
        this._transitionChatSessionState(paneId, sessionId, 'loading', { source, phase: 'loadMessages' });
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
            this.renderMessages(paneId, sessionId, data, { source, provider: options.provider, alias: options.alias });
        } catch (error) {
            console.error('Failed to load messages:', error);
            const isNotFound = /not found|404/i.test(error.message || '');
            if (isNotFound) {
                if (source === 'runtime' && this._isPendingNewSession(paneId, sessionId)) {
                    // Backend has not persisted the new session yet; avoid wiping streamed content.
                    return;
                }
                const attempt = Number(options._notFoundAttempt || 0);
                if (source === 'runtime' && attempt < 3) {
                    await new Promise(resolve => setTimeout(resolve, 250 * (attempt + 1)));
                    return this.loadMessages(paneId, sessionId, { ...options, source, _notFoundAttempt: attempt + 1 });
                }
                this.renderMessageLoadError(paneId, sessionId, error, { source, provider: options.provider, alias: options.alias, notFound: true });
                return;
            }
            this.renderMessageLoadError(paneId, sessionId, error, { source, provider: options.provider, alias: options.alias });
        }
    }

    renderMessageLoadError(paneId, sessionId, error, options = {}) {
        const detail = document.getElementById(`chatDetail-${paneId}`);
        if (!detail) return;

        const source = this._normalizeSessionSource(options.source || this.sessionSource[paneId] || 'runtime');
        const isNotFound = options.notFound === true || /not found|404/i.test(error?.message || '');
        this._transitionChatSessionState(paneId, sessionId, 'error', { source, phase: 'load-error', notFound: isNotFound });
        const title = isNotFound
            ? (source === 'history' ? 'History session unavailable' : 'Chat unavailable')
            : 'Failed to load messages';
        const text = isNotFound
            ? (source === 'history'
                ? 'This History session could not be loaded. It may have moved, expired, or no longer match the selected provider/alias.'
                : 'This chat could not be loaded. It may have been deleted, is still being prepared, or no longer exists in the active runtime list.')
            : (error?.message || 'Failed to load messages');
        const actionLabel = source === 'history' ? 'Reload History' : 'Reload Chats';

        detail.innerHTML = `
            <div class="empty-state">
                <svg class="empty-state-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 8v4m0 4h.01M10.29 3.86l-7.5 13A1 1 0 003.65 18h16.7a1 1 0 00.86-1.5l-7.5-13a1 1 0 00-1.72 0z"/>
                </svg>
                <p class="empty-state-title">${this.escapeHtml(title)}</p>
                <p class="empty-state-text">${this.escapeHtml(text)}</p>
                <button class="retry-btn" data-action="reload-session-list" data-pane="${paneId}">${actionLabel}</button>
            </div>
        `;

        const reloadBtn = detail.querySelector('[data-action="reload-session-list"]');
        if (reloadBtn) {
            reloadBtn.addEventListener('click', async () => {
                await this.loadSessions(paneId);
            });
        }
    }

    _closeTaskSessionStream(paneId) {
        const es = this.taskSessionStreams[paneId];
        if (es) {
            try { es.close(); } catch {}
            delete this.taskSessionStreams[paneId];
        }
    }

    async _reloadLiveSessionSnapshot(paneId, sessionId, errorPhase, warningMessage) {
        try {
            const snapshotData = await NexusAPI.getSessionMessages(sessionId);
            this.renderMessages(paneId, sessionId, snapshotData);
            return true;
        } catch (error) {
            console.warn(warningMessage, error);
            this._transitionChatSessionState(paneId, sessionId, 'error', {
                phase: errorPhase,
                message: error?.message || 'snapshot reload failed',
            });
            return false;
        }
    }

    _renderLiveStreamFallback(messagesContainer, text, tone = 'muted') {
        if (!messagesContainer) return;
        const toneClass = tone === 'error' ? 'text-error' : 'text-muted';
        messagesContainer.innerHTML = `
            <div class="empty-state streaming-empty-state">
                <p class="empty-state-text ${toneClass}">${this.escapeHtml(text)}</p>
            </div>
        `;
    }

    async _openLiveSessionStream(paneId, sessionId, options = {}) {
        if (options.skipIfOpen && this.taskSessionStreams[paneId]) return false;

        this._transitionChatSessionState(paneId, sessionId, 'streaming', {
            phase: options.phase || 'live-stream',
            paneId,
        });

        if (typeof options.beforeConnect === 'function') {
            await options.beforeConnect();
        }

        const messagesContainer = document.getElementById(`chatMessages-${paneId}`);
        if (!messagesContainer) return false;

        if (options.loadingMessage) {
            messagesContainer.innerHTML = `
                <div class="empty-state streaming-empty-state">
                    <div class="loading-spinner"></div>
                    <p class="empty-state-text streaming-empty-text">${this.escapeHtml(options.loadingMessage)}</p>
                </div>
            `;
        }

        const stream = options.streamFactory?.();
        if (!stream) return false;
        this.taskSessionStreams[paneId] = stream;

        const streamingView = this._createStreamingSessionView({
            container: messagesContainer,
            clearContainerOnFirstBubble: !!options.clearContainerOnFirstBubble,
            bubbleIdPrefix: options.bubbleIdPrefix || `live-stream-bubble-${paneId}`,
            textIdPrefix: options.textIdPrefix || `live-stream-text-${paneId}`,
        });

        let done = false;
        let sawStreamEvent = false;

        const finalizeWithSnapshot = async (phase, warningMessage, targetState = 'ready', message = '') => {
            if (done) return;
            done = true;
            this._closeTaskSessionStream(paneId);
            if (typeof options.afterClose === 'function') {
                options.afterClose();
            }
            await this._reloadLiveSessionSnapshot(paneId, sessionId, phase, warningMessage);
            this.loadSessions(paneId);
            this._transitionChatSessionState(paneId, sessionId, targetState, {
                phase: options.finishPhase || `${options.phase || 'live-stream'}-finished`,
                message,
            });
        };

        const controller = streamingView.createController({
            onRunFinished: async () => {
                await finalizeWithSnapshot(
                    options.reloadPhase || `${options.phase || 'live-stream'}-reload`,
                    options.reloadWarning || 'Failed to reload snapshot after stream finish:',
                );
            },
            onRunError: async (data) => {
                await finalizeWithSnapshot(
                    options.errorReloadPhase || `${options.phase || 'live-stream'}-reload`,
                    options.errorReloadWarning || 'Failed to reload snapshot after stream error:',
                    'error',
                    data?.message || data?.error || 'Stream error',
                );
            },
        });

        const sessionAdapter = {
            processEvent: (data, eventType) => {
                sawStreamEvent = true;
                return controller.processEvent(data, eventType);
            },
        };

        NexusStreamingController.bindEventSource(stream, sessionAdapter);

        stream.onerror = async () => {
            if (done) return;
            done = true;
            this._closeTaskSessionStream(paneId);
            if (typeof options.afterClose === 'function') {
                options.afterClose();
            }

            if (!sawStreamEvent || options.reloadOnTransportError) {
                const reloaded = await this._reloadLiveSessionSnapshot(
                    paneId,
                    sessionId,
                    options.transportErrorPhase || `${options.phase || 'live-stream'}-transport-error`,
                    options.transportErrorWarning || 'Fallback message load also failed:',
                );
                if (!reloaded && options.transportErrorFallbackText) {
                    this._renderLiveStreamFallback(
                        messagesContainer,
                        options.transportErrorFallbackText,
                        options.transportErrorFallbackTone || 'error',
                    );
                }
            }
        };

        return true;
    }

    async _streamTaskSessionMessages(paneId, sessionId) {
        const taskId = sessionId.replace(/^task_/, '');
        const globalUserFilter = document.getElementById('globalUserFilter');
        const execUser = globalUserFilter?.value || NexusAPI.getDefaultExecUser();

        this.renderMessages(paneId, sessionId, {
            session: { title: sessionId },
            messages: [],
            tool_calls: [],
        });

        await this._openLiveSessionStream(paneId, sessionId, {
            phase: 'task-stream',
            streamFactory: () => NexusAPI.streamTaskMessages(taskId, { execUser, tail: 5000 }),
            bubbleIdPrefix: `task-session-stream-${paneId}`,
            textIdPrefix: `task-session-content-${paneId}`,
            clearContainerOnFirstBubble: true,
            loadingMessage: 'Loading task stream...',
            transportErrorPhase: 'task-stream-error',
            transportErrorWarning: 'Fallback message load also failed:',
            transportErrorFallbackText: 'Failed to load task messages',
            transportErrorFallbackTone: 'error',
            reloadPhase: 'task-stream-reload',
            reloadWarning: 'Failed to reload snapshot after task finish:',
            errorReloadPhase: 'task-stream-reload',
            errorReloadWarning: 'Failed to reload snapshot after task finish:',
        });
    }

    async _streamChannelSessionMessages(paneId, sessionId) {
        const alreadyRendered = this._lastChannelStreamSession
            && this._lastChannelStreamSession[paneId] === sessionId;
        if (!this._lastChannelStreamSession) this._lastChannelStreamSession = {};
        this._lastChannelStreamSession[paneId] = sessionId;

        await this._openLiveSessionStream(paneId, sessionId, {
            phase: 'channel-stream',
            skipIfOpen: true,
            beforeConnect: async () => {
                if (alreadyRendered) return;
                try {
                    const snapshotData = await NexusAPI.getSessionMessages(sessionId);
                    this.renderMessages(paneId, sessionId, snapshotData);
                } catch (error) {
                    console.warn('Failed to load snapshot for channel session:', error);
                }
            },
            afterClose: () => {
                if (this._lastChannelStreamSession) delete this._lastChannelStreamSession[paneId];
            },
            streamFactory: () => NexusAPI.streamSessionMessages(sessionId, { tail: 5000 }),
            bubbleIdPrefix: `channel-stream-${paneId}`,
            textIdPrefix: `channel-stream-content-${paneId}`,
            reloadPhase: 'channel-stream-reload',
            reloadWarning: 'Failed to reload snapshot after channel session finish:',
            errorReloadPhase: 'channel-stream-reload',
            errorReloadWarning: 'Failed to reload snapshot after channel session finish:',
        });
    }

    renderMessages(paneId, sessionId, data, options = {}) {
        const detail = document.getElementById(`chatDetail-${paneId}`);
        if (!detail) return;

        const messages = data.messages || [];
        const toolCalls = data.tool_calls || [];
        const isHistory = (options.source || this.sessionSource[paneId] || '').toLowerCase() === 'history';
        const providerText = options.provider
            ? (this.app?.normalizeProviderName ? this.app.normalizeProviderName(options.provider) : options.provider)
            : '';
        const aliasText = options.alias && options.alias !== options.provider ? options.alias : '';
        const historyIdentityText = providerText || aliasText;

        // Track message count for auto-refresh change detection
        this._lastMessageCountBySession[sessionId] = messages.length;
        this._transitionChatSessionState(paneId, sessionId, 'ready', {
            source: options.source || this.sessionSource[paneId] || 'runtime',
            messageCount: messages.length,
        });

        detail.innerHTML = `
            <div class="chat-header">
                <div class="chat-header-info">
                    <h2 class="chat-header-title">${this.escapeHtml(data.session?.title || sessionId)}</h2>
                    <span class="chat-header-meta">${isHistory ? 'History · read-only · ' : ''}${messages.length} message${messages.length === 1 ? '' : 's'}${historyIdentityText ? ` · ${this.escapeHtml(historyIdentityText)}${providerText && aliasText ? ` / ${this.escapeHtml(aliasText)}` : ''}` : ''}</span>
                </div>
                <div class="chat-header-actions">
                    ${isHistory ? `
                        <button class="action-btn primary" data-action="continue-history-session" data-session-id="${sessionId}" title="Continue this history session in chat">
                            Continue
                        </button>
                    ` : !sessionId.startsWith('task_') ? `<button class="action-btn" data-action="fetch-from-cli" data-session-id="${sessionId}" title="Fetch from CLI file">
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
                    ${!isHistory ? `<button class="action-btn" data-action="delete-session" data-session-id="${sessionId}" title="Delete">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="16" height="16">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                        </svg>
                    </button>` : ''}
                </div>
            </div>
            <div class="chat-messages" id="chatMessages-${paneId}">
                ${messages.length === 0 
                    ? '<div class="empty-state"><p class="empty-state-text">No messages yet</p></div>'
                    : messages.map(msg => this.renderMessage(msg, toolCalls)).join('')}
            </div>
            ${isHistory ? `
                <div class="history-readonly-panel">
                    <div class="history-readonly-copy">
                        <strong>Read-only history</strong>
                        <span>View this session in read-only mode, or continue to create a live chat session.</span>
                    </div>
                </div>
            ` : `
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
            `}
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

        const continueHistoryBtn = detail.querySelector('[data-action="continue-history-session"]');
        if (continueHistoryBtn) {
            continueHistoryBtn.addEventListener('click', () => {
                this.continueHistorySession(paneId, sessionId);
            });
        }

        // Bind input events
        const textarea = document.getElementById(`chatInput-${paneId}`);
        const sendBtn = detail.querySelector('.chat-send-btn');

        if (textarea) {
            // Initialize slash command autocompleter first (so its keydown fires first)
            const completer = new SlashCompleter(textarea);
            completer.init();
            textarea._slashCompleter = completer;

            // Auto-resize textarea
            textarea.addEventListener('input', () => {
                this._autoSizeChatInput(textarea);
            });

            // Enter to send (Shift+Enter for newline)
            // SlashCompleter may intercept Enter for autocomplete selection;
            // if it does, e.defaultPrevented will be true and this handler skips.
            textarea.addEventListener('keydown', (e) => {
                if (e.defaultPrevented) return;
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

        this._bindMessageActionDelegates(detail, paneId);
    }

    _bindMessageActionDelegates(detail, paneId) {
        if (!detail || detail.dataset.messageDelegatesBound === 'true') return;
        detail.dataset.messageDelegatesBound = 'true';
        detail.addEventListener('click', (event) => {
            const retryBtn = event.target.closest('[data-action="retry-new-session"]');
            if (retryBtn) {
                event.preventDefault();
                this.showNewSessionView(Number(retryBtn.dataset.pane || paneId));
                return;
            }

            const copyBtn = event.target.closest('[data-action="copy-tool-call"]');
            if (copyBtn) {
                event.preventDefault();
                event.stopPropagation();
                const targetId = copyBtn.dataset.copyTarget;
                if (targetId) this.copyToClipboard(targetId);
                return;
            }

            const toggleBtn = event.target.closest('[data-action="toggle-tool-call"]');
            if (toggleBtn) {
                event.preventDefault();
                const toolRoot = toggleBtn.closest('.tool-call, .tool-call-standalone');
                if (toolRoot) toolRoot.classList.toggle('expanded');
            }
        });
    }

    _autoSizeChatInput(textarea) {
        if (!textarea) return;
        const computed = window.getComputedStyle(textarea);
        const lineHeight = parseFloat(computed.lineHeight) || 20;
        const maxRows = Math.max(1, Math.floor(120 / lineHeight));
        textarea.rows = 1;
        textarea.rows = Math.max(1, Math.min(maxRows, Math.ceil(textarea.scrollHeight / lineHeight)));
    }

    _resetChatInput(textarea) {
        if (!textarea) return;
        textarea.value = '';
        textarea.rows = 1;
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

    async continueHistorySession(paneId, sessionId) {
        try {
            return await this._promoteHistorySessionIfNeeded(paneId, sessionId);
        } catch (error) {
            console.error('Failed to continue history session:', error);
            this.app.showToast(error.message || 'Failed to continue history session', 'error');
            return null;
        }
    }

    async _promoteHistorySessionFallback(meta, sessionId, projectPath, execUser) {
        const providerKey = (meta?.alias || meta?.provider || 'claude').trim() || 'claude';
        const cfg = this.app.getAliasConfigPath(providerKey);
        const historyDetail = await NexusAPI.getHistoryMessages(providerKey, sessionId, {
            execUser,
            configPath: cfg || undefined,
        });
        const bootstrapContext = this._buildBootstrapContextFromHistoryMessages(historyDetail?.messages || [], 'windowed');
        const runtimeSessionId = `chat_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;

        this.promotedRuntimeMeta[runtimeSessionId] = {
            id: runtimeSessionId,
            thread_id: runtimeSessionId,
            title: (meta?.title || `History: ${sessionId}`),
            username: execUser,
            exec_user: execUser,
            provider: (meta?.provider || providerKey || 'claude').toLowerCase(),
            alias: providerKey,
            exec_dir: projectPath || meta?.exec_dir || meta?.work_dir || undefined,
            work_dir: projectPath || meta?.exec_dir || meta?.work_dir || undefined,
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
        const projectPath = String(meta?.exec_dir || meta?.work_dir || '').trim();
        const globalUserFilter = document.getElementById('globalUserFilter');
        const execUser = globalUserFilter?.value || NexusAPI.getDefaultExecUser();

        if (!providerKey) {
            throw new Error('History session provider is missing');
        }

        let runtimeSessionId = '';
        let usedFallback = false;
        let lastError = null;

        try {
            const promoted = await NexusAPI.resumeHistorySession(providerKey, sessionId, {
                projectPath: projectPath || undefined,
                execUser,
                mode: 'full',
            });
            runtimeSessionId = promoted?.runtime_session_id || '';
        } catch (error) {
            lastError = error;
            try {
                const bound = await NexusAPI.bindHistorySession(providerKey, sessionId, {
                    projectPath: projectPath || undefined,
                    execUser,
                    mode: 'full',
                });
                runtimeSessionId = bound?.runtime_session_id || '';
            } catch (bindError) {
                lastError = bindError;
                try {
                    const promoted = await NexusAPI.continueHistorySession(providerKey, sessionId, {
                        projectPath: projectPath || undefined,
                        execUser,
                        mode: 'full',
                    });
                    runtimeSessionId = promoted?.runtime_session_id || '';
                } catch (legacyError) {
                    lastError = legacyError;
                    const fallback = await this._promoteHistorySessionFallback(meta, sessionId, projectPath, execUser);
                    runtimeSessionId = fallback.runtimeSessionId;
                    usedFallback = fallback.usedFallback;
                }
            }
        }

        if (!runtimeSessionId) {
            throw lastError || new Error('Continue history session failed: missing runtime session id');
        }

        // Switch current pane to runtime source and bind active tab to new runtime session.
        this.sessionSource[paneId] = 'runtime';
        this._setCurrentSessionForPane(paneId, runtimeSessionId, 'runtime');

        if (!usedFallback) {
            await this.loadSessions(paneId);
            await this.loadMessages(paneId, runtimeSessionId, { source: 'runtime' });
        }

        if (usedFallback) {
            this.app.showToast('当前服务暂不支持继续历史会话接口，已自动使用兼容续聊模式', 'info');
        }

        return runtimeSessionId;
    }

    async sendMessage(paneId, sessionId, message) {
        if (!message.trim()) return;
        console.log('[sendMessage] START', { paneId, sessionId, message: message.substring(0, 50) });

        if ((this.sessionSource[paneId] || '').toLowerCase() === 'history') {
            this.app.showToast('History is read-only. Use Continue to create a live session.', 'warning');
            return;
        }

        if (!document.getElementById(`chatMessages-${paneId}`)) {
            console.error('[sendMessage] chatMessages container not found for pane', paneId);
            return;
        }

        const effectiveSessionId = sessionId;

        // Re-acquire DOM refs after switching to the continued runtime session
        const textarea = document.getElementById(`chatInput-${paneId}`);
        const sendBtn = document.querySelector(`.chat-send-btn[data-pane="${paneId}"]`);
        const messagesContainer = document.getElementById(`chatMessages-${paneId}`);
        if (!messagesContainer) return;

        // Clear input and disable
        if (textarea) {
            this._resetChatInput(textarea);
            textarea.disabled = true;
            textarea.dataset.sessionId = effectiveSessionId;
        }
        if (sendBtn) {
            sendBtn.disabled = true;
            sendBtn.dataset.sessionId = effectiveSessionId;
        }

        // Add user message to UI immediately (must match renderMessage structure)
        const userTimeStr = this.formatTime(Date.now());
        const isSlashCmd = message.trim().startsWith('/') && !message.trim().startsWith('// ');
        const userMsgHtml = isSlashCmd
            ? `
            <div class="message user slash-command-message">
                <div class="message-avatar">U</div>
                <div class="message-content">
                    <div class="message-bubble"><div class="message-text"><span class="slash-cmd-badge">CMD</span> ${this.formatMessageContent(message)}</div></div>
                    <span class="message-time">${userTimeStr}</span>
                </div>
            </div>
            `
            : `
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
        const thinkingHtml = isSlashCmd
            ? `
            <div class="message assistant" id="${thinkingId}">
                <div class="message-avatar">A</div>
                <div class="message-content">
                    <div class="thinking-indicator">
                        <span class="slash-exec-label">Executing ${this.escapeHtml(message.trim().split(/\s+/)[0])}...</span>
                        <span class="thinking-dot"></span>
                        <span class="thinking-dot"></span>
                        <span class="thinking-dot"></span>
                    </div>
                </div>
            </div>
            `
            : `
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

            // 发完消息后把 sessions/historySessions 列表缓存失效：
            // - runtime 列表的 updated_at / 预览文本会变
            // - 对 Continue 出来的会话来说，CLI 会通过 --resume 把新消息追加写回
            //   原始 JSONL，所以 History 列表里的 updated_at / msg_count 也会变。
            // 不强制立刻重拉（避免一次发消息就触发全量冷扫 1500+ JSONL），
            // 只打标记——用户下次切回相应面板时会自动重新拉取。
            try {
                this._dataStore?.invalidate('sessions', 'historySessions');
            } catch (_) { /* non-fatal */ }
        }
    }

    async streamMessage(paneId, sessionId, message, thinkingId) {
        const sessionMeta = this.getSessionMeta(paneId, sessionId);
        const globalUserFilter = document.getElementById('globalUserFilter');
        const execUser = sessionMeta?.username || globalUserFilter?.value || NexusAPI.getDefaultExecUser();
        const provider = (sessionMeta?.provider || '').trim();
        const alias = (sessionMeta?.alias || provider || '').trim();
        const workspace = String(sessionMeta?.exec_dir || sessionMeta?.work_dir || '').trim();

        let outboundMessage = message;
        const bootstrapContext = this.pendingBootstrapBySessionId[sessionId];
        if (bootstrapContext && !String(message || '').trim().startsWith('/')) {
            outboundMessage = `[History Bootstrap Context]\n\n以下是从历史会话提取的上下文摘要（兼容回退模式，非全量注入）：\n\n${bootstrapContext}\n\n---\n\n请基于以上上下文继续对话。\n\n用户的当前请求：\n${message}`;
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
                    <div class="tool-call-standalone-header" data-action="toggle-tool-call">
                        <div class="tool-call-standalone-status status-${status}">
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
                                    <button class="tool-call-standalone-copy-btn" type="button" data-action="copy-tool-call" data-copy-target="${toolId}-args">
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
                                    <button class="tool-call-standalone-copy-btn" type="button" data-action="copy-tool-call" data-copy-target="${toolId}-result">
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
                                    <span class="tool-call-standalone-section-title is-error">
                                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                        </svg>
                                        Error
                                    </span>
                                    <button class="tool-call-standalone-copy-btn" type="button" data-action="copy-tool-call" data-copy-target="${toolId}-error">
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
                <div class="tool-call-header" data-action="toggle-tool-call">
                    <div class="tool-call-status status-${status}">
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
                                <button class="tool-call-copy-btn" type="button" data-action="copy-tool-call" data-copy-target="${toolId}-args">
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
                                <button class="tool-call-copy-btn" type="button" data-action="copy-tool-call" data-copy-target="${toolId}-result">
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
                                <span class="tool-call-section-title is-error">Error</span>
                                <button class="tool-call-copy-btn" type="button" data-action="copy-tool-call" data-copy-target="${toolId}-error">
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
            this._clearCurrentSessionForPane(paneId, this.sessionSource[paneId] || 'runtime');
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
                fetchBtn.classList.add('is-busy');
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
                fetchBtn.classList.remove('is-busy');
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
            selectionActions.classList.toggle('is-visible', this.selectionMode[paneId]);
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
// Main Application
// ============================================================
class AgentsPage {
    constructor(app) {
        this.app = app;
        this.root = document.getElementById('agentsPageRoot');
        this.summary = document.getElementById('agentsSummary');
        this.directoryPanel = document.getElementById('agentsDirectoryPanel');
        this.activityPanel = document.getElementById('agentsActivityPanel');
        this.memoryPanel = document.getElementById('agentsMemoryPanel');
        this.schedulingPanel = document.getElementById('agentsSchedulingPanel');
        this.sectionMap = {
            directory: document.getElementById('agentsSectionDirectory'),
            activity: document.getElementById('agentsSectionActivity'),
            memory: document.getElementById('agentsSectionMemory'),
            scheduling: document.getElementById('agentsSectionScheduling'),
        };
        this.navButtons = Array.from(document.querySelectorAll('[data-agents-nav]'));
        this._refreshPromise = null;
        this.bindEvents();
        this.setActiveNav('directory');
    }

    bindEvents() {
        this.navButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                this.scrollToSection(btn.dataset.agentsNav);
            });
        });
    }

    _esc(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    setActiveNav(sectionKey) {
        this.navButtons.forEach(btn => {
            const isActive = btn.dataset.agentsNav === sectionKey;
            btn.classList.toggle('primary', isActive);
            btn.setAttribute('aria-current', isActive ? 'true' : 'false');
        });
    }

    scrollToSection(sectionKey) {
        const key = String(sectionKey || 'directory').trim().toLowerCase();
        const section = this.sectionMap[key];
        if (!section) return;
        this.setActiveNav(key);
        section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    refresh() {
        if (this._refreshPromise) {
            return this._refreshPromise;
        }

        this._refreshPromise = this._refresh().finally(() => {
            this._refreshPromise = null;
        });
        return this._refreshPromise;
    }

    async _refresh() {
        if (!this.root) return;

        this.renderSummary();
        await this._renderAdminPanel('renderAgentsTab', this.directoryPanel);
        await this._renderAdminPanel('renderActivityTab', this.activityPanel);
        await this._renderAdminPanel('renderMemoryTab', this.memoryPanel);
        await this._renderAdminPanel('renderSchedulingTab', this.schedulingPanel);
    }

    renderSummary() {
        if (!this.summary) return;

        const agents = Array.isArray(this.app.availableAgents) ? this.app.availableAgents : [];
        const online = agents.filter(agent => agent?.available).length;
        const providers = this.app.getAllProviders ? this.app.getAllProviders().length : 0;

        this.summary.innerHTML = `
            <div class="admin-cards">
                <div class="admin-card">
                    <div class="admin-card-body">
                        <div class="admin-metric"><span class="admin-metric-label">Registered Agents</span><span class="admin-metric-value">${agents.length}</span></div>
                        <div class="admin-metric"><span class="admin-metric-label">Online Now</span><span class="admin-metric-value admin-metric-value-success">${online}</span></div>
                    </div>
                </div>
                <div class="admin-card">
                    <div class="admin-card-body">
                        <div class="admin-metric"><span class="admin-metric-label">Provider Targets</span><span class="admin-metric-value">${providers}</span></div>
                        <div class="admin-metric"><span class="admin-metric-label">Default Exec User</span><span class="admin-metric-value">${this._esc(this.app.getDefaultExecUser?.() || 'ubuntu')}</span></div>
                    </div>
                </div>
            </div>
        `;
    }

    async _renderAdminPanel(methodName, container) {
        if (!container || !this.app.adminView || typeof this.app.adminView[methodName] !== 'function') {
            return;
        }

        const previousContainer = this.app.adminView.container;
        this.app.adminView.container = container;
        try {
            await this.app.adminView[methodName]();
        } catch (error) {
            container.innerHTML = `<div class="admin-error">${this._esc(error.message || 'Failed to load section')}</div>`;
        } finally {
            this.app.adminView.container = previousContainer;
        }
    }
}

class NexusApp {
    constructor() {
        this.themeManager = new ThemeManager();
        this.chatView = new ChatView(this);
        this.taskBoardPanel = new TaskBoardPanel('task-board', {
            title: 'Task Board',
            icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4',
            refreshMs: 0,
        });
        this.taskFormController = new NexusTaskFormController(this);
        this.tabManager = new TabManager(this);
        this.layoutManager = new LayoutManager(this);
        this.configView = new ConfigView(this);
        this.adminView = new AdminView(this);
        this.settingsPage = new SettingsPage(this);
        this.settingsView = this.settingsPage;
        this.agentsPage = typeof AgentsViewShell === 'function' ? new AgentsViewShell(this) : new AgentsPage(this);
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

        const defaultProviders = ['nexus', 'claude', 'gemini', 'codex', 'codebuddy'];
        
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
        const defaultProviders = ['nexus', 'claude', 'gemini', 'codex', 'codebuddy'];
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
        const defaultProviders = ['nexus', 'claude', 'gemini', 'codex', 'codebuddy'];
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
        
        const defaultProviders = ['nexus', 'claude', 'gemini', 'codex', 'codebuddy'];
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
        return ['nexus', 'claude', 'gemini', 'codex', 'codebuddy'];
    }

    getAllProviders() {
        return [...this.getDefaultProviders(), ...this.getCustomProviderNames()];
    }

    normalizeProviderName(provider) {
        const normalized = String(provider || '').trim().toLowerCase();
        if (!normalized) return '';
        return normalized === 'nanobot' ? 'nexus' : normalized;
    }

    // ============================================================
    // Default Provider Management
    // ============================================================
    getDefaultProvider() {
        const stored = this.normalizeProviderName(localStorage.getItem('nexus-default-provider'));
        const serverDefault = this.normalizeProviderName(this.serverDefaults?.default_provider);
        return stored || serverDefault || 'nexus';
    }

    setDefaultProvider(provider) {
        localStorage.setItem('nexus-default-provider', this.normalizeProviderName(provider));
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
        } else if (currentPage === 'settings' && this.settingsPage) {
            this.settingsPage.refresh();
            const section = this.pageManager.pendingSettingsSection || 'overview';
            window.setTimeout(() => this.settingsPage?.scrollToSection?.(section, { syncUrl: false, replaceUrl: true }), 0);
            this.pageManager.pendingSettingsSection = null;
        } else if (currentPage === 'agents' && this.agentsPage) {
            this.agentsPage.refresh();
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
            if (this.pageManager.currentPage === 'settings' && this.settingsPage) {
                this.settingsPage.refresh();
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

        if (this.pageManager?.currentPage === 'settings' && this.settingsPage) {
            this.settingsPage.refresh();
        }
        if (this.pageManager?.currentPage === 'agents' && this.agentsPage) {
            this.agentsPage.refresh();
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

        if (this.taskFormController) {
            this.taskFormController.bindModalEvents();
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
            this.taskBoardPanel.refreshTasks({ force: true });
        } else if (currentPage === 'agents' && this.agentsPage) {
            this.agentsPage.refresh();
        } else if (currentPage === 'settings' && this.settingsPage) {
            this.settingsPage.refresh();
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
        this.taskFormController?.refreshSelectors?.();
    }

    showCreateTaskModal(mode = 'single') {
        this.taskFormController?.showCreateTaskModal?.(mode);
    }

    async _loadTaskSourceSessionOptions(username) {
        return this.taskFormController?._loadTaskSourceSessionOptions?.(username);
    }

    async parseScheduleNaturalLanguage() {
        return this.taskFormController?.parseScheduleNaturalLanguage?.();
    }

    _updateSubmitButtonText() {
        this.taskFormController?._updateSubmitButtonText?.();
    }

    getTaskAgentSelection() {
        return this.taskFormController?.getTaskAgentSelection?.() || {
            execUser: NexusAPI.getDefaultExecUser(),
            providerSelection: this.getDefaultProvider(),
        };
    }

    resolveProviderSelection(providerSelection) {
        return this.taskFormController?.resolveProviderSelection?.(providerSelection) || {
            provider: this.normalizeProviderName(providerSelection || this.getDefaultProvider() || 'nexus'),
            alias: this.normalizeProviderName(providerSelection || this.getDefaultProvider() || 'nexus'),
        };
    }

    resolveTaskModel(selectedProvider, aliasValue, explicitModel) {
        return this.taskFormController?.resolveTaskModel?.(selectedProvider, aliasValue, explicitModel)
            || explicitModel
            || this.getProviderDefaultModel(aliasValue)
            || this.getProviderDefaultModel(selectedProvider)
            || undefined;
    }

    getLoopConfig() {
        return this.taskFormController?.getLoopConfig?.() || null;
    }

    async submitTask() {
        return this.taskFormController?.submit?.();
    }

    async _submitSingleTask(execUser, providerSelection) {
        return this.taskFormController?._submitSingleTask?.(execUser, providerSelection);
    }

    async _submitSchedule(execUser, providerSelection, triggerMode) {
        return this.taskFormController?._submitSchedule?.(execUser, providerSelection, triggerMode);
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
            <div class="modal modal-compact">
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
                    <p class="modal-note">
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
                username: globalUserFilter?.value || NexusAPI.getDefaultExecUser(),
                exec_dir: this.serverDefaults?.current_workdir || undefined,
                provider: this.getDefaultProvider ? this.getDefaultProvider() : undefined,
                alias: this.getDefaultProvider ? this.getDefaultProvider() : undefined,
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
            toast.classList.add('is-exiting');
            setTimeout(() => toast.remove(), 300);
        }, 5000);
    }

    showAddTabDropdown(btn, paneId) {
        // Simplified: directly add a new chat tab without showing dropdown
        this.tabManager.addTab(paneId, 'chat');
    }

    positionDropdown(dropdown, anchorEl) {
        // Dropdown rendering was simplified out of the shell flow.
        // Preserve the method for compatibility with older call-sites.
        return { dropdown, anchorEl };
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
    if (loginOverlay) loginOverlay.classList.remove('is-hidden');
    if (mainApp) mainApp.classList.add('is-hidden');
}

function showMainApp(authRequired) {
    const loginOverlay = document.getElementById('loginOverlay');
    const mainApp = document.getElementById('app');
    const logoutBtn = document.getElementById('logoutBtn');
    
    if (loginOverlay) loginOverlay.classList.add('is-hidden');
    if (mainApp) mainApp.classList.remove('is-hidden');
    if (logoutBtn) logoutBtn.classList.toggle('is-hidden', !authRequired);
    
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
                    loginError.classList.remove('is-hidden');
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
                    loginError.classList.remove('is-hidden');
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
