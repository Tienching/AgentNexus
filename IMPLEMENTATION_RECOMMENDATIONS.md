# Agent-Nexus 任务看板改进实施建议

基于 Multica 任务视图分析，本文档提出对 Agent-Nexus 任务看板的改进方案。

---

## 第一阶段: UI/UX 改进 (立即可实施)

### 1.1 增强筛选系统

**当前状态** (`kanban.js`)
```javascript
// 仅支持项目过滤 + 搜索
<select class="form-input form-select" id="taskProjectFilter">
  <option value="">All Projects</option>
</select>
<input type="text" class="form-input" placeholder="Search tasks...">
```

**改进方案**
```html
<div class="task-filters">
  <!-- 范围切换 -->
  <button-group id="scopeButtons" class="scope-tabs">
    <button data-scope="all" class="btn-outline">All</button>
    <button data-scope="members" class="btn-outline">Members</button>
    <button data-scope="agents" class="btn-outline">Agents</button>
  </button-group>
  
  <!-- 高级筛选 -->
  <dropdown-menu id="filterMenu" class="filter-dropdown">
    <!-- Status 多选 + 计数 -->
    <dropdown-item>
      <checkbox> Inbox <span class="count">5</span></checkbox>
    </dropdown-item>
    
    <!-- Priority 多选 -->
    <dropdown-item>
      <checkbox> High <span class="count">3</span></checkbox>
    </dropdown-item>
    
    <!-- Assignee 搜索 + 分组 -->
    <search-input placeholder="Search assignee...">
    <div class="members-group">
      <label><checkbox> John <span class="count">2</span></label>
    </div>
    
    <!-- Reset 按钮 -->
    <button class="btn-secondary">Reset all filters</button>
  </dropdown-menu>
  
  <!-- 排序与显示 -->
  <dropdown-menu id="displayMenu">
    <div class="sort-options">
      <button>Position (Manual)</button>
      <button>Priority</button>
      <button>Due Date</button>
      <button>Created Date</button>
    </div>
    <div class="display-options">
      <label><input type="checkbox"> Show Priority</label>
      <label><input type="checkbox"> Show Assignee</label>
      <label><input type="checkbox"> Show Due Date</label>
    </div>
  </dropdown-menu>
</div>
```

**实施步骤**
1. 在 `kanban.js` 中增加 `FilterManager` 类
2. 修改 `renderFullPage()` 增加新 UI 元素
3. 添加筛选状态存储 (localStorage)
4. 实现筛选逻辑 (前端过滤 + 算法优化)

**文件位置**
- `/src/server/static/nexus/js/components/filters.js` (新建)
- `/src/server/static/nexus/js/app.js` (修改 TaskView)

---

### 1.2 增强排序选项

**当前状态**
- 手动拖拽排序
- 基于 position 字段的简单排序

**改进方案**
```javascript
const SORT_OPTIONS = [
  { id: 'position', label: 'Manual', icon: 'sort' },
  { id: 'priority', label: 'Priority', icon: 'signal-high' },
  { id: 'due_date', label: 'Due Date', icon: 'calendar' },
  { id: 'created_at', label: 'Created', icon: 'clock' },
  { id: 'title', label: 'Title (A-Z)', icon: 'type' },
];

const SORT_DIRECTION = ['asc', 'desc'];

// 在 TaskView 中添加
this.sortBy = 'position';
this.sortDirection = 'asc';
this.setSortOption(sortBy, sortDirection);
this.applySorting();
```

**自动模式切换**
```javascript
// 当用户拖拽时，自动从其他排序模式切换到 position 模式
handleDragEnd(taskId, newStatus, oldStatus) {
  if (this.sortBy !== 'position') {
    this.setSortOption('position', 'asc');
  }
  this.updateTask(taskId, { status: newStatus });
}
```

---

### 1.3 列表视图补充

**当前状态**
- 仅有看板视图

