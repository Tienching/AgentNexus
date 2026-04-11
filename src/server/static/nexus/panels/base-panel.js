/**
 * BasePanel - Abstract base class for all Nexus panels.
 *
 * Subclasses MUST override: render()
 * Subclasses MAY override: init(), refresh(), destroy(), onResize(), onRealtimeEvent()
 *
 * Lifecycle:
 *   constructor(id, def, opts) → init() → render(container) → refresh() / onResize() / onRealtimeEvent() → destroy()
 *
 * Data layer:
 *   Panels access data through AppDataStore subscriptions instead of direct API calls.
 *   Use this.subscribeData(key, cb) in init() and the base class handles cleanup in destroy().
 */

class BasePanel {
    /**
     * @param {string} id       Panel unique id (e.g. 'agent-registry')
     * @param {Object} def      Panel definition from registry
     * @param {Object} [opts]   Runtime options
     * @param {HTMLElement} [opts.container]  Host element (set later via render)
     */
    constructor(id, def, opts = {}) {
        this.id = id;
        this.def = def;
        this.opts = opts;
        this.container = null;
        this._initialized = false;
        this._destroyed = false;
        this._refreshTimer = null;
        this._poll = null;  // SmartPoll instance if auto-refresh enabled

        /** @type {Array<{key: string, cb: Function}>} tracked data subscriptions */
        this._dataSubscriptions = [];
    }

    // ----------------------------------------------------------
    // Lifecycle hooks (override in subclass)
    // ----------------------------------------------------------

    /**
     * Called once after construction.  Fetch initial data, set up listeners.
     * Override to add custom async initialisation.
     */
    async init() {
        this._initialized = true;
        // Start auto-refresh if configured
        if (this.def.refreshMs > 0 && typeof SmartPoll !== 'undefined') {
            this._poll = new SmartPoll(() => this.refresh(), { intervalMs: this.def.refreshMs });
            this._poll.start();
        }
    }

    /**
     * Render the panel's DOM into the given container.
     * MUST be overridden by every subclass.
     *
     * @param {HTMLElement} container
     */
    render(container) {
        this.container = container;
        // Default: show a placeholder. Subclasses override this.
        container.innerHTML = `
            <div class="panel-placeholder">
                <div class="panel-placeholder-icon">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="32" height="32">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                              d="${this.def.icon || 'M4 6h16M4 12h16M4 18h16'}"/>
                    </svg>
                </div>
                <h3 class="panel-placeholder-title">${this._escapeHtml(this.def.title)}</h3>
                <p class="panel-placeholder-hint">Panel not yet implemented</p>
            </div>
        `;
    }

    /**
     * Refresh the panel's data and re-render.
     * Default implementation just re-calls render() if container exists.
     */
    async refresh() {
        if (this.container && !this._destroyed) {
            this.render(this.container);
        }
    }

    /**
     * Clean up: stop timers, remove listeners, release references.
     */
    async destroy() {
        this._destroyed = true;
        if (this._poll) {
            this._poll.destroy();
            this._poll = null;
        }
        if (this._refreshTimer) {
            clearInterval(this._refreshTimer);
            this._refreshTimer = null;
        }
        // Unsubscribe all data store subscriptions
        this._unsubscribeAll();
        this.container = null;
    }

    /**
     * Called when the panel's container is resized.
     * Override for responsive layout adjustments.
     */
    onResize() {
        // no-op by default
    }

    /**
     * Handle a real-time event from WebSocket / SSE.
     * @param {string} eventType  e.g. 'agent.heartbeat', 'task.updated'
     * @param {Object} payload    Event data
     */
    onRealtimeEvent(eventType, payload) {
        // no-op by default — panels opt-in to real-time updates
    }

    // ----------------------------------------------------------
    // Data Store integration
    // ----------------------------------------------------------

    /**
     * Get the shared AppDataStore instance.
     * @returns {AppDataStore}
     */
    get store() {
        return window.AppDataStore?.getInstance();
    }

