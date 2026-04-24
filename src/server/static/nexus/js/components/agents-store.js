(function initNexusAgentsStore(global) {
    class NexusAgentsStore {
        constructor(options = {}) {
            this.storageKey = options.storageKey || 'nexus_agents_view_state';
            this._subscribers = new Set();
            this._state = this._getDefaultState();
            this._loadPersistedState();
        }

        _getDefaultState() {
            return {
                initialized: false,
                loading: false,
                saving: false,
                error: '',
                mode: 'overview',
                searchQuery: '',
                statusFilter: 'all',
                selectedAgentId: null,
                selectedTeamName: null,
                overview: null,
                memoryState: null,
                agentBinding: null,
                teamConfig: null,
                lastLoadedAt: null,
            };
        }

        getState() {
            return {
                ...this._state,
                overview: this._state.overview ? JSON.parse(JSON.stringify(this._state.overview)) : null,
                memoryState: this._state.memoryState ? JSON.parse(JSON.stringify(this._state.memoryState)) : null,
                agentBinding: this._state.agentBinding ? JSON.parse(JSON.stringify(this._state.agentBinding)) : null,
                teamConfig: this._state.teamConfig ? JSON.parse(JSON.stringify(this._state.teamConfig)) : null,
            };
        }

        subscribe(callback) {
            if (typeof callback !== 'function') return () => {};
            this._subscribers.add(callback);
            callback(this.getState());
            return () => this._subscribers.delete(callback);
        }

        _notify() {
            const snapshot = this.getState();
            for (const callback of this._subscribers) {
                try {
                    callback(snapshot);
                } catch (error) {
                    console.error('[NexusAgentsStore] subscriber error:', error);
                }
            }
        }

        _setState(partial = {}) {
            this._state = {
                ...this._state,
                ...partial,
            };
            this._persistState();
            this._notify();
        }

        _loadPersistedState() {
            try {
                const raw = localStorage.getItem(this.storageKey);
                if (!raw) return;
                const saved = JSON.parse(raw);
                this._state.mode = saved.mode || this._state.mode;
                this._state.searchQuery = saved.searchQuery || '';
                this._state.statusFilter = saved.statusFilter || 'all';
                this._state.selectedAgentId = saved.selectedAgentId || null;
                this._state.selectedTeamName = saved.selectedTeamName || null;
            } catch (error) {
                console.warn('[NexusAgentsStore] failed to restore state:', error);
            }
        }

        _persistState() {
            try {
                localStorage.setItem(this.storageKey, JSON.stringify({
                    mode: this._state.mode,
                    searchQuery: this._state.searchQuery,
                    statusFilter: this._state.statusFilter,
                    selectedAgentId: this._state.selectedAgentId,
                    selectedTeamName: this._state.selectedTeamName,
                }));
            } catch (_) {
                // Best effort only.
            }
        }

        async init() {
            if (this._state.initialized && this._state.overview) {
                return this.refresh({ restoreSelection: true });
            }
            this._setState({ initialized: true });
            return this.refresh({ restoreSelection: true });
        }

        async refresh(options = {}) {
            const restoreSelection = options.restoreSelection !== false;
            this._setState({ loading: true, error: '' });
            try {
                const [overview, memoryState] = await Promise.all([
                    NexusAPI.getAgentsOverview(),
                    NexusAPI.getMemoryState().catch(() => null),
                ]);
                this._setState({
                    overview,
                    memoryState,
                    loading: false,
                    error: '',
                    lastLoadedAt: Date.now(),
                });
                if (restoreSelection) {
                    await this._restoreSelectionAfterRefresh();
                }
                return overview;
            } catch (error) {
                this._setState({ loading: false, error: error.message || 'Failed to load agents overview' });
                throw error;
            }
        }

        async _restoreSelectionAfterRefresh() {
            const overview = this._state.overview || {};
            const agents = overview.agents || [];
            const teams = overview.teams || [];
            if (this._state.mode === 'agent_detail' && this._state.selectedAgentId) {
                const exists = agents.some((agent) => agent.id === this._state.selectedAgentId);
                if (exists) {
                    return this.selectAgent(this._state.selectedAgentId, { preserveMode: true });
                }
            }
            if (this._state.mode === 'team_detail' && this._state.selectedTeamName) {
                const exists = teams.some((team) => team.team_name === this._state.selectedTeamName || team.name === this._state.selectedTeamName);
                if (exists) {
                    return this.selectTeam(this._state.selectedTeamName, { preserveMode: true });
                }
            }
            this.showOverview();
            return null;
        }

        setSearchQuery(searchQuery = '') {
            this._setState({ searchQuery });
        }

        setStatusFilter(statusFilter = 'all') {
            this._setState({ statusFilter: statusFilter || 'all' });
        }

        showOverview() {
            this._setState({
                mode: 'overview',
                selectedAgentId: null,
                selectedTeamName: null,
                agentBinding: null,
                teamConfig: null,
                error: '',
            });
        }

        async selectAgent(agentId, options = {}) {
            if (!agentId) {
                this.showOverview();
                return null;
            }
            this._setState({
                mode: 'agent_detail',
                selectedAgentId: agentId,
                selectedTeamName: null,
                teamConfig: null,
                loading: true,
                error: '',
            });
            try {
                const binding = await NexusAPI.getAgentBinding(agentId);
                this._setState({
                    agentBinding: binding,
                    loading: false,
                    error: '',
                });
                return binding;
            } catch (error) {
                this._setState({
                    agentBinding: null,
                    loading: false,
                    error: error.message || 'Failed to load agent binding',
                });
                if (!options.preserveMode) {
                    this.showOverview();
                }
                throw error;
            }
        }

        async selectTeam(teamName, options = {}) {
            if (!teamName) {
                this.showOverview();
                return null;
            }
            this._setState({
                mode: 'team_detail',
                selectedAgentId: null,
                selectedTeamName: teamName,
                agentBinding: null,
                loading: true,
                error: '',
            });
            try {
                const config = await NexusAPI.getTeamConfig(teamName);
                this._setState({
                    teamConfig: config,
                    loading: false,
                    error: '',
                });
                return config;
            } catch (error) {
                this._setState({
                    teamConfig: null,
                    loading: false,
                    error: error.message || 'Failed to load team config',
                });
                if (!options.preserveMode) {
                    this.showOverview();
                }
                throw error;
            }
        }

        async updateAgentBinding(patch = {}) {
            const agentId = this._state.selectedAgentId;
            if (!agentId) {
                throw new Error('No agent selected');
            }
            this._setState({ saving: true, error: '' });
            try {
                const binding = await NexusAPI.updateAgentBinding(agentId, patch);
                const overview = await NexusAPI.getAgentsOverview().catch(() => this._state.overview);
                this._setState({
                    agentBinding: binding,
                    overview,
                    saving: false,
                    error: '',
                    lastLoadedAt: Date.now(),
                });
                return binding;
            } catch (error) {
                this._setState({ saving: false, error: error.message || 'Failed to update agent binding' });
                throw error;
            }
        }

        async updateTeamConfig(patch = {}) {
            const teamName = this._state.selectedTeamName;
            if (!teamName) {
                throw new Error('No team selected');
            }
            this._setState({ saving: true, error: '' });
            try {
                const config = await NexusAPI.updateTeamConfig(teamName, patch);
                const overview = await NexusAPI.getAgentsOverview().catch(() => this._state.overview);
                this._setState({
                    teamConfig: config,
                    overview,
                    saving: false,
                    error: '',
                    lastLoadedAt: Date.now(),
                });
                return config;
            } catch (error) {
                this._setState({ saving: false, error: error.message || 'Failed to update team config' });
                throw error;
            }
        }

        getCurrentAgentSummary() {
            const overview = this._state.overview || {};
            return (overview.agents || []).find((agent) => agent.id === this._state.selectedAgentId) || null;
        }

        getCurrentTeamSummary() {
            const overview = this._state.overview || {};
            return (overview.teams || []).find((team) => (team.team_name || team.name) === this._state.selectedTeamName) || null;
        }

        _matchesStatus(item, statusFilter) {
            if (!statusFilter || statusFilter === 'all') return true;
            const runtime = item.runtime || item.runtime_detail || {};
            const status = String(runtime.status || item.status || '').trim().toLowerCase();
            if (statusFilter === 'online') {
                return status && status !== 'offline';
            }
            return status === String(statusFilter).trim().toLowerCase();
        }

        _matchesSearch(item, query) {
            if (!query) return true;
            const runtime = item.runtime || item.runtime_detail || {};
            const identity = item.identity || {};
            const haystack = [
                item.id,
                item.team_name,
                item.name,
                item.display_name,
                identity.title,
                identity.subtitle,
                identity.owner,
                identity.provider,
                runtime.workspace,
                ...(item.capabilities || []),
            ].filter(Boolean).join(' ').toLowerCase();
            return haystack.includes(String(query).trim().toLowerCase());
        }

        getFilteredItems() {
            const overview = this._state.overview || {};
            const searchQuery = this._state.searchQuery || '';
            const statusFilter = this._state.statusFilter || 'all';
            const agentItems = (overview.agents || [])
                .filter((agent) => this._matchesSearch(agent, searchQuery) && this._matchesStatus(agent, statusFilter))
                .map((agent) => ({
                    kind: 'agent',
                    key: `agent:${agent.id}`,
                    id: agent.id,
                    title: agent.identity?.title || agent.display_name || agent.id,
                    subtitle: agent.identity?.subtitle || agent.agent_type || '',
                    status: agent.runtime?.status || (agent.available ? 'online' : 'offline'),
                    item: agent,
                }));
            const teamItems = (overview.teams || [])
                .filter((team) => this._matchesSearch(team, searchQuery) && this._matchesStatus(team, statusFilter))
                .map((team) => ({
                    kind: 'team',
                    key: `team:${team.team_name || team.name}`,
                    id: team.team_name || team.name,
                    title: team.identity?.title || team.team_name || team.name,
                    subtitle: team.identity?.subtitle || `${team.member_count || 0} members`,
                    status: team.runtime?.status || team.status || 'idle',
                    item: team,
                }));
            return [...agentItems, ...teamItems];
        }
    }

    global.NexusAgentsStore = NexusAgentsStore;
})(window);