**改进方案**
```javascript
// 新增视图切换按钮
<div class="view-toggle">
  <button class="btn-board active" data-view="board">
    <icon>columns</icon> Board
  </button>
  <button class="btn-list" data-view="list">
    <icon>list</icon> List
  </button>
</div>

// 新建 ListView 类
class ListView {
  constructor(container, tasks, options = {}) {
    this.container = container;
    this.tasks = tasks;
    this.statusColumns = options.statusColumns || [];
  }
  
  render() {
    // 按 status 分组显示 Accordion 布局
    // 每组可折叠，显示任务列表
  }
}
```

**布局设计**
```
┌─────────────────────┐
│ ☑ Inbox (5 tasks)   │  ← Accordion Header (支持群选)
├─────────────────────┤
│ ☐ [TSK-001] Bug fix │  ← ListRow
│ ☐ [TSK-002] Feature│
└─────────────────────┘
```

---

## 第二阶段: 架构优化 (1-2 周)

### 2.1 状态管理重构

**当前状态**
```javascript
class TaskView {
  this.tasks = {};                // 任务数据
  this.selectedTask = {};         // 单选
  this.selectedTaskIds = {};      // 多选 (per pane)
  this.selectionMode = {};        // boolean
  // ... 分散的状态
}
```

**改进方案: 引入 Zustand (或 TinyStore)**
```javascript
// stores/taskViewStore.js
export const useTaskViewStore = create((set) => ({
  // 视图模式
  viewMode: 'board',           // 'board' | 'list'
  setViewMode: (mode) => set({ viewMode: mode }),
  
  // 筛选条件
  statusFilter: [],
  priorityFilter: [],
  assigneeFilter: [],
  setStatusFilter: (filters) => set({ statusFilter: filters }),
  
  // 排序
  sortBy: 'position',
  sortDirection: 'asc',
  setSortBy: (field, direction) => set({ sortBy: field, sortDirection: direction }),
  
  // 显示选项
  showPriority: true,
  showAssignee: true,
  showDueDate: true,
  toggleProperty: (key) => set((state) => ({ [key]: !state[key] })),
  
  // 选择
  selectedIds: new Set(),
  select: (ids) => set((state) => ({ selectedIds: new Set(ids) })),
  deselect: (ids) => set((state) => {
    const next = new Set(state.selectedIds);
    ids.forEach(id => next.delete(id));
    return { selectedIds: next };
  }),
}));
```

**迁移步骤**
1. 在 `packages/stores/` 创建 `taskViewStore.js`
2. 修改 `TaskView` 使用新 store
3. 保持向后兼容 (逐步迁移)

---

### 2.2 拖拽库升级评估

**当前方案: HTML5 DnD**
- 优点: 轻量级，无外部依赖
- 缺点: 碰撞检测逻辑复杂，位置计算易出错，跨列移动有限制

**候选方案对比**

| 库 | 大小 | 类型安全 | 碰撞检测 | 学习曲线 | 推荐指数 |
|----|------|---------|---------|---------|---------|
| @dnd-kit | 35KB | ✓ | 高 | 中 | ⭐⭐⭐⭐⭐ |
| react-beautiful-dnd | 60KB | ✗ | 中 | 中 | ⭐⭐⭐⭐ |
| react-grid-layout | 40KB | ✗ | 中 | 高 | ⭐⭐⭐ |
| 保持 HTML5 DnD | 0KB | ✗ | 低 | 低 | ⭐⭐⭐ |

**建议**
- 短期 (3 个月): 保持 HTML5 DnD，优化位置计算算法
- 中期 (6 个月): 评估 @dnd-kit，创建适配层
- 长期: 如需全功能，迁移到 @dnd-kit

