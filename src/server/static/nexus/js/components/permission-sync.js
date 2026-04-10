/**
 * PermissionSyncPanel — UI for cross-agent permission synchronization.
 *
 * Components:
 *   - PermissionSyncPanel: main container showing pending requests
 *   - PermissionRequestCard: individual request card with approve/reject
 *   - PermissionStatusBadge: agent avatar permission status indicator
 */

// ============================================================
// PermissionSyncPanel
// ============================================================

class PermissionSyncPanel {
    constructor(containerEl, options = {}) {
        this.container = typeof containerEl === 'string'
            ? document.querySelector(containerEl)
            : containerEl;
        this.options = {
            pollInterval: options.pollInterval || 5000,
            ...options,
        };
        this._pollTimer = null;
        this._requests = [];
        this._cache = {};
        this._stats = {};
    }

    start() {
        this.render();
        this._startPolling();
    }

    stop() {
        this._stopPolling();
    }

    async refresh() {
        try {
            const [pending, cacheData] = await Promise.all([
                NexusAPI.getPendingPermissionRequests(),
                NexusAPI.getPermissionCache(),
            ]);
            this._requests = pending || [];
            this._cache = cacheData?.cache || {};
            this._stats = cacheData?.stats || {};
            this.render();
        } catch (err) {
            console.error('PermissionSyncPanel: refresh failed', err);
        }
    }

    render() {
        if (!this.container) return;

        const pendingCount = this._requests.filter(r => r.status === 'pending').length;

        this.container.innerHTML = `
            <div class="perm-sync-panel">
                <div class="perm-sync-header">
                    <h3>Permission Requests</h3>
                    <span class="perm-sync-badge ${pendingCount > 0 ? 'has-pending' : ''}">${pendingCount}</span>
                </div>
                <div class="perm-sync-stats">
                    <span>Cached agents: ${this._stats.cached_agents || 0}</span>
                    <span>Cached entries: ${this._stats.total_cached_entries || 0}</span>
                </div>
                <div class="perm-sync-list">
                    ${this._requests.length === 0
                        ? '<div class="perm-sync-empty">No pending permission requests</div>'
                        : this._requests.map(r => this._renderRequestCard(r)).join('')
                    }
                </div>
            </div>
        `;

        this._bindCardEvents();
    }

    _renderRequestCard(req) {
        const riskColors = {
            read: 'risk-low',
            write: 'risk-medium',
            exec: 'risk-high',
            network: 'risk-medium',
            admin: 'risk-critical',
            message: 'risk-low',
        };
        const riskClass = riskColors[req.risk_level] || 'risk-medium';
        const timeAgo = this._formatTimeAgo(req.created_at);
        const argsPreview = this._formatArgs(req.tool_args);

        return `
            <div class="perm-request-card" data-request-id="${req.id}" data-status="${req.status}">
                <div class="perm-request-top">
                    <span class="perm-agent-name">${this._escapeHtml(req.agent_name)}</span>
                    <span class="perm-risk-badge ${riskClass}">${req.risk_level.toUpperCase()}</span>
                </div>
                <div class="perm-request-tool">
                    <code>${this._escapeHtml(req.tool_name)}</code>
                </div>
                <div class="perm-request-args">
                    <pre>${this._escapeHtml(argsPreview)}</pre>
                </div>
                <div class="perm-request-meta">
                    <span class="perm-time">${timeAgo}</span>
                    ${req.status === 'pending' ? '' : `<span class="perm-status perm-status-${req.status}">${req.status}</span>`}
                </div>
                ${req.status === 'pending' ? `
                    <div class="perm-request-actions">
                        <select class="perm-approve-scope" data-request-id="${req.id}">
                            <option value="once">Once</option>
                            <option value="session">Session</option>
                            <option value="permanent">Permanent</option>
                        </select>
                        <button class="perm-btn perm-btn-approve" data-request-id="${req.id}" data-action="approve">
                            Approve
                        </button>
                        <button class="perm-btn perm-btn-reject" data-request-id="${req.id}" data-action="reject">
                            Reject
                        </button>
                    </div>
                ` : ''}
            </div>
        `;
    }

    _bindCardEvents() {
        this.container.querySelectorAll('.perm-btn-approve').forEach(btn => {
            btn.addEventListener('click', () => this._handleApprove(btn.dataset.requestId));
        });
        this.container.querySelectorAll('.perm-btn-reject').forEach(btn => {
            btn.addEventListener('click', () => this._handleReject(btn.dataset.requestId));
        });
    }

