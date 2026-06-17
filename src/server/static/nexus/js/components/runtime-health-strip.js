/**
 * RuntimeHealthStrip — a compact runtime liveness indicator for the task board.
 *
 * Phase 6 kanban/UX improvement: surfaces the daemon fleet's health (online /
 * offline / relay runtimes) pulled from /api/nexus/runtimes/daemons, so the
 * board reflects the multi-machine aggregation established in Phase 4-5.
 *
 * Rendered as small badges; clicking an online runtime filters the board to
 * tasks assigned to it. Fails silently (renders nothing) if the API is
 * unavailable so the board stays usable standalone.
 */
class RuntimeHealthStrip {
    constructor(options = {}) {
        this.onClick = options.onClick || null;
        this._cache = null;
        this._cacheAt = 0;
        this._ttl = 15000; // refresh every 15s (matches daemon heartbeat interval)
    }

    async _fetch() {
        const now = Date.now();
        if (this._cache && (now - this._cacheAt) < this._ttl) return this._cache;
        try {
            const data = await (typeof NexusAPI !== 'undefined' && NexusAPI.listRuntimeDaemons
                ? NexusAPI.listRuntimeDaemons()
                : Promise.resolve(null));
            this._cache = data;
            this._cacheAt = now;
            return data;
        } catch (e) {
            return null;
        }
    }

    _summarize(daemons) {
        const summary = { online: 0, offline: 0, local: 0, relay: 0, byProvider: {} };
        for (const d of (daemons || [])) {
            const status = String(d.status || '').toLowerCase();
            const mode = String(d.runtime_mode || 'local').toLowerCase();
            const fresh = this._isFresh(d);
            if (fresh) summary.online += 1; else summary.offline += 1;
            if (mode === 'relay') summary.relay += 1; else summary.local += 1;
            const provider = d.provider || 'unknown';
            if (!summary.byProvider[provider]) summary.byProvider[provider] = { online: 0, offline: 0 };
            if (fresh) summary.byProvider[provider].online += 1;
            else summary.byProvider[provider].offline += 1;
        }
        return summary;
    }

    _isFresh(daemon) {
        const hb = Number(daemon.last_heartbeat || 0);
        if (!hb) return String(daemon.status || '').toLowerCase() !== 'offline';
        // freshness window = 2x heartbeat interval (30s)
        return (Date.now() / 1000 - hb) < 30;
    }

    async render(container) {
        if (!container) return;
        const data = await this._fetch();
        const daemons = (data && (data.daemons || data)) || [];
        if (!daemons.length) { container.innerHTML = ''; return; }
        const s = this._summarize(daemons);
        const dot = (on) => `<span class="runtime-health-dot ${on ? 'is-online' : 'is-offline'}"></span>`;
        const badges = Object.entries(s.byProvider).map(([provider, counts]) => {
            const total = counts.online + counts.offline;
            const on = counts.online > 0;
            return `<button class="runtime-health-badge" data-provider="${this._esc(provider)}" title="${counts.online}/${total} online">${dot(on)}<span class="runtime-health-label">${this._esc(provider)}</span><span class="runtime-health-count">${counts.online}</span></button>`;
        }).join('');
        const modeBadge = s.relay > 0
            ? `<span class="runtime-health-mode" title="relay runtimes forwarded from downstream daemons">relay:${s.relay}</span>`
            : '';
        container.innerHTML = `<div class="runtime-health-strip">${badges}${modeBadge}</div>`;
        // wire click handlers
        container.querySelectorAll('.runtime-health-badge').forEach((btn) => {
            btn.addEventListener('click', () => {
                const provider = btn.getAttribute('data-provider');
                if (this.onClick) this.onClick(provider);
            });
        });
    }

    _esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }
}

// Expose globally (no module system in the static UI bundle).
window.RuntimeHealthStrip = RuntimeHealthStrip;