**位置计算优化** (立即可做)
```javascript
// 当前: 整数位置，易冲突
// 改进: 浮点数插值
function computePosition(ids, activeId, taskMap) {
  const idx = ids.indexOf(activeId);
  if (idx === 0) return getPos(ids[1]) - 1;
  if (idx === ids.length - 1) return getPos(ids[idx - 1]) + 1;
  return (getPos(ids[idx - 1]) + getPos(ids[idx + 1])) / 2;  // 平均值
}
```

---

### 2.3 卡片内联编辑系统

**当前状态**
- 点击卡片打开详情弹窗编辑

**改进方案: Picker 模式**
```javascript
class CardPickers {
  constructor(card, issue) {
    this.card = card;
    this.issue = issue;
  }
  
  renderAssigneePicker() {
    // 在卡片内内联编辑 assignee
    // 防止事件冒泡到拖拽处理
  }
  
  renderPriorityPicker() {
    // 内联选择优先级
  }
  
  renderDueDatePicker() {
    // 内联日期选择器
  }
}

// HTML 结构
<div class="task-card" draggable="true">
  <div class="card-header">
    <span class="identifier">[TSK-001]</span>
    <span class="title">Fix login bug</span>
  </div>
  
  <div class="card-footer">
    <!-- Assignee Picker (阻止冒泡) -->
    <div class="picker-wrapper">
      <button class="assignee-picker" onclick="showAssigneePicker(event)">
        <avatar>John</avatar>
      </button>
    </div>
    
    <!-- Priority (内联) -->
    <span class="priority" onclick="showPriorityPicker(event)">High</span>
    
    <!-- Due Date -->
    <span class="due-date" onclick="showDatePicker(event)">Mar 15</span>
  </div>
</div>
```

---

## 第三阶段: 性能优化 (2-4 周)

### 3.1 无限滚动 (Done 列)

**实现方案**
```javascript
class InfiniteScrollManager {
  constructor(column, options = {}) {
    this.column = column;
    this.pageSize = options.pageSize || 50;
    this.currentPage = 1;
    this.setupSentinel();
  }
  
  setupSentinel() {
    // Intersection Observer 检测底部可见性
    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && !this.loading) {
        this.loadMore();
      }
    });
    observer.observe(this.sentinel);
  }
  
  async loadMore() {
    this.loading = true;
    const tasks = await fetchDoneTasks(this.currentPage++, this.pageSize);
    this.column.appendChild(this.renderTasks(tasks));
    this.loading = false;
  }
}
```

---

### 3.2 性能监测指标

```javascript
// 添加性能监测
class PerfMonitor {
  // 拖拽帧率 (目标: 60fps)
  // 筛选响应时间 (目标: <100ms)
  // 排序计算时间 (目标: <50ms)
  // 内存占用 (目标: <50MB for 1000 tasks)
}
```

---

## 第四阶段: 代码组织优化 (持续)

### 4.1 文件结构重组

**当前**
```
src/server/static/nexus/js/
├── app.js                      # 1800+ 行 monolith
├── components/
│   └── kanban.js
```

**改进后**
```
src/server/static/nexus/js/
├── app.js                      # 仅路由和初始化
├── stores/
│   ├── taskViewStore.js       # 视图状态 (Zustand/TinyStore)
│   └── selectionStore.js      # 多选状态
├── components/
│   ├── TaskView.js            # 主容器
│   ├── BoardView.js           # 看板视图
│   ├── ListView.js            # 列表视图
│   ├── IssuesHeader.js        # 工具栏
│   ├── TaskCard.js            # 卡片
│   ├── TaskPickers.js         # 内联编辑器
│   └── kanban.js              # 拖拽底层
├── utils/
│   ├── filter.js              # 筛选逻辑
│   ├── sort.js                # 排序逻辑
│   └── position.js            # 位置计算
└── styles/
    ├── kanban.css
    ├── list.css
    └── filters.css
```

---

## 第五阶段: 测试覆盖

### 5.1 单元测试

