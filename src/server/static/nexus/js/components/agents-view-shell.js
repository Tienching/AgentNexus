(function initNexusAgentsViewShell(global) {
    class NexusAgentsViewShell {
        constructor(app, options = {}) {
            this.app = app;
            this.store = options.store || new global.NexusAgentsStore();
            this.mounted = false;
            this._unsubscribe = null;
            this.view = null;
        }

        mount() {
            if (this.mounted) return;
            this._ensureView();
            if (!this.view) return;
            this.mounted = true;
            this._unsubscribe = this.store.subscribe((state) => this.render(state));
        }

        async refresh(options = {}) {
            this.mount();
            if (!this.view) return null;
            const restoreSelection = options.restoreSelection !== false;
            try {
                if (!this.store.getState().initialized) {
                    return await this.store.init();
                }
                return await this.store.refresh({ restoreSelection });
            } catch (error) {
                this._showToast(error.message || 'Failed to load agents', 'error');
                return null;
            }
        }

        _ensureView() {
            this.view = document.getElementById('agentsView');
        }

        _escape(value) {
            return String(value == null ? '' : value)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        }

        _formatTime(timestamp) {
            if (!timestamp) return '—';
            try {
                const numeric = Number(timestamp);
                const date = new Date(Number.isFinite(numeric) && numeric < 1e12 ? numeric * 1000 : numeric || timestamp);
                return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
            } catch (_) {
                return '—';
            }
        }

        _showToast(message, type = 'info') {
            if (typeof this.app?.showToast === 'function') {
                this.app.showToast(message, type);
                return;
            }
            console[type === 'error' ? 'error' : 'log']('[Agents]', message);
        }

        _metricCard(label, value, note = '') {
            return `
                <div class="agents-summary-card">
                    <div class="agents-summary-label">${this._escape(label)}</div>
                    <div class="agents-summary-value">${this._escape(value)}</div>
                    ${note ? `<div class="agents-summary-note">${this._escape(note)}</div>` : ''}
                </div>
            `;
        }

        _detailSection(title, copy, body, sectionKey, actions = '') {
            return `
                <section class="agents-section" data-agents-section="${this._escape(sectionKey)}">
                    <div class="agents-section-header">
                        <div>
                            <h3>${this._escape(title)}</h3>
                            ${copy ? `<p>${this._escape(copy)}</p>` : ''}
                        </div>
                        ${actions || ''}
                    </div>
                    ${body}
                </section>
            `;
        }

        _renderList(state) {
            const items = this.store.getFilteredItems();
            if (!items.length) {
                return '<div class="u-empty-state-lg">No agents or teams match the current filters.</div>';
            }
            return items.map((entry) => {
                const selected = entry.kind === 'agent'
                    ? state.mode === 'agent_detail' && state.selectedAgentId === entry.id
                    : state.mode === 'team_detail' && state.selectedTeamName === entry.id;
                return `
                    <button class="agents-list-item${selected ? ' is-active' : ''}" data-kind="${this._escape(entry.kind)}" data-id="${this._escape(entry.id)}">
                        <div class="agents-list-body">
                            <div class="agents-list-title">
                                <span class="agents-list-name">${this._escape(entry.title)}</span>
                                <span class="panel-badge">${this._escape(entry.kind)}</span>
                            </div>
                            <div class="agents-list-subtitle">${this._escape(entry.subtitle || '—')}</div>
                            <div class="agents-list-meta">${this._escape(entry.status || 'unknown')}</div>
                        </div>
                    </button>
                `;
            }).join('');
        }

        _renderMemoryRestoreList(memoryState) {
            const state = memoryState?.state || memoryState || {};
            const sessions = (state.sessions || state.entries || []).slice(0, 6);
            if (!sessions.length) {
                return '<div class="u-empty-state-lg">No restorable memory sessions found.</div>';
            }
            return sessions.map((session) => {
                const sessionId = session.session_id || session.id || '';
                const updatedAt = session.updated_at || session.timestamp || session.created_at;
                const summary = [
                    updatedAt ? this._formatTime(updatedAt) : '',
                    session.message_count ? `${session.message_count} messages` : '',
                ].filter(Boolean).join(' · ');
                return `
                    <div class="panel-list-item">
                        <div class="panel-list-item-body">
                            <div class="panel-list-item-title">${this._escape(sessionId || 'Session')}</div>
                            <div class="panel-list-item-sub">${this._escape(summary || 'Recent memory context')}</div>
                        </div>
                        ${sessionId ? `<button class="action-btn" data-action="restore-memory" data-session-id="${this._escape(sessionId)}">Restore</button>` : ''}
                    </div>
                `;
            }).join('');
        }

        _renderOverviewPanel(state) {
            const overview = state.overview || {};
            const dashboard = overview.dashboard || overview.summary || {};
            const recentActivity = overview.recent_activity || [];
            const recentCosts = (overview.costs?.by_agent || overview.recent_costs || []).slice(0, 5);
            const memoryState = state.memoryState?.state || state.memoryState || {};
            const memorySessions = memoryState.sessions || memoryState.entries || [];
            const memoryContexts = memoryState.contexts || [];

            const activityRows = recentActivity.length
                ? recentActivity.map((item) => `
                    <div class="panel-list-item">
                        <div class="panel-list-item-body">
                            <div class="panel-list-item-title">${this._escape(item.title || 'Activity')}</div>
                            <div class="panel-list-item-sub">${this._escape(item.subtitle || item.detail || '')}</div>
                        </div>
                        <span class="panel-badge">${this._escape(this._formatTime(item.timestamp))}</span>
                    </div>
                `).join('')
                : '<div class="u-empty-state-lg">No recent activity.</div>';

            const teamRows = (overview.teams || []).length
                ? (overview.teams || []).map((team) => `
                    <div class="panel-list-item">
                        <div class="panel-list-item-body">
                            <div class="panel-list-item-title">${this._escape(team.identity?.title || team.team_name || team.name)}</div>
                            <div class="panel-list-item-sub">${this._escape(team.identity?.subtitle || `${team.member_count || 0} members`)}</div>
                        </div>
                        <span class="panel-badge">${this._escape(team.runtime?.status || team.status || 'idle')}</span>
                    </div>
                `).join('')
                : '<div class="u-empty-state-lg">No teams registered.</div>';

            const costRows = recentCosts.length
                ? recentCosts.map((item) => `
                    <div class="panel-list-item">
                        <div class="panel-list-item-body">
                            <div class="panel-list-item-title">${this._escape(item.key || 'unassigned')}</div>
                            <div class="panel-list-item-sub">${this._escape(String(item.total_tokens || 0))} tokens · ${this._escape(String(item.count || 0))} req</div>
                        </div>
                        <span class="panel-badge">$${Number(item.total_cost_usd || 0).toFixed(4)}</span>
                    </div>
                `).join('')
                : '<div class="u-empty-state-lg">No cost data available.</div>';

            return `
                <div class="agents-main-inner" id="agentsOverviewPanel">
                    <div class="agents-section-header">
                        <div>
                            <h2>Agents Overview</h2>
                            <p>Global dashboard for agent health, team activity, memory restores, and token usage.</p>
                        </div>
                        <button class="action-btn" id="agentsRefreshBtn">Refresh</button>
                    </div>
                    <div class="agents-overview-grid">
                        ${this._metricCard('Agents', dashboard.total_agents || 0, `${dashboard.online_agents || 0} online`)}
                        ${this._metricCard('Teams', dashboard.teams_total || dashboard.total_teams || 0, `${dashboard.active_teams || 0} active`)}
                        ${this._metricCard('Active Tasks', dashboard.active_tasks || 0, `${dashboard.queue_depth || 0} queued`)}
                        ${this._metricCard('Tokens', dashboard.total_tokens || 0, `${dashboard.recent_activity_count || recentActivity.length || 0} recent events`)}
                        ${this._metricCard('Cost', `$${Number(dashboard.total_cost_usd || 0).toFixed(2)}`, `${dashboard.recent_failures || 0} failures`)}
                        ${this._metricCard('Memory', memorySessions.length, `${memoryContexts.length} contexts`)}
                    </div>
                    ${this._detailSection('Recent Activity', 'Notifications, failures, and operator-visible events.', activityRows, 'activity')}
                    ${this._detailSection('Teams Summary', 'Swarm and team coordination at a glance.', teamRows, 'teams')}
                    ${this._detailSection('Token Usage', 'Recent cost and token breakdown by agent.', costRows, 'cost')}
                    ${this._detailSection('Memory Restore', 'Restore memory context from recent sessions without leaving Agents.', this._renderMemoryRestoreList(state.memoryState), 'memory')}
                </div>
            `;
        }

        _renderAgentDetail(state) {
            const summary = this.store.getCurrentAgentSummary() || {};
            const binding = state.agentBinding || {};
            const identity = binding.identity || summary.identity || {};
            const runtime = binding.runtime || summary.runtime || {};
            const memory = binding.memory || summary.memory || {};
            const activity = binding.activity || summary.activity || {};
            const cost = binding.cost || summary.cost || {};
            const agentBinding = binding.binding || {};
            const capabilities = binding.capabilities || summary.capabilities || [];
            const memoryTopology = [
                agentBinding.memory_scope || memory.scope || 'session',
                agentBinding.team_name ? 'team-shared' : 'agent-local',
                (state.memoryState?.state?.sessions || state.memoryState?.sessions || []).length ? 'restorable' : 'ephemeral',
            ];

            return `
                <div class="agents-main-inner" id="agentsAgentDetail" data-agent-id="${this._escape(state.selectedAgentId || '')}">
                    <div class="agents-section-header">
                        <div>
                            <button class="action-btn" id="agentsOverviewBtn">← Overview</button>
                            <h2>${this._escape(identity.title || summary.display_name || state.selectedAgentId || 'Agent')}</h2>
                            <p>${this._escape(identity.subtitle || runtime.status || '')}</p>
                        </div>
                        <button class="action-btn" id="agentsRefreshBtn">Refresh</button>
                    </div>
                    ${this._detailSection('Identity', 'Basic ownership and profile fields for this agent.', `
                        <div class="agents-detail-grid">
                            <div class="detail-kv"><div class="detail-kv-label">Agent ID</div><div class="detail-kv-value">${this._escape(state.selectedAgentId || '—')}</div></div>
                            <div class="detail-kv"><div class="detail-kv-label">Display Name</div><div class="detail-kv-value">${this._escape(identity.title || summary.display_name || '—')}</div></div>
                            <div class="detail-kv"><div class="detail-kv-label">Owner</div><div class="detail-kv-value">${this._escape(identity.owner || agentBinding.exec_user || '—')}</div></div>
                            <div class="detail-kv"><div class="detail-kv-label">Status</div><div class="detail-kv-value">${this._escape(runtime.status || 'unknown')}</div></div>
                        </div>
                    `, 'identity')}
                    ${this._detailSection('Runtime', 'Provider, model, workspace, and routing for this agent.', `
                        <div class="agents-detail-grid">
                            <label class="detail-kv"><div class="detail-kv-label">Provider</div><input id="agentBindingProvider" class="form-input" value="${this._escape(agentBinding.provider || binding.provider || identity.provider || '')}"></label>
                            <label class="detail-kv"><div class="detail-kv-label">Alias</div><input id="agentBindingAlias" class="form-input" value="${this._escape(agentBinding.alias || identity.alias || '')}"></label>
                            <label class="detail-kv"><div class="detail-kv-label">Model</div><input id="agentBindingModel" class="form-input" value="${this._escape(agentBinding.model || runtime.model || '')}"></label>
                            <label class="detail-kv"><div class="detail-kv-label">Runtime Profile</div><input id="agentBindingRuntimeProfile" class="form-input" value="${this._escape(agentBinding.runtime_profile || runtime.runtime_profile || 'default')}"></label>
                            <label class="detail-kv"><div class="detail-kv-label">Workspace</div><input id="agentBindingWorkspace" class="form-input" value="${this._escape(agentBinding.workspace || runtime.workspace || '')}"></label>
                            <label class="detail-kv"><div class="detail-kv-label">Team</div><input id="agentBindingTeamName" class="form-input" value="${this._escape(agentBinding.team_name || runtime.team_name || '')}"></label>
                        </div>
                        <div class="agents-detail-grid">
                            <label class="detail-kv"><div class="detail-kv-label">Enabled</div><label class="u-inline-label"><input id="agentBindingEnabled" type="checkbox" ${agentBinding.enabled === false ? '' : 'checked'}><span>Allow task dispatch</span></label></label>
                            <div class="detail-kv"><div class="detail-kv-label">Last Heartbeat</div><div class="detail-kv-value">${this._escape(this._formatTime(runtime.last_heartbeat))}</div></div>
                        </div>
                    `, 'runtime')}
                    ${this._detailSection('Memory', 'Agent-scoped memory policy, topology, and restore entry points.', `
                        <div class="agents-detail-grid">
                            <label class="detail-kv"><div class="detail-kv-label">Memory Scope</div><input id="agentBindingMemoryScope" class="form-input" value="${this._escape(agentBinding.memory_scope || memory.scope || 'session')}"></label>
                            <label class="detail-kv"><div class="detail-kv-label">Notes</div><input id="agentBindingNotes" class="form-input" value="${this._escape(agentBinding.notes || '')}"></label>
                            <div class="detail-kv"><div class="detail-kv-label">Entries</div><div class="detail-kv-value">${this._escape(String(memory.entry_count || 0))}</div></div>
                            <div class="detail-kv"><div class="detail-kv-label">Topology</div><div class="detail-kv-value">${this._escape(memoryTopology.join(' · '))}</div></div>
                        </div>
                        <div class="settings-section-copy">${this._escape(memory.summary || 'No memory summary available.')}</div>
                        <div class="u-mt-lg">${this._renderMemoryRestoreList(state.memoryState)}</div>
                    `, 'memory')}
                    ${this._detailSection('Capabilities', 'Skills, tools, and permissions exposed at the agent level.', `
                        <div class="agents-detail-grid">
                            <label class="detail-kv detail-kv-span-full"><div class="detail-kv-label">Capabilities</div><input id="agentBindingCapabilities" class="form-input" value="${this._escape((agentBinding.capabilities || capabilities || []).join(', '))}"></label>
                        </div>
                        <div class="settings-section-copy">Current: ${this._escape((capabilities || []).join(', ') || 'No capabilities')}</div>
                    `, 'capabilities')}
                    ${this._detailSection('Activity', 'Recent runtime status and token usage for this agent.', `
                        <div class="agents-detail-grid">
                            <div class="detail-kv"><div class="detail-kv-label">Status</div><div class="detail-kv-value">${this._escape(activity.status || runtime.status || 'unknown')}</div></div>
                            <div class="detail-kv"><div class="detail-kv-label">Headline</div><div class="detail-kv-value">${this._escape(activity.headline || 'No recent headline')}</div></div>
                            <div class="detail-kv"><div class="detail-kv-label">Last Seen</div><div class="detail-kv-value">${this._escape(this._formatTime(activity.last_seen_at || runtime.last_heartbeat))}</div></div>
                            <div class="detail-kv"><div class="detail-kv-label">Usage</div><div class="detail-kv-value">$${Number(cost.total_cost_usd || 0).toFixed(4)} · ${this._escape(String(cost.total_tokens || 0))} tokens</div></div>
                        </div>
                    `, 'activity', `<button class="action-btn primary" id="saveAgentBindingBtn" ${state.saving ? 'disabled' : ''}>${state.saving ? 'Saving…' : 'Save binding'}</button>`)}
                </div>
            `;
        }

        _renderTeamDetail(state) {
            const summary = this.store.getCurrentTeamSummary() || {};
            const config = state.teamConfig || {};
            const teamConfig = config.config || {};
            const identity = config.identity || summary.identity || {};
            const runtime = config.runtime_detail || summary.runtime || {};
            const memory = config.memory || summary.memory || {};
            const activity = config.activity || summary.activity || {};
            const cost = config.cost || summary.cost || {};
            const capabilities = config.capabilities || summary.capabilities || [];
            const members = config.members || summary.members || [];

            return `
                <div class="agents-main-inner" id="agentsTeamDetail" data-team-name="${this._escape(state.selectedTeamName || '')}">
                    <div class="agents-section-header">
                        <div>
                            <button class="action-btn" id="agentsOverviewBtn">← Overview</button>
                            <h2>${this._escape(identity.title || state.selectedTeamName || 'Team')}</h2>
                            <p>${this._escape(identity.subtitle || runtime.status || '')}</p>
                        </div>
                        <button class="action-btn" id="agentsRefreshBtn">Refresh</button>
                    </div>
                    ${this._detailSection('Identity', 'Shared ownership and mission metadata for the team.', `
                        <div class="agents-detail-grid">
                            <div class="detail-kv"><div class="detail-kv-label">Team Name</div><div class="detail-kv-value">${this._escape(state.selectedTeamName || '—')}</div></div>
                            <div class="detail-kv"><div class="detail-kv-label">Lead Agent</div><div class="detail-kv-value">${this._escape(teamConfig.lead_agent_id || identity.owner || '—')}</div></div>
                            <div class="detail-kv"><div class="detail-kv-label">Provider</div><div class="detail-kv-value">${this._escape(identity.provider || config.default_provider || '—')}</div></div>
                            <div class="detail-kv"><div class="detail-kv-label">Alias</div><div class="detail-kv-value">${this._escape(identity.alias || config.default_alias || '—')}</div></div>
                        </div>
                    `, 'identity')}
                    ${this._detailSection('Runtime', 'Coordination workspace, mission, and swarm operating mode.', `
                        <div class="agents-detail-grid">
                            <label class="detail-kv"><div class="detail-kv-label">Display Name</div><input id="teamConfigDisplayName" class="form-input" value="${this._escape(teamConfig.display_name || identity.title || '')}"></label>
                            <label class="detail-kv"><div class="detail-kv-label">Workspace</div><input id="teamConfigWorkspace" class="form-input" value="${this._escape(teamConfig.workspace || runtime.workspace || '')}"></label>
                            <label class="detail-kv detail-kv-span-full"><div class="detail-kv-label">Mission</div><input id="teamConfigMission" class="form-input" value="${this._escape(teamConfig.mission || '')}"></label>
                            <label class="detail-kv"><div class="detail-kv-label">Lead Agent ID</div><input id="teamConfigLeadAgentId" class="form-input" value="${this._escape(teamConfig.lead_agent_id || '')}"></label>
                            <label class="detail-kv"><div class="detail-kv-label">Auto Balance</div><label class="u-inline-label"><input id="teamConfigAutoBalance" type="checkbox" ${teamConfig.auto_balance ? 'checked' : ''}><span>Distribute work automatically</span></label></label>
                        </div>
                        <div class="settings-section-copy">Running agents: ${this._escape(String(runtime.running_agents || 0))} · Available tasks: ${this._escape(String(runtime.available_tasks || 0))}</div>
                    `, 'runtime')}
                    ${this._detailSection('Memory', 'Shared team memory policy and member-level restore surface.', `
                        <div class="agents-detail-grid">
                            <label class="detail-kv"><div class="detail-kv-label">Shared Memory Policy</div><input id="teamConfigMemoryPolicy" class="form-input" value="${this._escape(teamConfig.shared_memory_policy || memory.scope || 'team')}"></label>
                            <label class="detail-kv"><div class="detail-kv-label">Tags</div><input id="teamConfigTags" class="form-input" value="${this._escape((teamConfig.tags || []).join(', '))}"></label>
                            <label class="detail-kv detail-kv-span-full"><div class="detail-kv-label">Notes</div><input id="teamConfigNotes" class="form-input" value="${this._escape(teamConfig.notes || '')}"></label>
                        </div>
                        <div class="settings-section-copy">${this._escape(memory.summary || 'No shared memory summary available.')}</div>
                        <div class="u-mt-lg">${this._renderMemoryRestoreList(state.memoryState)}</div>
                    `, 'memory')}
                    ${this._detailSection('Capabilities', 'Members, skills, and coordination capabilities exposed by the team.', `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">Capabilities</div>
                                <div class="panel-list-item-sub">${this._escape((capabilities || []).join(', ') || 'No capabilities')}</div>
                            </div>
                            <span class="panel-badge">${this._escape(String(members.length || 0))} members</span>
                        </div>
                        ${(members || []).length ? members.map((member) => `
                            <div class="panel-list-item">
                                <div class="panel-list-item-body">
                                    <div class="panel-list-item-title">${this._escape(member.name || member.agent_id || 'Member')}</div>
                                    <div class="panel-list-item-sub">${this._escape((member.capabilities || []).join(', ') || 'No capabilities')}</div>
                                </div>
                                <span class="panel-badge">${this._escape(member.role || 'worker')}</span>
                            </div>
                        `).join('') : '<div class="u-empty-state-lg">No team members found.</div>'}
                    `, 'capabilities')}
                    ${this._detailSection('Activity', 'Claim tasks, observe runtime state, and control the swarm.', `
                        <div class="agents-detail-grid">
                            <div class="detail-kv"><div class="detail-kv-label">Status</div><div class="detail-kv-value">${this._escape(activity.status || runtime.status || 'unknown')}</div></div>
                            <div class="detail-kv"><div class="detail-kv-label">Headline</div><div class="detail-kv-value">${this._escape(activity.headline || 'No recent headline')}</div></div>
                            <div class="detail-kv"><div class="detail-kv-label">Last Seen</div><div class="detail-kv-value">${this._escape(this._formatTime(activity.last_seen_at))}</div></div>
                            <div class="detail-kv"><div class="detail-kv-label">Usage</div><div class="detail-kv-value">$${Number(cost.total_cost_usd || 0).toFixed(4)} · ${this._escape(String(cost.total_tokens || 0))} tokens</div></div>
                        </div>
                        <div class="agents-detail-grid u-mt-lg">
                            <label class="detail-kv"><div class="detail-kv-label">Task ID to Claim</div><input id="teamClaimTaskId" class="form-input" placeholder="task-123"></label>
                            <label class="detail-kv"><div class="detail-kv-label">Agent Name</div><input id="teamClaimAgentName" class="form-input" placeholder="lead"></label>
                        </div>
                    `, 'activity', `
                        <div class="u-row-wrap">
                            <button class="action-btn primary" id="saveTeamConfigBtn" ${state.saving ? 'disabled' : ''}>${state.saving ? 'Saving…' : 'Save team config'}</button>
                            <button class="action-btn" id="claimTeamTaskBtn">Claim task</button>
                            <button class="action-btn btn-danger-solid" id="shutdownTeamBtn">Shutdown</button>
                        </div>
                    `)}
                </div>
            `;
        }

        render(state = this.store.getState()) {
            if (!this.view) return;
            const detailPanel = state.mode === 'agent_detail'
                ? this._renderAgentDetail(state)
                : state.mode === 'team_detail'
                    ? this._renderTeamDetail(state)
                    : this._renderOverviewPanel(state);
            this.view.innerHTML = `
                <div id="agentsPageShell" class="agents-page" data-agents-mode="${this._escape(state.mode)}">
                    <aside class="agents-sidebar">
                        <div class="agents-sidebar-header">
                            <div class="agents-sidebar-title">
                                <h2>Agents</h2>
                                <button class="action-btn" id="agentsSidebarRefreshBtn">Refresh</button>
                            </div>
                            <p class="agents-sidebar-copy">Search, filter, and switch between overview, agent detail, and team detail.</p>
                            <div class="agents-filter-row">
                                <input id="agentsSearchInput" class="form-input" value="${this._escape(state.searchQuery || '')}" placeholder="Search agents or teams">
                                <select id="agentsStatusFilter" class="form-input form-select">
                                    ${['all', 'online', 'idle', 'running', 'error', 'offline'].map((status) => `<option value="${status}" ${state.statusFilter === status ? 'selected' : ''}>${status}</option>`).join('')}
                                </select>
                            </div>
                            <div class="agents-filter-row">
                                <button class="agents-filter-chip${state.mode === 'overview' ? ' is-active' : ''}" id="agentsSidebarOverviewBtn">Overview</button>
                            </div>
                            ${state.error ? `<div class="panel-list-item"><div class="panel-list-item-body"><div class="panel-list-item-title">Load Error</div><div class="panel-list-item-sub">${this._escape(state.error)}</div></div></div>` : ''}
                        </div>
                        <div class="agents-sidebar-body">
                            <div class="agents-sidebar-group">
                                <div class="agents-sidebar-group-title"><span>Directory</span><span>${this._escape(String(this.store.getFilteredItems().length))}</span></div>
                                <div id="agentsList" class="agents-list">${this._renderList(state)}</div>
                            </div>
                        </div>
                    </aside>
                    <section class="agents-main">
                        ${state.loading ? '<div class="panel-badge">Loading…</div>' : ''}
                        ${detailPanel}
                    </section>
                </div>
            `;
            this._bindRenderEvents(state);
        }

        _bindRenderEvents(state) {
            this.view.querySelector('#agentsSearchInput')?.addEventListener('input', (event) => {
                this.store.setSearchQuery(event.target.value || '');
            });
            this.view.querySelector('#agentsStatusFilter')?.addEventListener('change', (event) => {
                this.store.setStatusFilter(event.target.value || 'all');
            });
            this.view.querySelector('#agentsSidebarOverviewBtn')?.addEventListener('click', () => this.store.showOverview());
            this.view.querySelector('#agentsOverviewBtn')?.addEventListener('click', () => this.store.showOverview());
            this.view.querySelector('#agentsSidebarRefreshBtn')?.addEventListener('click', () => this.refresh({ restoreSelection: true }));
            this.view.querySelector('#agentsRefreshBtn')?.addEventListener('click', () => this.refresh({ restoreSelection: true }));
            this.view.querySelectorAll('.agents-list-item').forEach((button) => {
                button.addEventListener('click', async () => {
                    try {
                        if (button.dataset.kind === 'team') {
                            await this.store.selectTeam(button.dataset.id);
                        } else {
                            await this.store.selectAgent(button.dataset.id);
                        }
                    } catch (error) {
                        this._showToast(error.message || 'Failed to load selection', 'error');
                    }
                });
            });
            this.view.querySelectorAll('[data-action="restore-memory"]').forEach((button) => {
                button.addEventListener('click', async () => {
                    const sessionId = button.dataset.sessionId;
                    if (!sessionId) return;
                    try {
                        await NexusAPI.restoreMemoryContext(sessionId);
                        this._showToast('Memory context restored', 'success');
                    } catch (error) {
                        this._showToast(error.message || 'Failed to restore memory context', 'error');
                    }
                });
            });
            this.view.querySelector('#saveAgentBindingBtn')?.addEventListener('click', async () => {
                try {
                    const capabilities = String(this.view.querySelector('#agentBindingCapabilities')?.value || '')
                        .split(',')
                        .map((item) => item.trim())
                        .filter(Boolean);
                    await this.store.updateAgentBinding({
                        provider: this.view.querySelector('#agentBindingProvider')?.value || '',
                        workspace: this.view.querySelector('#agentBindingWorkspace')?.value || '',
                        runtime_profile: this.view.querySelector('#agentBindingRuntimeProfile')?.value || 'default',
                        alias: this.view.querySelector('#agentBindingAlias')?.value || '',
                        model: this.view.querySelector('#agentBindingModel')?.value || '',
                        team_name: this.view.querySelector('#agentBindingTeamName')?.value || '',
                        enabled: !!this.view.querySelector('#agentBindingEnabled')?.checked,
                        memory_scope: this.view.querySelector('#agentBindingMemoryScope')?.value || 'session',
                        notes: this.view.querySelector('#agentBindingNotes')?.value || '',
                        capabilities,
                    });
                    this._showToast('Agent binding saved', 'success');
                } catch (error) {
                    this._showToast(error.message || 'Failed to save binding', 'error');
                }
            });
            this.view.querySelector('#saveTeamConfigBtn')?.addEventListener('click', async () => {
                try {
                    const tags = String(this.view.querySelector('#teamConfigTags')?.value || '')
                        .split(',')
                        .map((item) => item.trim())
                        .filter(Boolean);
                    await this.store.updateTeamConfig({
                        display_name: this.view.querySelector('#teamConfigDisplayName')?.value || '',
                        workspace: this.view.querySelector('#teamConfigWorkspace')?.value || '',
                        mission: this.view.querySelector('#teamConfigMission')?.value || '',
                        lead_agent_id: this.view.querySelector('#teamConfigLeadAgentId')?.value || '',
                        shared_memory_policy: this.view.querySelector('#teamConfigMemoryPolicy')?.value || 'team',
                        auto_balance: !!this.view.querySelector('#teamConfigAutoBalance')?.checked,
                        tags,
                        notes: this.view.querySelector('#teamConfigNotes')?.value || '',
                    });
                    this._showToast('Team config saved', 'success');
                } catch (error) {
                    this._showToast(error.message || 'Failed to save team config', 'error');
                }
            });
            this.view.querySelector('#claimTeamTaskBtn')?.addEventListener('click', async () => {
                try {
                    const taskId = this.view.querySelector('#teamClaimTaskId')?.value?.trim();
                    const agentName = this.view.querySelector('#teamClaimAgentName')?.value?.trim();
                    if (!taskId || !agentName || !state.selectedTeamName) {
                        throw new Error('Team name, task id, and agent name are required');
                    }
                    await NexusAPI.claimTeamTask(state.selectedTeamName, { task_id: taskId, agent_name: agentName });
                    this._showToast('Team task claimed', 'success');
                    await this.refresh({ restoreSelection: true });
                } catch (error) {
                    this._showToast(error.message || 'Failed to claim team task', 'error');
                }
            });
            this.view.querySelector('#shutdownTeamBtn')?.addEventListener('click', async () => {
                try {
                    if (!state.selectedTeamName) throw new Error('No team selected');
                    await NexusAPI.shutdownTeam(state.selectedTeamName);
                    this._showToast('Team shutdown requested', 'success');
                } catch (error) {
                    this._showToast(error.message || 'Failed to shutdown team', 'error');
                }
            });
        }
    }

    global.NexusAgentsViewShell = NexusAgentsViewShell;
    global.AgentsViewShell = NexusAgentsViewShell;
})(window);
