(function initSettingsPage(global) {
    const sections = global.NexusSettingsSections || {};
    const SettingsBasicSection = sections.SettingsBasicSection || global.SettingsBasicSection;
    const SettingsExtensionsSection = sections.SettingsExtensionsSection || global.SettingsExtensionsSection;
    const SettingsSafetySection = sections.SettingsSafetySection || global.SettingsSafetySection;

    if (!SettingsBasicSection || !SettingsExtensionsSection || !SettingsSafetySection) {
        throw new Error('Settings section modules must load before settings-page.js');
    }

    const SECTION_ALIASES = Object.freeze({
        basic: 'provider',
        provider: 'provider',
        extensions: 'skills',
        skills: 'skills',
        safety: 'runtime',
        runtime: 'runtime',
    });

    class SettingsPage {
        constructor(app) {
            this.app = app;
            this.root = document.getElementById('settingsPageRoot');
            this.topAnchor = document.getElementById('settingsPageTopAnchor') || this.root;
            this.navButtons = Array.from(document.querySelectorAll('[data-settings-nav]'));
            this.subNavButtons = Array.from(document.querySelectorAll('[data-settings-subnav]'));
            this.sectionMap = {
                provider: document.getElementById('settingsSectionBasic'),
                skills: document.getElementById('settingsSectionSkills'),
                runtime: document.getElementById('settingsSectionSafety'),
            };
            this.defaultSubPanels = {
                provider: 'provider-default',
            };
            this.sections = {
                provider: new SettingsBasicSection(app, { root: this.sectionMap.provider }),
                skills: new SettingsExtensionsSection(app, { root: this.sectionMap.skills }),
                runtime: new SettingsSafetySection(app, { root: this.sectionMap.runtime }),
            };
            this._refreshPromise = null;
            this.activeSection = this.getCurrentUrlSection() || 'provider';
            this.bindEvents();
            this.setActiveSection(this.activeSection);
        }

        bindEvents() {
            this.navButtons.forEach(btn => {
                btn.addEventListener('click', () => {
                    this.showSection(btn.dataset.settingsNav, { syncUrl: true, replaceUrl: false });
                });
            });
            this.subNavButtons.forEach(btn => {
                btn.addEventListener('click', () => {
                    this.showSubPanel(btn.dataset.settingsSubnav);
                });
            });
        }

        normalizeSectionKey(sectionKey) {
            const key = String(sectionKey || 'provider').trim().toLowerCase();
            if (key === 'overview') return 'provider';
            return SECTION_ALIASES[key] || 'provider';
        }

        getCurrentUrlSection() {
            try {
                const url = new URL(window.location.href);
                if ((url.searchParams.get('page') || 'chat').trim().toLowerCase() !== 'settings') {
                    return null;
                }
                const raw = url.searchParams.get('settingsSection');
                if (!raw) return null;
                const normalized = this.normalizeSectionKey(raw);
                return normalized;
            } catch {
                return null;
            }
        }

        setActiveNav(sectionKey) {
            const normalized = this.normalizeSectionKey(sectionKey);
            this.navButtons.forEach(btn => {
                const isActive = btn.dataset.settingsNav === normalized;
                btn.classList.toggle('is-active', isActive);
                btn.setAttribute('aria-current', isActive ? 'true' : 'false');
                btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
            });
        }

        setActiveSection(sectionKey) {
            const key = this.normalizeSectionKey(sectionKey);
            if (!this.sectionMap[key]) return;
            this.activeSection = key;
            this.setActiveNav(key);

            Object.entries(this.sectionMap).forEach(([name, section]) => {
                if (!section) return;
                const isActive = name === key;
                section.hidden = !isActive;
                section.classList.toggle('is-active', isActive);
                section.setAttribute('aria-hidden', isActive ? 'false' : 'true');
            });
            this.ensureSubPanel(key);
        }

        getSubPanelGroup(panelKey) {
            return String(panelKey || '').split('-', 1)[0];
        }

        ensureSubPanel(sectionKey) {
            const section = this.sectionMap[sectionKey];
            if (!section) return;
            const activePanel = section.querySelector('[data-settings-subpanel].is-active');
            if (activePanel && !activePanel.hidden) return;
            const defaultPanel = this.defaultSubPanels[sectionKey];
            if (defaultPanel) {
                this.showSubPanel(defaultPanel, { resetScroll: false });
            }
        }

        showSubPanel(panelKey, { resetScroll = true } = {}) {
            const group = this.getSubPanelGroup(panelKey);
            if (!group) return;
            const panels = Array.from(document.querySelectorAll('[data-settings-subpanel]'))
                .filter(panel => this.getSubPanelGroup(panel.dataset.settingsSubpanel) === group);
            const target = panels.find(panel => panel.dataset.settingsSubpanel === panelKey);
            if (!target) return;

            panels.forEach(panel => {
                const isActive = panel === target;
                panel.hidden = !isActive;
                panel.classList.toggle('is-active', isActive);
                panel.setAttribute('aria-hidden', isActive ? 'false' : 'true');
            });

            this.subNavButtons
                .filter(btn => this.getSubPanelGroup(btn.dataset.settingsSubnav) === group)
                .forEach(btn => {
                    const isActive = btn.dataset.settingsSubnav === panelKey;
                    btn.classList.toggle('is-active', isActive);
                    btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
                });

            if (resetScroll) {
                const scrollTarget = target.closest('.config-content') || target;
                scrollTarget.scrollTo?.({ top: 0, behavior: 'smooth' });
            }
        }

        showSection(sectionKey, { syncUrl = false, replaceUrl = false } = {}) {
            const key = this.normalizeSectionKey(sectionKey);
            const section = this.sectionMap[key];
            if (!section) return;
            this.setActiveSection(key);
            if (syncUrl) {
                this.app.pageManager?.syncSettingsSection?.(key, { replace: replaceUrl });
            }

            const scrollTarget = section.querySelector('.config-content, .admin-content') || section;
            if (scrollTarget?.scrollTo) {
                scrollTarget.scrollTo({ top: 0, behavior: 'smooth' });
            }
        }

        scrollToSection(sectionKey, options = {}) {
            this.showSection(sectionKey, options);
        }

        refresh() {
            if (this._refreshPromise) {
                return this._refreshPromise;
            }

            this._refreshPromise = this._refresh().finally(() => {
                this._refreshPromise = null;
            });
            return this._refreshPromise;
        }

        async _refresh() {
            await this.sections.provider.refresh();
            await this.sections.skills.refresh();
            await this.sections.runtime.refresh();
            this.setActiveSection(this.getCurrentUrlSection() || this.activeSection || 'provider');
        }
    }

    global.SettingsPage = SettingsPage;
    global.NexusSettingsPage = Object.freeze({
        SettingsPage,
        SettingsBasicSection,
        SettingsExtensionsSection,
        SettingsSafetySection,
    });
})(window);