```javascript
// tests/unit/sort.test.js
describe('Sorting', () => {
  it('sorts by priority correctly', () => {
    const tasks = [
      { id: 1, priority: 'low' },
      { id: 2, priority: 'high' },
      { id: 3, priority: 'medium' },
    ];
    const sorted = sortTasks(tasks, 'priority', 'desc');
    expect(sorted[0].priority).toBe('high');
  });
});

// tests/unit/position.test.js
describe('Position calculation', () => {
  it('computes float position correctly', () => {
    const ids = ['1', '2', '3'];
    const taskMap = new Map([
      ['1', { position: 10 }],
      ['2', { position: 20 }],
      ['3', { position: 30 }],
    ]);
    const pos = computePosition(ids, '2', taskMap);
    expect(pos).toBe(20);  // 中间值应保留原位置
  });
});
```

### 5.2 集成测试

```javascript
// tests/integration/kanban.test.js
describe('Kanban', () => {
  it('filters and sorts tasks correctly', async () => {
    const board = new KanbanBoard(container, {
      filters: { status: ['in_progress'] },
      sortBy: 'priority',
    });
    await board.render();
    
    const cards = board.queryAll('.task-card');
    expect(cards).toHaveLength(expectedCount);
  });
  
  it('handles drag and drop across columns', async () => {
    // 模拟拖拽
    // 验证任务状态变更
    // 验证 API 调用
  });
});
```

---

## 实施优先级与时间表

| 优先级 | 功能 | 工时 | 起始周期 |
|--------|------|------|---------|
| P0 | 位置计算优化 | 2天 | W1 |
| P0 | 高级筛选 UI | 3天 | W1 |
| P1 | 排序选项 | 2天 | W1 |
| P1 | 列表视图 | 5天 | W2 |
| P2 | 状态管理重构 | 4天 | W2-W3 |
| P2 | 卡片内联编辑 | 3天 | W3 |
| P3 | @dnd-kit 评估 | 2天 | W4 |
| P3 | 性能优化 | 5天 | W4-W5 |

**总计: 4-5 周**

---

## 关键设计决策

### 决策 1: 状态管理库选择
- **选项 A**: Zustand (推荐)
  - 轻量 (5KB)
  - 原生 JS 支持
  - TypeScript 友好
  - localStorage persist
  
- **选项 B**: TinyStore (备选)
  - 极轻量 (1KB)
  - 无依赖
  
**决策**: 采用 Zustand (长期更易维护)

### 决策 2: 拖拽库升级时机
- **现在**: 优化算法，保持 HTML5 DnD
- **6 个月后**: 评估 @dnd-kit 可行性
- **条件**: 用户反馈或功能需求推动

**理由**: 降低风险，保持稳定性

### 决策 3: 内联编辑 vs 弹窗编辑
- **采用**: 混合方案
  - Picker: 快速编辑 (status/priority/assignee)
  - 详情页: 完整编辑 (description/等)

**理由**: 兼顾易用性和功能完整性

---

## 风险管理

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 拖拽性能下降 | 中 | 高 | 完整测试 + 监测指标 |
| 状态管理迁移破坏 | 低 | 高 | 逐步迁移 + 充分测试 |
| 用户交互差异 | 中 | 中 | 用户测试 + 反馈迭代 |

---

## 成功指标

1. **功能覆盖**
   - 支持 4 维筛选
   - 支持 5 种排序方式
   - 支持 board/list 两种视图

2. **性能指标**
   - 拖拽帧率 ≥ 55fps
   - 筛选响应 ≤ 100ms
   - 1000+ 任务加载 ≤ 2s

3. **用户体验**
   - NPS ≥ 8/10
   - 用户培训时间 ≤ 5 min
   - 支持票减少 30%

---

## 参考文件

- `/home/ubuntu/Projects/agent-nexus_feature-dev/MULTICA_TASKVIEW_ANALYSIS.md`
- Multica 源码: `~/Projects/multica/packages/views/issues/`
