/**
 * WebSocket Manager - Persistent WebSocket connection with auto-reconnect,
 * visibility-aware pause/resume, and message deduplication.
 *
 * Usage:
 *   const ws = new WebSocketManager('/api/nexus/ws');
 *   ws.on('agent.heartbeat', (payload) => { … });
 *   ws.on('task.updated',   (payload) => { … });
 *   ws.connect();
 */

class WebSocketManager {

    /**
     * @param {string} url          WebSocket endpoint URL (ws:// or wss://)
     * @param {Object} [options]
     * @param {number} [options.reconnectDelayMs=2000]    Initial reconnect delay
     * @param {number} [options.maxReconnectDelayMs=30000] Max reconnect delay (exponential backoff cap)
     * @param {number} [options.heartbeatMs=30000]         Ping interval to keep connection alive
     * @param {number} [options.dedupWindowMs=5000]        De-duplicate messages within this window
     */
    constructor(url, options = {}) {
        this.url = url;
        this.opts = {
            reconnectDelayMs: 2000,
            maxReconnectDelayMs: 30000,
            heartbeatMs: 30000,
            dedupWindowMs: 5000,
            ...options,
        };

        /** @private @type {WebSocket|null} */
        this._ws = null;
        /** @private @type {Map<string, Function[]>} event type → handlers */
        this._handlers = new Map();
        /** @private @type {Map<string, number>} msg hash → timestamp for dedup */
        this._seen = new Map();
        /** @private */
        this._reconnectDelay = this.opts.reconnectDelayMs;
        /** @private */
        this._reconnectTimer = null;
        /** @private */
        this._heartbeatTimer = null;
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

    /** Open the WebSocket connection. */
    connect() {
        if (this._destroyed) return;
        this._doConnect();
        document.addEventListener('visibilitychange', this._visHandler);
    }

    /** Disconnect and stop reconnecting. */
    disconnect() {
        this._cleanup();
        document.removeEventListener('visibilitychange', this._visHandler);
    }

    /** Permanently tear down. */
    destroy() {
        this._destroyed = true;
        this.disconnect();
        this._handlers.clear();
        this._seen.clear();
    }

    /** Whether the socket is currently open. */
    get connected() {
        return this._connected;
    }

    /**
     * Subscribe to events of a given type.
     * @param {string} eventType  e.g. 'agent.heartbeat'
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

    /**
     * Unsubscribe a handler.
     * @param {string} eventType
     * @param {Function} handler
     */
    off(eventType, handler) {
        const list = this._handlers.get(eventType);
        if (list) {
            const idx = list.indexOf(handler);
            if (idx !== -1) list.splice(idx, 1);
        }
    }

    /**
     * Send a message over the WebSocket.
     * @param {string} type    Event type
     * @param {Object} payload Data
     */
    send(type, payload = {}) {
        if (this._ws && this._ws.readyState === WebSocket.OPEN) {
            this._ws.send(JSON.stringify({ type, payload, ts: Date.now() }));
        }
    }

    // ----------------------------------------------------------
    // Internals
    // ----------------------------------------------------------

    /** @private */
    _doConnect() {
        try {
            // Resolve URL — if relative, build from current origin
            let url = this.url;
            if (!url.startsWith('ws')) {
                const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
                url = `${proto}//${location.host}${url}`;
            }

            this._ws = new WebSocket(url);

            this._ws.onopen = () => {
                this._connected = true;
                this._reconnectDelay = this.opts.reconnectDelayMs;
                this._startHeartbeat();
                this._emit('_connected', {});
            };

            this._ws.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    if (this._isDuplicate(msg)) return;
                    this._emit(msg.type || 'unknown', msg.payload || msg);
                    // Also emit wildcard
                    this._emit('*', msg);
                } catch (e) {
                    console.warn('WebSocketManager: failed to parse message', e);
                }
            };

            this._ws.onclose = (event) => {
                this._connected = false;
                this._stopHeartbeat();
                this._emit('_disconnected', { code: event.code, reason: event.reason });
                if (!this._destroyed && !event.wasClean) {
                    this._scheduleReconnect();
                }
            };

            this._ws.onerror = () => {
                // onclose will fire after onerror, so reconnect logic lives there
            };
        } catch (e) {
            console.error('WebSocketManager: connect failed', e);
            this._scheduleReconnect();
        }
    }

    /** @private */
    _cleanup() {
        this._stopHeartbeat();
        clearTimeout(this._reconnectTimer);
        this._reconnectTimer = null;
        if (this._ws) {
            this._ws.onopen = null;
            this._ws.onmessage = null;
            this._ws.onclose = null;
            this._ws.onerror = null;
            try { this._ws.close(1000, 'client disconnect'); } catch {}
            this._ws = null;
        }
        this._connected = false;
    }

    /** @private */
    _scheduleReconnect() {
        if (this._destroyed) return;
        clearTimeout(this._reconnectTimer);
        this._reconnectTimer = setTimeout(() => {
            this._doConnect();
        }, this._reconnectDelay);
        // Exponential backoff
        this._reconnectDelay = Math.min(this._reconnectDelay * 2, this.opts.maxReconnectDelayMs);
    }

    /** @private */
    _startHeartbeat() {
        this._stopHeartbeat();
        this._heartbeatTimer = setInterval(() => {
            this.send('ping', {});
        }, this.opts.heartbeatMs);
    }

    /** @private */
    _stopHeartbeat() {
        if (this._heartbeatTimer) {
            clearInterval(this._heartbeatTimer);
            this._heartbeatTimer = null;
        }
    }

    /** @private */
    _emit(eventType, payload) {
        const handlers = this._handlers.get(eventType);
        if (handlers) {
            for (const fn of handlers) {
                try { fn(payload); } catch (e) { console.error('WS handler error:', e); }
            }
        }
    }

    /** @private — simple hash-based dedup within the time window */
    _isDuplicate(msg) {
        const key = `${msg.type}:${JSON.stringify(msg.payload)}`;
        const now = Date.now();
        // Prune old entries
        for (const [k, ts] of this._seen) {
            if (now - ts > this.opts.dedupWindowMs) this._seen.delete(k);
        }
        if (this._seen.has(key)) return true;
        this._seen.set(key, now);
        return false;
    }

    /** @private — pause/resume based on page visibility */
    _onVisibilityChange() {
        if (document.hidden) {
            // Page hidden — close WS to save resources
            if (this._ws && this._ws.readyState === WebSocket.OPEN) {
                this._ws.close(1000, 'page hidden');
            }
        } else {
            // Page visible — reconnect if not already connected
            if (!this._connected && !this._destroyed) {
                clearTimeout(this._reconnectTimer);
                this._doConnect();
            }
        }
    }
}

window.WebSocketManager = WebSocketManager;
