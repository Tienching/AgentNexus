/**
 * AgentHeartbeatPanel - Live agent heartbeat monitoring with status timeline.
 */

class AgentHeartbeatPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._heartbeats = [];
        this._ws = null;
    }

    async init() {
        await super.init();
        this._connectRealtime();
    }

    _connectRealtime() {
        if (window.WebSocketManager) {
            this._ws = new WebSocketManager('/api/nexus/ws');
            this._ws.on('agent.heartbeat', (payload) => this._onHeartbeat(payload));
            this._ws.on('_connected', () => {
                this._ws.send('subscribe', { events: ['agent.heartbeat'] });
            });
            this._ws.connect();
        }
    }

    _onHeartbeat(payload) {
        this._heartbeats.unshift({
            agent_id: payload.agent_id,
            status: payload.status,
            ts: payload.ts || Date.now(),
            latency_ms: payload.latency_ms,
        });
        if (this._heartbeats.length > 100) this._heartbeats.length = 100;
        if (this.container) this.render(this.container);
    }

    render(container) {
        this.container = container;
        const recent = this._heartbeats.slice(0, 50);

        container.innerHTML = `
            ${this._headerHtml()}
            <div class="panel-body">
                ${recent.length === 0 ? '<div class="panel-empty">Waiting for heartbeat events…</div>' : `
                <div class="panel-timeline">
                    ${recent.map(h => {
                        const time = new Date(h.ts).toLocaleTimeString();
                        const statusClass = h.status === 'ok' ? 'status-online' : h.status === 'warn' ? 'status-warn' : 'status-offline';
                        return `
                        <div class="timeline-item">
                            <div class="timeline-dot ${statusClass}"></div>
                            <div class="timeline-content">
                                <div class="timeline-title">${this._escapeHtml(h.agent_id)}</div>
                                <div class="timeline-meta">${time} &middot; ${h.latency_ms != null ? h.latency_ms + 'ms' : h.status}</div>
                            </div>
                        </div>`;
                    }).join('')}
                </div>`}
            </div>
        `;
        this._bindRefreshBtn();
    }

    async destroy() {
        await super.destroy();
        if (this._ws) { this._ws.destroy(); this._ws = null; }
    }

    onRealtimeEvent(eventType, payload) {
        if (eventType === 'agent.heartbeat') this._onHeartbeat(payload);
    }
}

export { AgentHeartbeatPanel };
