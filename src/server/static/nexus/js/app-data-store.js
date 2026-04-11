/**
 * AppDataStore - Centralized data cache layer for Nexus UI.
 *
 * Eliminates redundant API calls by providing a single source of truth
 * with subscriber-based reactivity, TTL-based cache invalidation, and
 * an event bus for broadcasting data changes.
 *
 * Usage:
 *   const store = AppDataStore.getInstance();
 *   store.subscribe('tasks', (data) => { ... });
 *   store.fetch('tasks');               // triggers API call if cache is stale
 *   store.invalidate('tasks');          // force next fetch to hit network
 *   store.unsubscribe('tasks', cb);
 */

class AppDataStore {
    /** @type {AppDataStore|null} */
    static _instance = null;

    /** @returns {AppDataStore} */
    static getInstance() {
        if (!AppDataStore._instance) {
            AppDataStore._instance = new AppDataStore();
        }
        return AppDataStore._instance;
    }

    constructor() {
        /** @type {Map<string, any>} cached data by key */
        this._cache = new Map();

        /** @type {Map<string, number>} timestamp of last successful fetch */
        this._timestamps = new Map();

        /** @type {Map<string, Set<Function>>} subscribers by key */
        this._subscribers = new Map();

        /** @type {Map<string, Promise>} in-flight fetch promises to dedup */
        this._pending = new Map();

        /** @type {Map<string, Object>} last fetch options per key, for re-fetch */
        this._lastOpts = new Map();

        // Default TTL per data source (ms). 0 = no auto-expiry.
        this._ttl = {
            tasks:        15000,   // 15s
            sessions:     20000,   // 20s
            agents:       60000,   // 60s
            schedules:    30000,   // 30s
            diagnostics:  30000,   // 30s
            activities:   20000,   // 20s
            defaults:     120000,  // 2min - rarely changes
            usernames:    60000,   // 60s
            skills:       60000,   // 60s
            projects:     60000,   // 60s
            runtimes:     60000,   // 60s
            security:     60000,   // 60s
            workload:     30000,   // 30s
            audit:        30000,   // 30s
        };

        // Data source fetchers — each returns a Promise
        this._fetchers = {
            tasks:       (opts) => NexusAPI.getTasks(opts),
            sessions:    (opts) => NexusAPI.getSessions(opts),
            agents:      ()     => NexusAPI.getAgents(),
            schedules:   (opts) => NexusAPI.getSchedules(opts),
            diagnostics: ()     => NexusAPI.getDiagnostics(),
            activities:  ()     => NexusAPI.getStandup(),
            defaults:    ()     => NexusAPI.getDefaults(),
            usernames:   ()     => NexusAPI.getUsernames(),
            skills:      (opts) => NexusAPI.getSkills(opts),
            projects:    (opts) => NexusAPI.getProjects(opts),
            runtimes:    (opts) => NexusAPI.getAgentRuntimes(opts?.runtimeId),
            security:    ()     => NexusAPI.getSecurityScan(),
            workload:    ()     => NexusAPI.getWorkload(),
            audit:       (opts) => NexusAPI.getAuditLog(opts),
        };
    }

    // ------------------------------------------------------------------
    // Subscriber API
    // ------------------------------------------------------------------

    /**
     * Subscribe to changes on a data key.
     * The callback is invoked immediately if cached data exists and is fresh.
     * @param {string} key   Data source key (e.g. 'tasks')
     * @param {Function} cb  Callback receiving (data, key)
     */
    subscribe(key, cb) {
        if (typeof cb !== 'function') return;
        if (!this._subscribers.has(key)) {
            this._subscribers.set(key, new Set());
        }
        this._subscribers.get(key).add(cb);

        // Immediately deliver cached value if fresh
        if (this._cache.has(key) && !this._isStale(key)) {
            try { cb(this._cache.get(key), key); } catch (e) {
                console.error(`[AppDataStore] subscriber error on '${key}':`, e);
            }
        }
    }

    /**
     * Unsubscribe a previously registered callback.
     * @param {string} key
     * @param {Function} cb
     */
    unsubscribe(key, cb) {
        const subs = this._subscribers.get(key);
        if (subs) {
            subs.delete(cb);
            if (subs.size === 0) this._subscribers.delete(key);
        }
    }

    /**
     * Get the number of active subscribers for a key.
     * @param {string} key
     * @returns {number}
     */
    subscriberCount(key) {
        return this._subscribers.has(key) ? this._subscribers.get(key).size : 0;
    }

    // ------------------------------------------------------------------
    // Fetch / Cache API
    // ------------------------------------------------------------------

