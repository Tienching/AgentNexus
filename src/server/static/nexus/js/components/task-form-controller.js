/**
 * NexusTaskFormController
 *
 * Owns the create-task / schedule modal state machine and submission logic.
 * The app shell keeps compatibility wrappers, but the actual orchestration
 * lives here so task-domain behavior stays co-located with task UI.
 */
class NexusTaskFormController {
    constructor(app) {
        this.app = app || null;
        this._bound = false;
    }

    _getChatView() {
        return this.app?.chatView || null;
    }

    _getTaskBoardPanel() {
        return this.app?.taskBoardPanel || null;
    }

    _escapeHtml(value) {
        const chatView = this._getChatView();
        if (chatView && typeof chatView.escapeHtml === 'function') {
            return chatView.escapeHtml(value);
        }
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    _normalizeProviderName(provider) {
        if (this.app && typeof this.app.normalizeProviderName === 'function') {
            return this.app.normalizeProviderName(provider);
        }
        return String(provider || '').trim().toLowerCase();
    }

    _getDefaultProviders() {
        if (this.app && typeof this.app.getDefaultProviders === 'function') {
            return this.app.getDefaultProviders();
        }
        return ['nexus', 'claude', 'gemini', 'codex', 'codebuddy'];
    }

    _getCustomProviderNames() {
        if (this.app && typeof this.app.getCustomProviderNames === 'function') {
            return this.app.getCustomProviderNames();
        }
        return [];
    }

    _getDefaultProvider() {
        if (this.app && typeof this.app.getDefaultProvider === 'function') {
            return this.app.getDefaultProvider();
        }
        return 'claude';
    }

    _getServerCurrentWorkdir() {
        return String(this.app?.serverDefaults?.current_workdir || '').trim();
    }

    _normalizeWorkspaceInput(workspace) {
        const raw = String(workspace || '').trim();
        if (!raw) return '';
        if (raw.startsWith('~') || raw.startsWith('/')) {
            return raw;
        }
        const base = this._getServerCurrentWorkdir();
        if (!base) return raw;
        return `${base.replace(/\/+$/, '')}/${raw.replace(/^\.?\/*/, '')}`;
    }

    _isCustomAlias(name) {
        return !!(this.app && typeof this.app.isCustomAlias === 'function' && this.app.isCustomAlias(name));
    }

    _getBaseProvider(name) {
        if (this.app && typeof this.app.getBaseProvider === 'function') {
            return this.app.getBaseProvider(name);
        }
        return null;
    }

    bindModalEvents() {
        if (this._bound) return;
        this._bound = true;

        document.querySelectorAll('input[name="triggerMode"]').forEach(radio => {
            radio.addEventListener('change', () => {
                const mode = document.querySelector('input[name="triggerMode"]:checked')?.value || 'immediate';
                const cronFields = document.getElementById('cronFields');
                const onetimeFields = document.getElementById('onetimeFields');
                const scheduleExtra = document.getElementById('scheduleExtraFields');
                const cronExtra = document.getElementById('cronExtraFields');
                if (cronFields) cronFields.hidden = mode !== 'cron';
                if (onetimeFields) onetimeFields.hidden = mode !== 'onetime';
                if (scheduleExtra) scheduleExtra.hidden = mode === 'immediate';
                if (cronExtra) cronExtra.hidden = mode !== 'cron';
                this._updateSubmitButtonText();
            });
        });

        document.querySelectorAll('input[name="loopMode"]').forEach(radio => {
            radio.addEventListener('change', () => {
                const mode = document.querySelector('input[name="loopMode"]:checked')?.value || 'normal';
                const loopFields = document.getElementById('loopFields');
                if (loopFields) loopFields.hidden = mode !== 'loop';
            });
        });

        const submitBtn = document.getElementById('submitTaskBtn');
        if (submitBtn) {
            submitBtn.addEventListener('click', () => this.submit());
        }

        const scheduleParseBtn = document.getElementById('scheduleNaturalParseBtn');
        if (scheduleParseBtn) {
            scheduleParseBtn.addEventListener('click', () => this.parseScheduleNaturalLanguage());
        }

        const saveScheduleBtn = document.getElementById('saveScheduleBtn');
        if (saveScheduleBtn) {
            saveScheduleBtn.addEventListener('click', async () => {
                const scheduleId = document.getElementById('editScheduleId')?.value;
                if (!scheduleId) return;

                const name = document.getElementById('editScheduleName')?.value.trim();
                const cronExpression = document.getElementById('editScheduleCron')?.value.trim();
                const timezone = document.getElementById('editScheduleTimezone')?.value.trim();
                const description = document.getElementById('editScheduleDescription')?.value.trim();
                const workspace = document.getElementById('editScheduleWorkspace')?.value.trim();
                const maxRunsStr = document.getElementById('editScheduleMaxRuns')?.value.trim();

                if (!name) { this.showToast('Schedule name is required', 'error'); return; }
                if (!cronExpression) { this.showToast('Cron expression is required', 'error'); return; }
                if (!description) { this.showToast('Task description is required', 'error'); return; }

                const payload = {};
                if (name) payload.name = name;
                if (cronExpression) payload.cron_expression = cronExpression;
                if (timezone) payload.timezone = timezone;
                if (description) payload.description = description;
                payload.workspace = this._normalizeWorkspaceInput(workspace) || null;
                if (maxRunsStr) {
                    const maxRuns = parseInt(maxRunsStr, 10);
                    if (!isNaN(maxRuns) && maxRuns > 0) payload.max_runs = maxRuns;
                }

                try {
                    await NexusAPI.updateSchedule(scheduleId, payload);
                    this.showToast('Schedule updated', 'success');
                    document.getElementById('editScheduleModal')?.classList.remove('open');
                    this._getTaskBoardPanel()?.refreshSchedules({ force: true, onlyIfVisible: true });
                } catch (error) {
                    this.showToast(error.message || 'Failed to update schedule', 'error');
                }
            });
        }
    }

    refreshSelectors() {
        const modal = document.getElementById('createTaskModal');
        if (!modal || !modal.classList.contains('open')) return;

        const globalUserFilter = document.getElementById('globalUserFilter');
        const selectedUser = globalUserFilter?.value || '';
        const allAgents = this._getChatView()?.getAvailableAgents('') || [];
        const rawUsernames = [...new Set(allAgents.map(agent => agent.username))];
        const usernames = rawUsernames.length ? rawUsernames : [NexusAPI.getDefaultExecUser()];
        const fallbackUser = (selectedUser && usernames.includes(selectedUser))
            ? selectedUser
            : (usernames.includes(NexusAPI.getDefaultExecUser()) ? NexusAPI.getDefaultExecUser() : (usernames[0] || NexusAPI.getDefaultExecUser()));

        const buildModelOptions = (user) => {
            const agents = this._getChatView()?.getAvailableAgents(user) || [];
            const agentModels = [...new Set(agents.map(agent => this._normalizeProviderName(agent.agent_type)))];
            const allModels = [...new Set([...this._getDefaultProviders(), ...this._getCustomProviderNames(), ...agentModels])];
            if (!allModels.length) {
                return '<option value="claude">claude</option>';
            }
            const getModelLabel = (model) => {
                if (this._isCustomAlias(model)) {
                    const baseProvider = this._getBaseProvider(model);
                    if (baseProvider) {
                        return `${model} (${baseProvider})`;
                    }
                }
                return model;
            };
            return allModels.map(model => {
                const label = getModelLabel(model);
                return `<option value="${this._escapeHtml(model)}">${this._escapeHtml(label)}</option>`;
            }).join('');
        };

        const updateSelectors = (userSelectId, modelSelectId) => {
            const userSelect = document.getElementById(userSelectId);
            const modelSelect = document.getElementById(modelSelectId);
            if (!modelSelect) return;

            const currentUser = userSelect?.value || fallbackUser;
            const resolvedUser = usernames.includes(currentUser) ? currentUser : fallbackUser;

            if (userSelect) {
                userSelect.innerHTML = usernames.map(u => `<option value="${this._escapeHtml(u)}">${this._escapeHtml(u)}</option>`).join('');
                userSelect.value = resolvedUser;
            }

            const currentModel = modelSelect.value;
            modelSelect.innerHTML = buildModelOptions(resolvedUser);
            const optionValues = Array.from(modelSelect.options).map(opt => opt.value);
            const defaultPref = this._getDefaultProvider();
            const selected = optionValues.includes(currentModel)
                ? currentModel
                : (optionValues.includes(defaultPref) ? defaultPref : (optionValues[0] || 'claude'));
            modelSelect.value = selected;
            this._loadTaskSourceSessionOptions(resolvedUser).catch(err => {
                console.warn('Failed to refresh source sessions:', err);
            });
        };

        updateSelectors('taskUser', 'taskProvider');
    }

    showCreateTaskModal(mode = 'single') {
        const modal = document.getElementById('createTaskModal');
        if (!modal) return;

        const taskName = document.getElementById('taskName');
        if (taskName) taskName.value = '';
        const taskDescription = document.getElementById('taskDescription');
        if (taskDescription) taskDescription.value = '';
        const taskLlmModel = document.getElementById('taskLlmModel');
        if (taskLlmModel) taskLlmModel.value = '';
        const taskWorkspace = document.getElementById('taskWorkspace');
        if (taskWorkspace) taskWorkspace.value = this._getServerCurrentWorkdir();
        const taskDependsOn = document.getElementById('taskDependsOn');
        if (taskDependsOn) taskDependsOn.value = '';
        const taskSourceSession = document.getElementById('taskSourceSession');
        if (taskSourceSession) {
            taskSourceSession.innerHTML = '<option value="">None (new task run)</option>';
            taskSourceSession.value = '';
        }

        const normalRadio = document.querySelector('input[name="loopMode"][value="normal"]');
        if (normalRadio) normalRadio.checked = true;
        const loopFieldsDiv = document.getElementById('loopFields');
        if (loopFieldsDiv) loopFieldsDiv.hidden = true;
        const loopKeywords = document.getElementById('loopKeywords');
        if (loopKeywords) loopKeywords.value = '';
        const loopMaxIterations = document.getElementById('loopMaxIterations');
        if (loopMaxIterations) loopMaxIterations.value = '5';

        const immediateRadio = document.querySelector('input[name="triggerMode"][value="immediate"]');
        if (immediateRadio) immediateRadio.checked = true;
        const cronFields = document.getElementById('cronFields');
        if (cronFields) cronFields.hidden = true;
        const onetimeFields = document.getElementById('onetimeFields');
        if (onetimeFields) onetimeFields.hidden = true;
        const scheduleExtra = document.getElementById('scheduleExtraFields');
        if (scheduleExtra) scheduleExtra.hidden = true;
        const cronExtra = document.getElementById('cronExtraFields');
        if (cronExtra) cronExtra.hidden = true;

        const scheduleCron = document.getElementById('scheduleCron');
        if (scheduleCron) scheduleCron.value = '';
        const scheduleRunAt = document.getElementById('scheduleRunAt');
        if (scheduleRunAt) scheduleRunAt.value = '';
        const scheduleTimezone = document.getElementById('scheduleTimezone');
        if (scheduleTimezone) scheduleTimezone.value = 'UTC';
        const scheduleMaxRuns = document.getElementById('scheduleMaxRuns');
        if (scheduleMaxRuns) scheduleMaxRuns.value = '';
        const scheduleNaturalInput = document.getElementById('scheduleNaturalInput');
        if (scheduleNaturalInput) scheduleNaturalInput.value = '';
        const scheduleNaturalResult = document.getElementById('scheduleNaturalResult');
        if (scheduleNaturalResult) {
            scheduleNaturalResult.textContent = '';
            scheduleNaturalResult.className = 'form-hint';
        }

        this._updateSubmitButtonText();
        this._refreshTaskSelectorsForModal(mode);
        modal.classList.add('open');
    }

    _refreshTaskSelectorsForModal(mode = 'single') {
        const globalUserFilter = document.getElementById('globalUserFilter');
        const selectedUser = globalUserFilter?.value || '';
        const allAgents = this._getChatView()?.getAvailableAgents('') || [];
        const rawUsernames = [...new Set(allAgents.map(agent => agent.username))];
        const usernames = rawUsernames.length ? rawUsernames : [NexusAPI.getDefaultExecUser()];
        const initialUser = (selectedUser && usernames.includes(selectedUser))
            ? selectedUser
            : (usernames.includes(NexusAPI.getDefaultExecUser()) ? NexusAPI.getDefaultExecUser() : (usernames[0] || NexusAPI.getDefaultExecUser()));

        const buildModelOptions = (user) => {
            const agents = this._getChatView()?.getAvailableAgents(user) || [];
            const agentModels = [...new Set(agents.map(agent => this._normalizeProviderName(agent.agent_type)))];
            const allModels = [...new Set([...this._getDefaultProviders(), ...this._getCustomProviderNames(), ...agentModels])];
            if (!allModels.length) {
                return '<option value="claude">claude</option>';
            }
            const getModelLabel = (model) => {
                if (this._isCustomAlias(model)) {
                    const baseProvider = this._getBaseProvider(model);
                    if (baseProvider) {
                        return `${model} (${baseProvider})`;
                    }
                }
                return model;
            };
            return allModels.map(model => {
                const label = getModelLabel(model);
                return `<option value="${this._escapeHtml(model)}">${this._escapeHtml(label)}</option>`;
            }).join('');
        };

        const setupAgentSelectors = (userSelectId, modelSelectId, preferredUser = initialUser, preferredModel = null) => {
            const userSelect = document.getElementById(userSelectId);
            const modelSelect = document.getElementById(modelSelectId);
            if (!modelSelect) return;

            const defaultModel = preferredModel || this._getDefaultProvider();

            const applyModelOptions = (user) => {
                modelSelect.innerHTML = buildModelOptions(user);
                const optionValues = Array.from(modelSelect.options).map(opt => opt.value);
                const selected = optionValues.includes(defaultModel) ? defaultModel : (optionValues[0] || 'claude');
                modelSelect.value = selected;
                this._loadTaskSourceSessionOptions(user).catch(err => {
                    console.warn('Failed to load source sessions:', err);
                });
            };

            if (userSelect) {
                userSelect.innerHTML = usernames.map(u => `<option value="${this._escapeHtml(u)}">${this._escapeHtml(u)}</option>`).join('');
                userSelect.value = preferredUser;
                applyModelOptions(preferredUser);
                userSelect.onchange = () => {
                    const user = userSelect.value || preferredUser;
                    applyModelOptions(user);
                };
            } else {
                applyModelOptions(preferredUser);
            }
        };

        setupAgentSelectors('taskUser', 'taskProvider');
    }

    getTaskAgentSelection() {
        const globalUserFilter = document.getElementById('globalUserFilter');
        const execUser = document.getElementById('taskUser')?.value || globalUserFilter?.value || NexusAPI.getDefaultExecUser();
        const providerSelection = document.getElementById('taskProvider')?.value || this._getDefaultProvider();
        return { execUser, providerSelection };
    }

    resolveProviderSelection(providerSelection) {
        const normalizedSelection = this._normalizeProviderName(providerSelection || this._getDefaultProvider() || 'nexus');
        const defaultProviders = this._getDefaultProviders();
        const baseProvider = defaultProviders.includes(normalizedSelection)
            ? normalizedSelection
            : ((this._getBaseProvider(normalizedSelection))
                || defaultProviders.find(providerName => normalizedSelection.startsWith(`${providerName}-`))
                || normalizedSelection);
        return { provider: baseProvider, alias: normalizedSelection };
    }

    resolveTaskModel(selectedProvider, aliasValue, explicitModel) {
        return explicitModel
            || this.app?.getProviderDefaultModel?.(aliasValue)
            || this.app?.getProviderDefaultModel?.(selectedProvider)
            || undefined;
    }

    getLoopConfig() {
        const loopEnabled = document.querySelector('input[name="loopMode"]:checked')?.value === 'loop';
        if (!loopEnabled) return null;

        const keywordsStr = document.getElementById('loopKeywords')?.value.trim();
        if (!keywordsStr) {
            throw new Error('Please enter at least one stop keyword for Ralph Loop');
        }

        const keywords = keywordsStr.split(',').map(keyword => keyword.trim()).filter(Boolean);
        if (keywords.length === 0) {
            throw new Error('Please enter at least one valid stop keyword');
        }

        const maxIterations = parseInt(document.getElementById('loopMaxIterations')?.value.trim(), 10);
        if (Number.isNaN(maxIterations) || maxIterations < 1 || maxIterations > 100) {
            throw new Error('Max iterations must be between 1 and 100');
        }

        return {
            loop_enabled: true,
            loop_max_iterations: maxIterations,
            loop_keywords: keywords,
        };
    }

    async submit() {
        const { execUser, providerSelection } = this.getTaskAgentSelection();
        const triggerMode = document.querySelector('input[name="triggerMode"]:checked')?.value || 'immediate';
        const isScheduledTask = triggerMode === 'cron' || triggerMode === 'onetime';

        try {
            if (isScheduledTask) {
                await this._submitSchedule(execUser, providerSelection, triggerMode);
            } else {
                await this._submitSingleTask(execUser, providerSelection);
            }

            document.getElementById('createTaskModal')?.classList.remove('open');
            if (isScheduledTask) {
                this._getTaskBoardPanel()?.refreshSchedules({ force: true, onlyIfVisible: true });
            } else {
                this._getTaskBoardPanel()?.refreshTasks({ force: true });
                this._getTaskBoardPanel()?.startAutoPolling?.();
            }
        } catch (error) {
            console.error('Failed to create task:', error);
            this.showToast(error.message || 'Failed to create task', 'error');
        }
    }

    async _submitSingleTask(execUser, providerSelection) {
        const description = document.getElementById('taskDescription')?.value.trim();
        const workspace = document.getElementById('taskWorkspace')?.value.trim();
        const dependsOnStr = document.getElementById('taskDependsOn')?.value.trim();
        const llmModel = document.getElementById('taskLlmModel')?.value.trim();
        const { provider: selectedProvider, alias: aliasValue } = this.resolveProviderSelection(providerSelection);
        const loopConfig = this.getLoopConfig();

        if (!description) {
            throw new Error('Description is required');
        }

        const targetSessionId = document.getElementById('taskSourceSession')?.value?.trim();
        const payload = {
            description,
            provider: selectedProvider,
            alias: aliasValue,
            model: this.resolveTaskModel(selectedProvider, aliasValue, llmModel),
            workspace: this._normalizeWorkspaceInput(workspace) || undefined,
            session_id: targetSessionId || undefined,
            depends_on: dependsOnStr ? dependsOnStr.split(',').map(s => s.trim()).filter(Boolean) : undefined,
            ...(loopConfig || {}),
        };

        await NexusAPI.createTask(payload, { execUser });
        const msg = loopConfig
            ? `Loop task created (max ${loopConfig.loop_max_iterations} iterations)`
            : 'Task created successfully';
        this.showToast(msg, 'success');
    }

    async _submitSchedule(execUser, providerSelection, triggerMode) {
        const description = document.getElementById('taskDescription')?.value.trim();
        const name = document.getElementById('taskName')?.value.trim();
        const timezone = document.getElementById('scheduleTimezone')?.value.trim() || 'UTC';
        const workspace = document.getElementById('taskWorkspace')?.value.trim();
        const llmModel = document.getElementById('taskLlmModel')?.value.trim();
        const maxRunsStr = document.getElementById('scheduleMaxRuns')?.value.trim();
        const { provider: selectedProvider, alias: aliasValue } = this.resolveProviderSelection(providerSelection);
        const loopConfig = this.getLoopConfig();

        if (!description) throw new Error('Description is required');
        if (!name) throw new Error('Please enter a name for the schedule');

        const payload = {
            name,
            timezone,
            description,
            provider: selectedProvider,
            alias: aliasValue,
            exec_user: execUser,
        };

        if (triggerMode === 'cron') {
            const cronExpression = document.getElementById('scheduleCron')?.value.trim();
            if (!cronExpression) throw new Error('Please enter a cron expression');
            payload.cron_expression = cronExpression;
        } else {
            const runAtStr = document.getElementById('scheduleRunAt')?.value.trim();
            if (!runAtStr) throw new Error('Please select a date and time');
            const runAtDate = new Date(runAtStr);
            if (Number.isNaN(runAtDate.getTime())) throw new Error('Invalid date/time value');
            payload.run_at = runAtDate.toISOString();
        }

        if (workspace) payload.workspace = this._normalizeWorkspaceInput(workspace);
        if (llmModel) payload.model = llmModel;
        if (maxRunsStr) {
            const maxRuns = parseInt(maxRunsStr, 10);
            if (!Number.isNaN(maxRuns) && maxRuns > 0) payload.max_runs = maxRuns;
        }
        if (loopConfig) {
            payload.context = {
                ...(payload.context || {}),
                ...loopConfig,
            };
        }

        await NexusAPI.createSchedule(payload);
        const schedLabel = triggerMode === 'cron' ? `Schedule "${name}"` : `One-time schedule "${name}"`;
        this.showToast(`${schedLabel} created`, 'success');
        this._getTaskBoardPanel()?.refreshSchedules({ force: true, onlyIfVisible: true });
    }

    async _loadTaskSourceSessionOptions(username) {
        const sourceSelect = document.getElementById('taskSourceSession');
        if (!sourceSelect) return;

        const selected = sourceSelect.value || '';
        sourceSelect.innerHTML = '<option value="">None (new task run)</option>';

        try {
            const data = await NexusAPI.getSessions({
                username: username || undefined,
                page: 1,
                pageSize: 100,
            });
            const sessions = Array.isArray(data?.sessions) ? data.sessions : [];
            sessions.forEach((session) => {
                const sid = session?.id || '';
                if (!sid) return;
                const title = session?.title || sid;
                const label = `${title} (${sid.slice(0, 8)})`;
                sourceSelect.insertAdjacentHTML(
                    'beforeend',
                    `<option value="${this._escapeHtml(sid)}">${this._escapeHtml(label)}</option>`,
                );
            });
            if (selected && sessions.some((s) => (s?.id || '') === selected)) {
                sourceSelect.value = selected;
            }
        } catch (error) {
            console.warn('Unable to load task source sessions', error);
        }
    }

    async parseScheduleNaturalLanguage() {
        const inputEl = document.getElementById('scheduleNaturalInput');
        const resultEl = document.getElementById('scheduleNaturalResult');
        const input = inputEl?.value?.trim();

        if (!input) {
            if (resultEl) {
                resultEl.textContent = 'Enter a natural-language schedule first.';
                resultEl.className = 'form-hint task-form-status task-form-status-warning';
            }
            return;
        }

        try {
            const parsed = await NexusAPI.parseSchedule(input);
            const cronExpr = parsed?.cronExpr || parsed?.cron_expr;
            const humanReadable = parsed?.humanReadable || parsed?.human_readable || '';

            if (!cronExpr) {
                if (resultEl) {
                    resultEl.textContent = parsed?.error || 'Could not parse schedule expression.';
                    resultEl.className = 'form-hint task-form-status task-form-status-error';
                }
                return;
            }

            const cronInput = document.getElementById('scheduleCron');
            if (cronInput) cronInput.value = cronExpr;

            const cronRadio = document.querySelector('input[name="triggerMode"][value="cron"]');
            if (cronRadio) {
                cronRadio.checked = true;
                cronRadio.dispatchEvent(new Event('change'));
            }

            if (resultEl) {
                resultEl.textContent = humanReadable
                    ? `${humanReadable} → ${cronExpr}`
                    : `Parsed cron: ${cronExpr}`;
                resultEl.className = 'form-hint task-form-status task-form-status-success';
            }
        } catch (error) {
            if (resultEl) {
                resultEl.textContent = error.message || 'Failed to parse schedule expression.';
                resultEl.className = 'form-hint task-form-status task-form-status-error';
            }
        }
    }

    _updateSubmitButtonText() {
        const btn = document.getElementById('submitTaskBtn');
        if (!btn) return;
        const triggerMode = document.querySelector('input[name="triggerMode"]:checked')?.value || 'immediate';
        btn.textContent = (triggerMode === 'cron' || triggerMode === 'onetime')
            ? 'Create Schedule'
            : 'Create Task';
    }

    showToast(message, type = 'info') {
        if (this.app && typeof this.app.showToast === 'function') {
            this.app.showToast(message, type);
        }
    }
}

window.NexusTaskFormController = NexusTaskFormController;
