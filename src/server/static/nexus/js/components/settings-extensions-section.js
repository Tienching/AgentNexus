(function initSettingsExtensionsSection(global) {
    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    class SettingsExtensionsSection {
        constructor(app, options = {}) {
            this.app = app;
            this.root = options.root || document.querySelector('[data-settings-section="extensions"]');
            this.summary = document.getElementById('settingsExtensionsSummary');
            this.integrationsPanel = document.getElementById('settingsExtensionsIntegrationsPanel');
        }

        async refresh() {
            if (!this.root) return;
            this.renderSummary();
            this.app.configView?.renderMcp?.();
            await this.app.configView?.renderSkills?.();
            await this._renderAdminPanel('renderIntegrationsTab', this.integrationsPanel);
        }

        renderSummary() {
            if (!this.summary) return;

            const config = this.app.loadMcpConfig?.() || { global: [], providers: {} };
            const globalServers = Array.isArray(config.global) ? config.global.length : 0;
            const providerServers = Object.values(config.providers || {}).reduce((sum, list) => sum + (Array.isArray(list) ? list.length : 0), 0);
            const providerCount = this.app.getAllProviders?.().length || 0;
            const aliasCount = this.app.getCustomProviderNames?.().length || 0;

            this.summary.innerHTML = `
                <div class="admin-cards">
                    <div class="admin-card">
                        <div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Global MCP</span><span class="admin-metric-value">${globalServers}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Provider MCP</span><span class="admin-metric-value">${providerServers}</span></div>
                        </div>
                    </div>
                    <div class="admin-card">
                        <div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Providers</span><span class="admin-metric-value">${providerCount}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Aliases with Extensions</span><span class="admin-metric-value">${aliasCount}</span></div>
                        </div>
                    </div>
                </div>
                <div class="u-text-secondary u-text-sm u-mt-sm">Use this section for MCP servers, skills, and integrations. Workflow and schedule tools now live under Task.</div>
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

    global.SettingsExtensionsSection = SettingsExtensionsSection;
    global.NexusSettingsSections = global.NexusSettingsSections || {};
    global.NexusSettingsSections.SettingsExtensionsSection = SettingsExtensionsSection;
})(window);
