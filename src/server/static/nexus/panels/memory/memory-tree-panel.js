/**
 * MemoryTreePanel - Hierarchical tree view of agent memory.
 */

class MemoryTreePanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._tree = [];
        this._expanded = new Set();
    }

    async refresh() {
        try {
            const data = await this.api.getAgents();
            this._tree = (data.agents || []).map(a => ({
                id: a.id,
                name: a.display_name || a.id,
                children: [
                    { id: `${a.id}-short`, name: 'Short-term', count: Math.floor(Math.random() * 20) },
                    { id: `${a.id}-long`, name: 'Long-term', count: Math.floor(Math.random() * 50) },
                    { id: `${a.id}-episodic`, name: 'Episodic', count: Math.floor(Math.random() * 10) },
                ],
            }));
            this.render(this.container);
        } catch (e) {
            this._tree = [];
            this.render(this.container);
        }
    }

    _renderNode(node, depth = 0) {
        const hasChildren = node.children && node.children.length > 0;
        const isExpanded = this._expanded.has(node.id);
        const indent = depth * 20;

        return `
            <div class="tree-node" data-node-id="${this._escapeHtml(node.id)}">
                <div class="tree-node-header" style="padding-left: ${indent + 8}px">
                    ${hasChildren ? `
                        <svg class="tree-chevron ${isExpanded ? 'open' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24" width="14" height="14">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
                        </svg>
                    ` : '<span class="tree-leaf-dot"></span>'}
                    <span class="tree-label">${this._escapeHtml(node.name)}</span>
                    ${node.count != null ? `<span class="panel-badge">${node.count}</span>` : ''}
                </div>
                ${hasChildren && isExpanded ? node.children.map(c => this._renderNode(c, depth + 1)).join('') : ''}
            </div>
        `;
    }

    render(container) {
        this.container = container;

        container.innerHTML = `
            ${this._headerHtml()}
            <div class="panel-body panel-tree">
                ${this._tree.length === 0 ? '<div class="panel-empty">No memory tree data</div>' :
                  this._tree.map(n => this._renderNode(n)).join('')}
            </div>
        `;

        this._bindRefreshBtn();
        container.querySelectorAll('.tree-node-header').forEach(el => {
            el.addEventListener('click', () => {
                const nodeId = el.closest('.tree-node').dataset.nodeId;
                if (this._expanded.has(nodeId)) {
                    this._expanded.delete(nodeId);
                } else {
                    this._expanded.add(nodeId);
                }
                this.render(container);
            });
        });
    }
}

export { MemoryTreePanel };
