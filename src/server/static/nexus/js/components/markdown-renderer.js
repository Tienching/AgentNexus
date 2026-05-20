/**
 * MarkdownRenderer component
 *
 * Lightweight markdown renderer with:
 * - fenced code blocks
 * - basic syntax highlight (keyword spans)
 * - headings, lists, blockquote, hr, links, inline code
 * - preview rendering helper
 */
class MarkdownRenderer {
    constructor(options = {}) {
        this.customRender = typeof options.renderFn === 'function' ? options.renderFn : null;
        this.escapeHtml = options.escapeHtml || MarkdownRenderer.escapeHtml;
    }

    setRenderFn(renderFn) {
        this.customRender = typeof renderFn === 'function' ? renderFn : null;
    }

    render(content) {
        const text = String(content ?? '');
        if (!text) return '';
        if (this.customRender) {
            return this.customRender(text);
        }
        return this.renderFallback(text);
    }

    renderPreview(content, container) {
        if (!container) return '';
        const html = this.render(content);
        container.innerHTML = html || '<p class="message-empty">Nothing to preview</p>';
        return html;
    }

    renderFallback(content) {
        const normalized = content.replace(/\r\n?/g, '\n');
        const lines = normalized.split('\n');
        const blocks = [];
        let index = 0;

        while (index < lines.length) {
            const line = lines[index] || '';
            if (!line.trim()) {
                index++;
                continue;
            }

            // Tolerate fenced blocks where the closing ``` is glued to the previous code
            // line or to the next markdown block (a common streaming artifact when the
            // model omits the trailing newline). Anything past the opening language tag
            // is re-injected as the first code line so it isn't lost.
            const fenceMatch = line.match(/^(\s*)```([\w-]*)\s*(.*)$/);
            if (fenceMatch) {
                const language = fenceMatch[2] || '';
                const openingTail = fenceMatch[3] || '';
                const codeLines = [];
                index++;
                if (openingTail) {
                    lines.splice(index, 0, openingTail);
                }
                while (index < lines.length) {
                    const current = lines[index];
                    const closeIdx = current.indexOf('```');
                    if (closeIdx === -1) {
                        codeLines.push(current);
                        index++;
                        continue;
                    }
                    const before = current.slice(0, closeIdx);
                    const after = current.slice(closeIdx + 3);
                    if (before.length > 0) codeLines.push(before);
                    const trailing = after.replace(/^[ \t]+/, '');
                    if (trailing.length > 0) {
                        lines[index] = trailing;
                    } else {
                        index++;
                    }
                    break;
                }
                const codeHtml = this.highlightCode(codeLines.join('\n'), language);
                const languageClass = language ? ` language-${this.escapeHtml(language)}` : '';
                blocks.push(`<pre class="message-code-block"><code class="md-code${languageClass}">${codeHtml}</code></pre>`);
                continue;
            }

            const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
            if (headingMatch) {
                const level = headingMatch[1].length;
                blocks.push(`<h${level}>${this.formatInline(headingMatch[2])}</h${level}>`);
                index++;
                continue;
            }

            if (/^([-*_])(?:\s*\1){2,}\s*$/.test(line.trim())) {
                blocks.push('<hr class="message-hr">');
                index++;
                continue;
            }

            if (/^\s*>\s?/.test(line)) {
                const quoteLines = [];
                while (index < lines.length && /^\s*>\s?/.test(lines[index] || '')) {
                    quoteLines.push((lines[index] || '').replace(/^\s*>\s?/, ''));
                    index++;
                }
                blocks.push(`<blockquote class="message-blockquote">${quoteLines.map((q) => `<p>${this.formatInline(q)}</p>`).join('')}</blockquote>`);
                continue;
            }

            if (/^\s*[-*+]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
                const ordered = /^\s*\d+\.\s+/.test(line);
                const tag = ordered ? 'ol' : 'ul';
                const items = [];
                while (index < lines.length) {
                    const current = lines[index] || '';
                    if (!current.trim()) break;
                    if (ordered && !/^\s*\d+\.\s+/.test(current)) break;
                    if (!ordered && !/^\s*[-*+]\s+/.test(current)) break;
                    items.push(current.replace(ordered ? /^\s*\d+\.\s+/ : /^\s*[-*+]\s+/, ''));
                    index++;
                }
                blocks.push(`<${tag}>${items.map((item) => `<li>${this.formatInline(item)}</li>`).join('')}</${tag}>`);
                continue;
            }

            const para = [line];
            index++;
            while (index < lines.length && lines[index] && lines[index].trim()) {
                const nxt = lines[index];
                if (/^```/.test(nxt) || /^(#{1,6})\s+/.test(nxt) || /^\s*>\s?/.test(nxt) || /^\s*[-*+]\s+/.test(nxt) || /^\s*\d+\.\s+/.test(nxt)) {
                    break;
                }
                para.push(nxt);
                index++;
            }
            blocks.push(`<p>${para.map((p) => this.formatInline(p)).join('<br>')}</p>`);
        }

        return blocks.join('');
    }

    formatInline(text) {
        if (!text) return '';
        const tokens = [];
        const createToken = (html) => `@@MD_TOKEN_${tokens.push(html) - 1}@@`;
        let formatted = String(text);

        formatted = formatted.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, label, url) => {
            const safe = this.sanitizeUrl(url);
            if (!safe) return createToken(this.escapeHtml(`[${label}](${url})`));
            return createToken(`<a href="${safe}" target="_blank" rel="noopener noreferrer">${this.escapeHtml(label)}</a>`);
        });

        formatted = formatted.replace(/`([^`]+)`/g, (_m, code) => createToken(`<code>${this.escapeHtml(code)}</code>`));

        formatted = this.escapeHtml(formatted)
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')
            .replace(/~~([^~]+)~~/g, '<del>$1</del>');

        return formatted.replace(/@@MD_TOKEN_(\d+)@@/g, (_m, idx) => tokens[Number(idx)] ?? '');
    }

    highlightCode(code, language = '') {
        let html = this.escapeHtml(code || '');
        const keywords = this.getKeywords(language);
        if (!keywords.length) return html;

        const tokenPattern = new RegExp(`\\b(${keywords.map((k) => k.replace(/[.*+?^${}()|[\\]\\]/g, '\\$&')).join('|')})\\b`, 'g');
        html = html.replace(tokenPattern, '<span class="md-code-keyword">$1</span>');
        return html;
    }

    getKeywords(language = '') {
        const lang = String(language || '').toLowerCase();
        const common = ['const', 'let', 'var', 'class', 'function', 'return', 'if', 'else', 'for', 'while', 'try', 'catch', 'import', 'from', 'export'];
        if (lang === 'python' || lang === 'py') {
            return ['def', 'class', 'return', 'if', 'elif', 'else', 'for', 'while', 'try', 'except', 'import', 'from', 'with', 'as', 'lambda'];
        }
        if (lang === 'ts' || lang === 'tsx' || lang === 'typescript' || lang === 'js' || lang === 'jsx' || lang === 'javascript') {
            return [...common, 'async', 'await', 'new', 'extends'];
        }
        if (lang === 'bash' || lang === 'sh') {
            return ['if', 'then', 'else', 'fi', 'for', 'do', 'done', 'case', 'esac', 'function'];
        }
        return common;
    }

    sanitizeUrl(url) {
        if (!url) return '';
        const trimmed = String(url).trim();
        if (!trimmed) return '';
        try {
            if (trimmed.startsWith('/')) {
                const safe = new URL(trimmed, window.location.origin);
                return this.escapeHtml(`${safe.pathname}${safe.search}${safe.hash}`);
            }
            const parsed = new URL(trimmed);
            const protocol = parsed.protocol.toLowerCase();
            if (!['http:', 'https:', 'mailto:'].includes(protocol)) return '';
            return this.escapeHtml(parsed.href);
        } catch {
            return '';
        }
    }

    static escapeHtml(str) {
        if (str === undefined || str === null) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }
}

window.MarkdownRenderer = MarkdownRenderer;
