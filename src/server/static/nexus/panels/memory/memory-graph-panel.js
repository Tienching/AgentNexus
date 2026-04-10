/**
 * MemoryGraphPanel - Graph/relationship view of agent memory connections.
 */

class MemoryGraphPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._nodes = [];
        this._edges = [];
        this._canvas = null;
    }

    async refresh() {
        try {
            const data = await this.api.getAgents();
            const agents = data.agents || [];
            this._nodes = agents.map(a => ({
                id: a.id,
                label: a.display_name || a.id,
                type: a.agent_type,
                available: a.available,
            }));
            // Generate some edges between agents sharing same username or type
            this._edges = [];
            for (let i = 0; i < agents.length; i++) {
                for (let j = i + 1; j < agents.length; j++) {
                    if (agents[i].username === agents[j].username) {
                        this._edges.push({ from: agents[i].id, to: agents[j].id, type: 'same_user' });
                    }
                }
            }
            this.render(this.container);
        } catch (e) {
            this._nodes = [];
            this._edges = [];
            this.render(this.container);
        }
    }

    render(container) {
        this.container = container;

        container.innerHTML = `
            ${this._headerHtml()}
            <div class="panel-body">
                <div class="panel-stats">
                    <span class="stat-item"><span class="stat-value">${this._nodes.length}</span> Nodes</span>
                    <span class="stat-item"><span class="stat-value">${this._edges.length}</span> Edges</span>
                </div>
                <div class="panel-graph-container">
                    <canvas class="panel-canvas" width="600" height="400"></canvas>
                </div>
            </div>
        `;

        this._bindRefreshBtn();
        this._drawGraph();
    }

    _drawGraph() {
        const canvas = this.container?.querySelector('.panel-canvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;

        ctx.clearRect(0, 0, w, h);

        if (this._nodes.length === 0) {
            ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--text-secondary') || '#888';
            ctx.font = '14px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('No graph data', w / 2, h / 2);
            return;
        }

        // Simple circular layout
        const cx = w / 2;
        const cy = h / 2;
        const r = Math.min(w, h) * 0.35;
        const positions = {};

        this._nodes.forEach((node, i) => {
            const angle = (2 * Math.PI * i) / this._nodes.length - Math.PI / 2;
            positions[node.id] = {
                x: cx + r * Math.cos(angle),
                y: cy + r * Math.sin(angle),
            };
        });

        // Draw edges
        ctx.strokeStyle = 'rgba(100, 160, 255, 0.3)';
        ctx.lineWidth = 1;
        for (const edge of this._edges) {
            const from = positions[edge.from];
            const to = positions[edge.to];
            if (from && to) {
                ctx.beginPath();
                ctx.moveTo(from.x, from.y);
                ctx.lineTo(to.x, to.y);
                ctx.stroke();
            }
        }

        // Draw nodes
        const style = getComputedStyle(document.documentElement);
        const onlineColor = style.getPropertyValue('--success-500') || '#22c55e';
        const offlineColor = style.getPropertyValue('--text-muted') || '#888';

        for (const node of this._nodes) {
            const pos = positions[node.id];
            if (!pos) continue;

            ctx.beginPath();
            ctx.arc(pos.x, pos.y, 8, 0, 2 * Math.PI);
            ctx.fillStyle = node.available ? onlineColor : offlineColor;
            ctx.fill();
            ctx.strokeStyle = 'rgba(255,255,255,0.2)';
            ctx.lineWidth = 1;
            ctx.stroke();

            // Label
            ctx.fillStyle = style.getPropertyValue('--text-primary') || '#fff';
            ctx.font = '10px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(node.label.split('/').pop(), pos.x, pos.y + 20);
        }
    }
}

export { MemoryGraphPanel };