    /**
     * Subscribe to a data key in AppDataStore.
     * The subscription is automatically cleaned up in destroy().
     *
     * @param {string} key   Data source key (e.g. 'tasks', 'sessions')
     * @param {Function} cb  Callback receiving (data, key)
     */
    subscribeData(key, cb) {
        const store = this.store;
        if (!store) return;
        store.subscribe(key, cb);
        this._dataSubscriptions.push({ key, cb });
    }

    /**
     * Fetch data from the store (with caching / dedup).
     * @param {string} key
     * @param {Object} [opts]
     * @returns {Promise<any>}
     */
    fetchData(key, opts) {
        const store = this.store;
        if (!store) return this.api[`get${key.charAt(0).toUpperCase() + key.slice(1)}`]?.(opts);
        return store.fetch(key, opts);
    }

    /**
     * Invalidate cached data and refresh from network.
     * @param {string} key
     * @param {Object} [opts]
     * @returns {Promise<any>}
     */
    refreshData(key, opts) {
        const store = this.store;
        if (!store) return this.fetchData(key, opts);
        return store.refresh(key, opts);
    }

    /** @private Unsubscribe all tracked data subscriptions */
    _unsubscribeAll() {
        const store = this.store;
        if (!store) return;
        for (const { key, cb } of this._dataSubscriptions) {
            store.unsubscribe(key, cb);
        }
        this._dataSubscriptions = [];
    }

    // ----------------------------------------------------------
    // Helpers available to subclasses
    // ----------------------------------------------------------

    /**
     * Shorthand for NexusAPI calls.
     * @returns {typeof NexusAPI}
     */
    get api() {
        return window.NexusAPI;
    }

    /**
     * Show a loading spinner in the container.
     */
    showLoading() {
        if (!this.container) return;
        this.container.innerHTML = `
            <div class="panel-loading">
                <div class="spinner"></div>
                <span>Loading...</span>
            </div>
        `;
    }

    /**
     * Show an error message in the container.
     * @param {string} msg
     */
    showError(msg) {
        if (!this.container) return;
        this.container.innerHTML = `
            <div class="panel-error">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="20" height="20">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                          d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
                <span>${this._escapeHtml(msg)}</span>
            </div>
        `;
    }

    /**
     * Show an empty-state message.
     * @param {string} msg
     */
    showEmpty(msg = 'No data') {
        if (!this.container) return;
        this.container.innerHTML = `
            <div class="panel-empty">
                <span>${this._escapeHtml(msg)}</span>
            </div>
        `;
    }

    /**
     * Escape HTML special characters.
     * @param {string} str
     * @returns {string}
     */
    _escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = str || '';
        return d.innerHTML;
    }

    /**
     * Create a panel header bar with title, optional actions, and refresh button.
     * @param {Object} [opts]
     * @param {string} [opts.actions]  HTML for action buttons
     * @returns {string} HTML string
     */
    _headerHtml(opts = {}) {
        return `
            <div class="panel-header">
                <div class="panel-header-title">
                    <svg class="panel-header-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24" width="18" height="18">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                              d="${this.def.icon || 'M4 6h16M4 12h16M4 18h16'}"/>
                    </svg>
                    <h3>${this._escapeHtml(this.def.title)}</h3>
                </div>
                <div class="panel-header-actions">
                    ${opts.actions || ''}
                    <button class="panel-btn panel-refresh-btn" data-panel-id="${this.id}" title="Refresh">
                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="14" height="14">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                        </svg>
                    </button>
                </div>
            </div>
        `;
    }

    /**
     * Bind the refresh button in the header (call after innerHTML is set).
     */
    _bindRefreshBtn() {
        const btn = this.container?.querySelector('.panel-refresh-btn');
        if (btn) {
            btn.addEventListener('click', () => this.refresh());
        }
    }
}

// Export for use in panel modules
window.BasePanel = BasePanel;