    async _handleApprove(requestId) {
        const scopeSelect = this.container.querySelector(`.perm-approve-scope[data-request-id="${requestId}"]`);
        const scope = scopeSelect ? scopeSelect.value : 'once';
        try {
            await NexusAPI.approvePermissionRequest(requestId, { approver: 'lead', scope });
            await this.refresh();
        } catch (err) {
            console.error('Failed to approve permission request:', err);
        }
    }

    async _handleReject(requestId) {
        const reason = prompt('Reason for rejection (optional):') || '';
        try {
            await NexusAPI.rejectPermissionRequest(requestId, { approver: 'lead', reason });
            await this.refresh();
        } catch (err) {
            console.error('Failed to reject permission request:', err);
        }
    }

    _startPolling() {
        this._stopPolling();
        this._pollTimer = setInterval(() => this.refresh(), this.options.pollInterval);
    }

    _stopPolling() {
        if (this._pollTimer) {
            clearInterval(this._pollTimer);
            this._pollTimer = null;
        }
    }

    _formatTimeAgo(timestamp) {
        const seconds = Math.floor(Date.now() / 1000 - timestamp);
        if (seconds < 60) return `${seconds}s ago`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
        return `${Math.floor(seconds / 3600)}h ago`;
    }

    _formatArgs(args) {
        try {
            const str = JSON.stringify(args, null, 2);
            return str.length > 200 ? str.substring(0, 200) + '...' : str;
        } catch {
            return String(args);
        }
    }

    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
}


// ============================================================
// PermissionStatusBadge
// ============================================================

class PermissionStatusBadge {
    /**
     * Create a permission status badge element.
     * @param {Object} opts - { agentName, hasPending, hasSync }
     * @returns {HTMLElement}
     */
    static create(opts = {}) {
        const { agentName, hasPending = false, hasSync = false } = opts;

        const badge = document.createElement('span');
        badge.className = 'perm-status-badge';
        badge.dataset.agentName = agentName;

        if (!hasSync) {
            badge.classList.add('perm-badge-none');
            badge.title = 'No permission sync';
            badge.textContent = '';
        } else if (hasPending) {
            badge.classList.add('perm-badge-pending');
            badge.title = 'Pending permission requests';
            badge.textContent = '!';
        } else {
            badge.classList.add('perm-badge-ok');
            badge.title = 'All permissions synced';
            badge.textContent = '';
        }

        return badge;
    }

    /**
     * Update an existing badge.
     * @param {HTMLElement} badge - The badge element
     * @param {Object} opts - { hasPending, hasSync }
     */
    static update(badge, opts = {}) {
        const { hasPending = false, hasSync = false } = opts;

        badge.className = 'perm-status-badge';

        if (!hasSync) {
            badge.classList.add('perm-badge-none');
            badge.title = 'No permission sync';
            badge.textContent = '';
        } else if (hasPending) {
            badge.classList.add('perm-badge-pending');
            badge.title = 'Pending permission requests';
            badge.textContent = '!';
        } else {
            badge.classList.add('perm-badge-ok');
            badge.title = 'All permissions synced';
            badge.textContent = '';
        }
    }
}


// ============================================================
// NexusAPI extensions for permission sync
// ============================================================

// Add permission sync API methods to NexusAPI
if (window.NexusAPI) {
    NexusAPI.getPendingPermissionRequests = async function() {
        const response = await fetch(`${API_BASE}/security/permissions/pending`);
        if (!response.ok) throw new Error('Failed to fetch pending permission requests');
        return response.json();
    };

    NexusAPI.approvePermissionRequest = async function(requestId, payload) {
        const response = await fetch(
            `${API_BASE}/security/permissions/${encodeURIComponent(requestId)}/approve`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }
        );
        if (!response.ok) throw new Error('Failed to approve permission request');
        return response.json();
    };

    NexusAPI.rejectPermissionRequest = async function(requestId, payload) {
        const response = await fetch(
            `${API_BASE}/security/permissions/${encodeURIComponent(requestId)}/reject`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }
        );
        if (!response.ok) throw new Error('Failed to reject permission request');
        return response.json();
    };

    NexusAPI.getPermissionCache = async function() {
        const response = await fetch(`${API_BASE}/security/permissions/cache`);
        if (!response.ok) throw new Error('Failed to fetch permission cache');
        return response.json();
    };

    NexusAPI.triggerPermissionSync = async function(agentName) {
        const response = await fetch(`${API_BASE}/security/permissions/sync`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agent_name: agentName }),
        });
        if (!response.ok) throw new Error('Failed to trigger permission sync');
        return response.json();
    };
}


// Export for use in other scripts
window.PermissionSyncPanel = PermissionSyncPanel;
window.PermissionStatusBadge = PermissionStatusBadge;
