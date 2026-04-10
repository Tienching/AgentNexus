/**
 * SSE Handler - Server-Sent Events client with auto-reconnect and message dedup.
 *
 * Wraps the native EventSource API with:
 *  - Typed event dispatching (event type → handler)
 *  - Deduplication within a configurable time window
 *  - Visibility-aware pause/resume
 *  - Exponential backoff on errors
 *
 * Usage:
 *   const sse = new SSEHandler('/api/nexus/events');
 *   sse.on('task.updated', (payload) => { … });
 *   sse.connect();
 */

class SSEHandler {

    /**
     * @param {string} url          SSE endpoint URL
     * @param {Object} [options]
     * @param {number} [options.reconnectDelayMs=2000]     Initial reconnect delay
     * @param {number} [options.maxReconnectDelayMs=30000]  Max reconnect delay
     * @param {number} [options.dedupWindowMs=5000]         De-dup window
     * @param {Object} [options.params]                     Query params to append
     */
    constructor(url, options = {}) {
        this.url = url;
        this.opts = {
            reconnectDelayMs: 2000,
            maxReconnectDelayMs: 30000,
            dedupWindowMs: 5000,
            params: {},
            ...options,
        };

        /** @private @type {EventSource|null} */
        this._es = null;
        /** @private @type {Map<string, Function[]>} event type → handlers */
        this._handlers = new Map();
        /** @private @type {Map<string, number>} dedup */
        this._seen = new Map();
        /** @private */
        this._reconnectDelay = this.opts.reconnectDelayMs;
        /** @private */
        this._reconnectTimer = null;
        /** @private */
        this._connected = false;
        /** @private */
        this._destroyed = false;
        /** @private */
        this._visHandler = this._onVisibilityChange.bind(this);
    }

    // ----------------------------------------------------------
    // Public API
    // ----------------------------------------------------------

    connect() {
        if (this._destroyed) return;
        this._doConnect();
        document.addEventListener('visibilitychange', this._visHandler);
    }

    disconnect() {
        this._cleanup();
        document.removeEventListener('visibilitychange', this._visHandler);
    }

    destroy() {
        this._destroyed = true;
        this.disconnect();
        this._handlers.clear();
        this._seen.clear();
    }

    get connected() {
        return this._connected;
    }

    /**
     * Subscribe to a named SSE event.
     * @param {string} eventType  SSE event name (or '*' for all)
     * @param {Function} handler  (payload: Object) => void
     * @returns {Function} Unsubscribe function
     */
    on(eventType, handler) {
        if (!this._handlers.has(eventType)) {
            this._handlers.set(eventType, []);
        }
        this._handlers.get(eventType).push(handler);
        return () => this.off(eventType, handler);
    }

    off(eventType, handler) {
        const list = this._handlers.get(eventType);
        if (list) {
            const idx = list.indexOf(handler);
            if (idx !== -1) list.splice(idx, 1);
        }
    }

    // ----------------------------------------------------------
    // Internals
    // ----------------------------------------------------------

    /** @private */
    _doConnect() {
        try {
            // Build URL with query params
            const url = new URL(this.url, location.origin);
            for (const [k, v] of Object.entries(this.opts.params || {})) {
                if (v !== undefined && v !== null) url.searchParams.set(k, v);
            }

            this._es = new EventSource(url.toString());

            this._es.onopen = () => {
                this._connected = true;
                this._reconnectDelay = this.opts.reconnectDelayMs;
                this._emit('_connected', {});
            };

            // Listen for specific named events
            // SSE spec: named events come as `event: <name>\ndata: <json>`
            // We also handle the generic 'message' event as fallback
            this._es.addEventListener('message', (event) => {
                this._handleMessage(event);
            });

            // Common Nexus event types — register listeners so the browser
            // dispatches them properly.  Additional types can be added later.
            const knownTypes = [
                'agent.heartbeat', 'agent.registered', 'agent.offline',
                'task.created', 'task.updated', 'task.completed', 'task.failed',
                'skill.synced', 'skill.approved',
                'schedule.triggered', 'schedule.completed',
                'activity.log', 'notification',
                'security.alert', 'security.audit',
                'memory.updated',
            ];
            for (const t of knownTypes) {
                this._es.addEventListener(t, (event) => this._handleMessage(event));
            }

            this._es.onerror = () => {
                this._connected = false;
                this._emit('_disconnected', {});
                // EventSource auto-reconnects, but if it stays in CONNECTING
                // state too long, we force-restart
                this._scheduleReconnect();
            };
        } catch (e) {
            console.error('SSEHandler: connect failed', e);
            this._scheduleReconnect();
        }
    }

    /** @private */
    _handleMessage(event) {
        try {
            const payload = JSON.parse(event.data);
            const eventType = event.type || 'message';
            if (this._isDuplicate(eventType, payload)) return;
            this._emit(eventType, payload);
            this._emit('*', { type: eventType, payload });
        } catch (e) {
            // Non-JSON data — emit as raw string
            this._emit('raw', event.data);
        }
    }

    /** @private */
    _cleanup() {
        clearTimeout(this._reconnectTimer);
        this._reconnectTimer = null;
        if (this._es) {
            this._es.onopen = null;
            this._es.onerror = null;
            this._es.onmessage = null;
            this._es.close();
            this._es = null;
        }
        this._connected = false;
    }

    /** @private */
    _scheduleReconnect() {
        if (this._destroyed) return;
        clearTimeout(this._reconnectTimer);
        this._reconnectTimer = setTimeout(() => {
            // Force close and reconnect
            this._cleanup();
            this._doConnect();
        }, this._reconnectDelay);
        this._reconnectDelay = Math.min(this._reconnectDelay * 2, this.opts.maxReconnectDelayMs);
    }

    /** @private */
    _emit(eventType, payload) {
        const handlers = this._handlers.get(eventType);
        if (handlers) {
            for (const fn of handlers) {
                try { fn(payload); } catch (e) { console.error('SSE handler error:', e); }
            }
        }
    }

    /** @private */
    _isDuplicate(eventType, payload) {
        const key = `${eventType}:${JSON.stringify(payload)}`;
        const now = Date.now();
        for (const [k, ts] of this._seen) {
            if (now - ts > this.opts.dedupWindowMs) this._seen.delete(k);
        }
        if (this._seen.has(key)) return true;
        this._seen.set(key, now);
        return false;
    }

    /** @private */
    _onVisibilityChange() {
        if (document.hidden) {
            // Close SSE — server will buffer if needed
            if (this._es) {
                this._es.close();
                this._connected = false;
            }
        } else {
            // Reconnect
            if (!this._connected && !this._destroyed) {
                clearTimeout(this._reconnectTimer);
                this._cleanup();
                this._doConnect();
            }
        }
    }
}

window.SSEHandler = SSEHandler;