    /**
     * Fetch data for a key. Returns cached data if still fresh.
     * Deduplicates concurrent calls for the same key.
     *
     * @param {string} key           Data source key
     * @param {Object} [opts]        Options forwarded to the fetcher
     * @param {boolean} [opts.force] Force bypass cache
     * @returns {Promise<any>}
     */
    async fetch(key, opts = {}) {
        const force = opts.force;

        // Return cache if fresh and not forced
        if (!force && this._cache.has(key) && !this._isStale(key)) {
            return this._cache.get(key);
        }

        // Dedup: if a fetch for this key is already in-flight, return that promise
        if (this._pending.has(key)) {
            return this._pending.get(key);
        }

        const fetcher = this._fetchers[key];
        if (!fetcher) {
            throw new Error(`[AppDataStore] Unknown data source: '${key}'`);
        }

        // Strip internal flags before passing to fetcher
        const fetchOpts = { ...opts };
        delete fetchOpts.force;
        this._lastOpts.set(key, fetchOpts);

        const promise = fetcher(fetchOpts)
            .then(data => {
                this._cache.set(key, data);
                this._timestamps.set(key, Date.now());
                this._pending.delete(key);
                this._notify(key, data);
                return data;
            })
            .catch(err => {
                this._pending.delete(key);
                throw err;
            });

        this._pending.set(key, promise);
        return promise;
    }

    /**
     * Get cached data synchronously (may be stale or undefined).
     * @param {string} key
     * @returns {any|undefined}
     */
    get(key) {
        return this._cache.get(key);
    }

    /**
     * Check if cached data exists and is still within TTL.
     * @param {string} key
     * @returns {boolean}
     */
    isFresh(key) {
        return this._cache.has(key) && !this._isStale(key);
    }

    /**
     * Manually set data in the cache (e.g. after a mutation).
     * Broadcasts to subscribers.
     * @param {string} key
     * @param {any} data
     */
    set(key, data) {
        this._cache.set(key, data);
        this._timestamps.set(key, Date.now());
        this._notify(key, data);
    }

    /**
     * Invalidate cache for one or more keys. Next fetch() will hit network.
     * @param {...string} keys  Keys to invalidate; if empty, invalidate all
     */
    invalidate(...keys) {
        const targets = keys.length > 0 ? keys : [...this._cache.keys()];
        for (const key of targets) {
            this._timestamps.delete(key);
        }
    }

    /**
     * Invalidate and immediately re-fetch a key, notifying subscribers.
     * @param {string} key
     * @param {Object} [opts]
     * @returns {Promise<any>}
     */
    async refresh(key, opts) {
        this.invalidate(key);
        const fetchOpts = opts || this._lastOpts.get(key) || {};
        return this.fetch(key, { ...fetchOpts, force: true });
    }

    /**
     * Clear all caches and subscribers (for logout / teardown).
     */
    clear() {
        this._cache.clear();
        this._timestamps.clear();
        this._pending.clear();
        this._lastOpts.clear();
        // Don't clear subscribers — they re-attach on next init
    }

    // ------------------------------------------------------------------
    // TTL configuration
    // ------------------------------------------------------------------

    /**
     * Override TTL for a specific key.
     * @param {string} key
     * @param {number} ms  TTL in milliseconds (0 = always stale)
     */
    setTTL(key, ms) {
        this._ttl[key] = ms;
    }

    /**
     * Get the configured TTL for a key.
     * @param {string} key
     * @returns {number}
     */
    getTTL(key) {
        return this._ttl[key] ?? 30000; // default 30s
    }

    // ------------------------------------------------------------------
    // Event bus: onChange
    // ------------------------------------------------------------------

    /**
     * Register a global listener that fires for *any* data change.
     * @param {Function} cb  Callback receiving (key, data)
     * @returns {Function}   Unsubscribe function
     */
    onChange(cb) {
        if (typeof cb !== 'function') return () => {};
        if (!this._globalListeners) this._globalListeners = new Set();
        this._globalListeners.add(cb);
        return () => this._globalListeners.delete(cb);
    }

    // ------------------------------------------------------------------
    // Internal helpers
    // ------------------------------------------------------------------

    /** @private */
    _isStale(key) {
        const ts = this._timestamps.get(key);
        if (ts == null) return true;
        const ttl = this._ttl[key] ?? 30000;
        if (ttl <= 0) return true;
        return Date.now() - ts > ttl;
    }

    /** @private Notify key-specific + global listeners */
    _notify(key, data) {
        const subs = this._subscribers.get(key);
        if (subs) {
            for (const cb of subs) {
                try { cb(data, key); } catch (e) {
                    console.error(`[AppDataStore] subscriber error on '${key}':`, e);
                }
            }
        }
        if (this._globalListeners) {
            for (const cb of this._globalListeners) {
                try { cb(key, data); } catch (e) {
                    console.error('[AppDataStore] global listener error:', e);
                }
            }
        }
    }
}

// Export as global
window.AppDataStore = AppDataStore;
