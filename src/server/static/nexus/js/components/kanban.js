/**
 * Kanban drag-and-drop helper.
 *
 * Lightweight HTML5 DnD wrapper for Nexus task board.
 * Expects:
 * - board element containing .kanban-column[data-status]
 * - cards with .task-card[data-task-id][draggable="true"]
 */
class KanbanDragDrop {
    static mount(board, options = {}) {
        if (!board) return null;
        const instance = new KanbanDragDrop(board, options);
        instance.bind();
        return instance;
    }

    constructor(board, options = {}) {
        this.board = board;
        this.onMove = options.onMove || (async () => {});
        this.getTaskStatus = options.getTaskStatus || (() => null);
        this.dragState = null;
    }

    bind() {
        this.board.querySelectorAll('.task-card[draggable="true"]').forEach((card) => {
            if (card.dataset.kanbanBound === '1') return;
            card.dataset.kanbanBound = '1';
            card.addEventListener('dragstart', (event) => this.handleDragStart(event, card));
            card.addEventListener('dragend', () => this.handleDragEnd());
        });

        this.board.querySelectorAll('.kanban-column').forEach((column) => {
            const items = column.querySelector('.kanban-column-items');
            if (!items || items.dataset.kanbanBound === '1') return;
            items.dataset.kanbanBound = '1';
            items.addEventListener('dragover', (event) => this.handleDragOver(event, column));
            items.addEventListener('dragenter', (event) => this.handleDragEnter(event, column));
            items.addEventListener('dragleave', (event) => this.handleDragLeave(event, column));
            items.addEventListener('drop', (event) => this.handleDrop(event, column));
        });
    }

    handleDragStart(event, card) {
        const taskId = card.dataset.taskId;
        const fromStatus = this.getTaskStatus(taskId) || card.closest('.kanban-column')?.dataset.status || '';
        this.dragState = { taskId, fromStatus };
        card.classList.add('task-card-dragging');
        if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', JSON.stringify(this.dragState));
        }
    }

    handleDragEnd() {
        this.board.querySelectorAll('.task-card-dragging').forEach((el) => el.classList.remove('task-card-dragging'));
        this.board.querySelectorAll('.kanban-drop-target').forEach((el) => el.classList.remove('kanban-drop-target'));
        this.dragState = null;
    }

    handleDragOver(event, column) {
        if (!this.dragState) return;
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
        column.classList.add('kanban-drop-target');
    }

    handleDragEnter(event, column) {
        if (!this.dragState) return;
        event.preventDefault();
        column.classList.add('kanban-drop-target');
    }

    handleDragLeave(event, column) {
        const related = event.relatedTarget;
        if (related && column.contains(related)) return;
        column.classList.remove('kanban-drop-target');
    }

    async handleDrop(event, column) {
        event.preventDefault();
        const toStatus = column.dataset.status;
        const payload = this.dragState || this.readTransfer(event);
        column.classList.remove('kanban-drop-target');
        if (!payload || !payload.taskId || !toStatus) return;
        if (payload.fromStatus === toStatus) return;
        await this.onMove(payload.taskId, toStatus, payload.fromStatus);
    }

    readTransfer(event) {
        try {
            const raw = event.dataTransfer?.getData('text/plain');
            return raw ? JSON.parse(raw) : null;
        } catch {
            return null;
        }
    }
}

window.KanbanDragDrop = KanbanDragDrop;
