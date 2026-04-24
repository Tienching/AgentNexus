(function initSettingsBasicSection(global) {
    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    class SettingsBasicSection {
        constructor(app, options = {}) {
            this.app = app;
            this.root = options.root || document.querySelector('[data-settings-section="basic"]');
            this.summary = document.getElementById('settingsBasicSummary');
            this.overviewPanel = document.getElementById('settingsBasicOverviewPanel');
            this.onboardingPanel = document.getElementById('settingsBasicOnboardingPanel');
            this.runtimesPanel = document.getElementById('settingsBasicRuntimesPanel');
        }

        async refresh() {
            if (!this.root) return;
            this.renderSummary();
            this.app.configView?.renderParameters?.();
            await this._renderAdminPanel('renderOverview', this.overviewPanel);
            await this._renderAdminPanel('renderOnboardingTab', this.onboardingPanel);
            await this._renderAdminPanel('renderRuntimes', this.runtimesPanel);
        }

        renderSummary() {
            if (!this.summary) return;

            const defaultProvider = this.app.getDefaultProvider?.() || 'nexus';
            const aliases = Array.isArray(this.app.customProviders) ? this.app.customProviders.length : 0;
            const agents = Array.isArray(this.app.availableAgents) ? this.app.availableAgents.length : 0;
            const execUser = this.app.getDefaultExecUser?.() || 'ubuntu';

            this.summary.innerHTML = `
                <div class="admin-cards">
                    <div class="admin-card">
                        <div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Default Provider</span><span class="admin-metric-value">${escapeHtml(defaultProvider)}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Custom Aliases</span><span class="admin-metric-value">${aliases}</span></div>
                        </div>
                    </div>
                    <div class="admin-card">
                        <div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Available Agents</span><span class="admin-metric-value">${agents}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Exec User</span><span class="admin-metric-value">${escapeHtml(execUser)}</span></div>
                        </div>
                    </div>
                </div>
            `;
        }

        async _renderAdminPanel(methodName, container) {
            if (!container || !this.app.adminView || typeof this.app.adminView[methodName] !== 'function') {
                return;
            }

            // Clear stale content so async renders don't overlap across sections.
            container.innerHTML = '';

            const previousContainer = this.app.adminView.container;
            this.app.adminView.container = container;
            try {
                await this.app.adminView[methodName]();
            } catch (error) {
                container.innerHTML = `<div class="admin-error">${escapeHtml(error.message || 'Failed to load section')}</div>`;
            } finally {
                if (this.app.adminView.container === container) {
                    this.app.adminView.container = previousContainer;
                }
            }
        }
    }

    global.SettingsBasicSection = SettingsBasicSection;
    global.NexusSettingsSections = global.NexusSettingsSections || {};
    global.NexusSettingsSections.SettingsBasicSection = SettingsBasicSection;
})(window);
