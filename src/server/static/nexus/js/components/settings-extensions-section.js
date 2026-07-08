(function initSettingsExtensionsSection(global) {
    class SettingsExtensionsSection {
        constructor(app, options = {}) {
            this.app = app;
            this.root = options.root || document.querySelector('[data-settings-section="skills"]');
            this.summary = document.getElementById('settingsSkillsSummary');
        }

        async refresh() {
            if (!this.root) return;
            this.renderSummary();
            await this.app.configView?.renderSkills?.();
        }

        renderSummary() {
            if (!this.summary) return;

            const defaultProviders = this.app.getDefaultProviders?.() || [];
            const aliases = this.app.getCustomProviderNames?.() || [];
            const allProviders = this.app.getAllProviders?.() || [...defaultProviders, ...aliases];

            this.summary.innerHTML = `
                <div class="admin-cards">
                    <div class="admin-card">
                        <div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Providers</span><span class="admin-metric-value">${allProviders.length}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Aliases</span><span class="admin-metric-value">${aliases.length}</span></div>
                        </div>
                    </div>
                    <div class="admin-card">
                        <div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Scope</span><span class="admin-metric-value">Skills</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Source</span><span class="admin-metric-value">Provider dirs</span></div>
                        </div>
                    </div>
                </div>
            `;
        }
    }

    global.SettingsExtensionsSection = SettingsExtensionsSection;
    global.NexusSettingsSections = global.NexusSettingsSections || {};
    global.NexusSettingsSections.SettingsExtensionsSection = SettingsExtensionsSection;
})(window);
