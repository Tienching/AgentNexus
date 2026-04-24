(function initSettingsPage(global) {
    const sections = global.NexusSettingsSections || {};
    const SettingsBasicSection = sections.SettingsBasicSection || global.SettingsBasicSection;
    const SettingsExtensionsSection = sections.SettingsExtensionsSection || global.SettingsExtensionsSection;
    const SettingsSafetySection = sections.SettingsSafetySection || global.SettingsSafetySection;

    if (!SettingsBasicSection || !SettingsExtensionsSection || !SettingsSafetySection) {
        throw new Error('Settings section modules must load before settings-page.js');
    }

    class SettingsPage {
        constructor(app) {
            this.app = app;
            this.root = document.getElementById('settingsPageRoot');
            this.topAnchor = document.getElementById('settingsPageTopAnchor') || this.root;
            this.navButtons = Array.from(document.querySelectorAll('[data-settings-nav]'));
            this.sectionMap = {
                overview: this.topAnchor,
                basic: document.getElementById('settingsSectionBasic'),
                extensions: document.getElementById('settingsSectionExtensions'),
                safety: document.getElementById('settingsSectionSafety'),
            };
            this.sections = {
                basic: new SettingsBasicSection(app, { root: this.sectionMap.basic }),
                extensions: new SettingsExtensionsSection(app, { root: this.sectionMap.extensions }),
                safety: new SettingsSafetySection(app, { root: this.sectionMap.safety }),
            };
            this._refreshPromise = null;
            this.bindEvents();
            this.setActiveNav(this.getCurrentUrlSection() || 'overview');
        }

        bindEvents() {
            this.navButtons.forEach(btn => {
                btn.addEventListener('click', () => {
                    this.scrollToSection(btn.dataset.settingsNav, { syncUrl: true, replaceUrl: false });
                });
            });
        }

        normalizeSectionKey(sectionKey) {
            const key = String(sectionKey || 'overview').trim().toLowerCase();
            return ['overview', 'basic', 'extensions', 'safety'].includes(key) ? key : 'overview';
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
                return normalized === 'overview' ? null : normalized;
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
            });
        }

        scrollToSection(sectionKey, { syncUrl = false, replaceUrl = false } = {}) {
            const key = this.normalizeSectionKey(sectionKey);
            const section = this.sectionMap[key];
            if (!section) return;
            this.setActiveNav(key);
            if (syncUrl) {
                this.app.pageManager?.syncSettingsSection?.(key === 'overview' ? null : key, { replace: replaceUrl });
            }

            // Scroll within the Settings container (the actual scroll parent) rather
            // than relying on browser-wide scrollIntoView, which may pick the wrong
            // ancestor and leave sticky nav/sections visually overlapping.
            const container = this.root;
            if (container && container.contains(section)) {
                if (key === 'overview') {
                    container.scrollTo({ top: 0, behavior: 'smooth' });
                } else {
                    // Account for sticky short-nav (≈64px) + a little breathing room.
                    const stickyOffset = 72;
                    const top = Math.max(0, section.offsetTop - stickyOffset);
                    container.scrollTo({ top, behavior: 'smooth' });
                }
            } else {
                section.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
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
            await this.sections.basic.refresh();
            await this.sections.extensions.refresh();
            await this.sections.safety.refresh();
            this.setActiveNav(this.getCurrentUrlSection() || 'overview');
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
