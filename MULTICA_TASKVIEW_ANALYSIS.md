# Multica 任务视图深度分析报告

## 项目概览

**Multica** 是一个基于 Next.js + TypeScript + React 的现代化任务管理系统，采用 monorepo 架构（pnpm workspace）。

### 核心技术栈

- **前端框架**: React 18 + Next.js (App Router)
- **状态管理**: Zustand (轻量化方案)
- **拖拽库**: @dnd-kit (headless drag-and-drop)
- **UI 组件**: 自建 UI 库 (@multica/ui) + shadcn 组件
- **TypeScript**: 全类型安全
- **包结构**:
  - `apps/web`: 主应用 (Next.js)
  - `packages/core`: 业务逻辑/store/queries
  - `packages/views`: UI 组件库
  - `packages/ui`: 基础 UI 组件

---

## 1. 任务视图架构分析

### 1.1 核心文件结构

```
packages/views/issues/
├── components/
│   ├── issues-page.tsx          # 主容器 (board/list 切换、筛选、排序)
│   ├── board-view.tsx           # 看板视图 (Kanban 拖拽逻辑)
│   ├── board-column.tsx         # 看板列 (status 列)
│   ├── board-card.tsx           # 看板卡片 (可拖拽、可编辑)
│   ├── list-view.tsx            # 列表视图 (Accordion 分组)
│   ├── list-row.tsx             # 列表行
│   ├── issues-header.tsx        # 工具栏 (筛选、排序、视图切换)
│   ├── issue-detail.tsx         # 详情弹窗
│   ├── batch-action-toolbar.tsx # 批量操作
│   └── pickers/                 # 字段编辑器 (status/priority/assignee/due-date)
├── utils/
│   ├── filter.ts                # 筛选逻辑
│   └── sort.ts                  # 排序逻辑
```

### 1.2 数据流架构

```
┌─────────────────────────────────────────────────────┐
│ IssuesPage (主容器)                                 │
│ - 数据获取: useQuery(issueListOptions)              │
│ - 状态管理: useIssueViewStore (视图状态)            │
└─────────────────────────────────────────────────────┘
         │
         ├──→ IssuesHeader (筛选/排序/视图切换)
         │
         ├──→ BoardView / ListView
         │    ├─ buildColumns() (基于筛选/排序重组数据)
         │    ├─ DragContext (@dnd-kit)
         │    └─ BoardColumn[] / ListRow[]
         │
         └──→ BatchActionToolbar (批量操作 - 仅列表视图)

状态管理层:
├── useIssueViewStore        # 视图状态 (view-store.ts)
│   ├─ viewMode: "board" | "list"
│   ├─ statusFilters: IssueStatus[]
│   ├─ priorityFilters: IssuePriority[]
│   ├─ assigneeFilters: ActorFilterValue[]
│   ├─ sortBy: SortField
│   └─ cardProperties: { priority, description, assignee, dueDate }
├── useIssueSelectionStore   # 多选状态 (selection-store.ts)
│   └─ selectedIds: Set<taskId>
└── useIssuesScopeStore      # 作用域 (issues-scope-store.ts)
    └─ scope: "all" | "members" | "agents"
```

---

## 2. 任务视图详细实现

### 2.1 看板视图 (BoardView)

#### 渲染流程

```typescript
// issues-page.tsx (L159)
{viewMode === "board" ? (
  <BoardView
    issues={issues}                 // 已筛选的任务
    allIssues={scopedIssues}       // 原始任务 (用于隐藏列统计)
    visibleStatuses={visibleStatuses}
    hiddenStatuses={hiddenStatuses}
    onMoveIssue={handleMoveIssue}
    childProgressMap={childProgressMap}
  />
) : ...}
```

#### 拖拽核心逻辑 (BoardView.tsx)

**1. 列结构初始化**
```typescript
// L54-71: buildColumns()
// 按 status 分组 + 按 sortBy/sortDirection 排序
const columns = Record<IssueStatus, string[]>  // status -> [issueId, ...]
```

**2. 冲突检测策略**
```typescript
// L40-52: kanbanCollision()
const kanbanCollision: CollisionDetection = (args) => {
  const pointer = pointerWithin(args);
  if (pointer.length > 0) {
    // 优先卡片碰撞 > 列碰撞 (拖拽向下时防止误触列)
    const cards = pointer.filter((c) => !COLUMN_IDS.has(c.id as string));
    if (cards.length > 0) return cards;
  }
  return closestCenter(args);  // 备选: 最近距离
};
```

**3. 拖拽生命周期**

a) **handleDragStart (L172-179)**
   - 记录被拖拽的卡片和初始状态
   - 从 issueMapRef 获取卡片数据 (frozen during drag)

b) **handleDragOver (L181-204)**
   - 检测列碰撞
   - 实时更新本地列结构 (columns state)
   - 防抖: recentlyMovedRef (跨列移动后锁定1帧)

c) **handleDragEnd (L206-266)**
   - 验证: 终点列是否有效
   - 计算新位置 (computePosition L73-82)
   - 调用 onMoveIssue → updateIssueMutation

**4. 位置计算算法 (computePosition)**
```typescript
// L73-82
// 基于邻接卡片的 position 字段计算浮点位置
function computePosition(ids: string[], activeId: string, issueMap: Map<string, Issue>): number {
  const idx = ids.indexOf(activeId);
  
  if (idx === 0) 
    return getPos(ids[1]!) - 1;           // 前插: next - 1
  if (idx === ids.length - 1) 
    return getPos(ids[idx - 1]!) + 1;     // 后插: prev + 1
  
  return (getPos(ids[idx - 1]!) + getPos(ids[idx + 1]!)) / 2;  // 中间: 平均值
}
```

#### 状态冻结策略

```typescript
// L152-164: issueMap 在拖拽期间冻结
const issueMapRef = useRef(issueMap);
if (!isDraggingRef.current) {
  issueMapRef.current = issueMap;  // 拖拽结束后更新
}
// 好处: 即使 TQ refetch 发生，拖拽 UI 也保持稳定
```

#### 隐藏列面板 (HiddenColumnsPanel)

```typescript
// L312-372
// 显示被过滤隐藏的列及其任务数
// 可点击菜单恢复列显示
```

### 2.2 列表视图 (ListView)

#### 布局: Accordion (分组可折叠)

```typescript
// list-view.tsx (L62-156)
<Accordion.Root multiple>
  {visibleStatuses.map(status => (
    <Accordion.Item value={status}>
      <Accordion.Header>
        // 复选框 (群选)
        // 状态徽章 + 计数
        // +新建按钮
      </Accordion.Header>
      <Accordion.Panel>
        {statusIssues.map(issue => (
          <ListRow key={issue.id} issue={issue} />
        ))}
      </Accordion.Panel>
    </Accordion.Item>
  ))}
</Accordion.Root>
```

#### 选择模式

```typescript
// list-view.tsx (L88-101): 群选逻辑
- 全选: 选中该 status 的所有任务
- 半选: 部分选中时 checkbox 显示不确定态
- 修改任何值 (viewMode/scope/filter) 时清空选择 (L43-44)
```

### 2.3 工具栏/筛选 (IssuesHeader)

#### 作用域切换 (Scope Tabs)

```typescript
const SCOPES = [
  { value: "all", label: "All", description: "All issues in this workspace" },
  { value: "members", label: "Members", description: "Issues assigned to team members" },
  { value: "agents", label: "Agents", description: "Issues assigned to AI agents" },
];
// scope 影响 scopedIssues 的预过滤 (L47-53)
```

#### 筛选系统 (Filter Dropdown)

| 筛选维度 | 类型 | 实现 |
|---------|------|------|
| **Status** | 多选 | CheckboxItem (显示计数) |
| **Priority** | 多选 | CheckboxItem |
| **Assignee** | 多选 + 搜索 | ActorSubContent (members/agents 分组) |
| **Creator** | 多选 + 搜索 | ActorSubContent |
| **No Assignee** | 单独开关 | CheckboxItem |

**搜索优化 (L158-168)**
```typescript
const [search, setSearch] = useState("");
const filteredMembers = members.filter(m => m.name.toLowerCase().includes(query));
const filteredAgents = agents.filter(a => !a.archived_at && a.name.toLowerCase().includes(query));
// 实时搜索 members 和 agents (不通过 API)
```

#### 排序与显示选项 (Display Settings Popover)

**排序字段** (L25-31)
```
- position (手动排序)
- priority
- due_date
- created_at
- title
```

**卡片属性显示** (L33-38)
```
toggles: priority, description, assignee, dueDate
```

#### 视图切换

```typescript
// board <-> list 的快速切换 + 自动清除选择 (L43-44)
```

### 2.4 卡片组件 (BoardCardContent & DraggableBoardCard)

#### 卡片布局

```
┌─────────────────────┐
│ issue.identifier    │ (灰色小字)
├─────────────────────┤
│ Title               │ (最多2行)
├─────────────────────┤
│ ⊙ 2/5 (sub-issue)   │ (进度环 + 计数)
├─────────────────────┤
│ Description snippet │ (可选, 1行截断)
├─────────────────────┤
│ 👤 priority 📅      │ (可选 footer: assignee/priority/due-date)
└─────────────────────┘
```

#### 字段编辑 (内联编辑)

```typescript
// board-card.tsx (L99-176)
// 通过 PickerWrapper 阻止事件冒泡到拖拽处理
const PickerWrapper = ({ children }) => (
  <div onClick={stop} onMouseDown={stop} onPointerDown={stop}>
    {children}
  </div>
);

// 支持编辑:
- assignee → AssigneePicker
- priority → PriorityPicker
- due_date → DueDatePicker
```

#### 可拖拽包装 (DraggableBoardCard)

```typescript
// L188-223: useSortable() hook (from @dnd-kit/sortable)
const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
  id: issue.id,
  data: { status: issue.status },
  animateLayoutChanges: customAnimation,  // 拖拽时禁用动画
});

// 拖拽时 opacity: 30%
```

### 2.5 子任务进度 (ChildProgress)

```typescript
// issues-page.tsx (L60-75)
const childProgressMap = useMemo(() => {
  const map = new Map<string, { done: number; total: number }>();
  // 从 allIssues (未筛选) 计算每个 parent_issue_id 的进度
  // 只有 status === "done" 或 "cancelled" 的才算完成
  return map;
}, [allIssues]);

// 显示在卡片上:
{childProgress && (
  <ProgressRing done={childProgress.done} total={childProgress.total} size={14} />
)}
```

---

## 3. 状态管理深度解析

### 3.1 IssueViewStore (view-store.ts)

#### 状态结构

```typescript
interface IssueViewState {
  // 视图模式
  viewMode: "board" | "list"
  
  // 筛选条件
  statusFilters: IssueStatus[]           // 空数组 = 显示全部
  priorityFilters: IssuePriority[]
  assigneeFilters: ActorFilterValue[]    // [{ type: "member" | "agent", id }]
  includeNoAssignee: boolean
  creatorFilters: ActorFilterValue[]
  
  // 排序
  sortBy: "position" | "priority" | "due_date" | "created_at" | "title"
  sortDirection: "asc" | "desc"
  
  // 显示选项
  cardProperties: { priority, description, assignee, dueDate }  // boolean flags
  listCollapsedStatuses: IssueStatus[]   // 列表模式下已折叠的 status
  
  // 行为
  setViewMode(mode: ViewMode): void
  toggleStatusFilter(status: IssueStatus): void
  // ... 其他 toggle 方法
}
```

#### 持久化

```typescript
// 使用 zustand persist middleware
// localStorage 自动保存视图偏好设置
```

#### 状态创建工厂

```typescript
export const viewStoreSlice = (set): IssueViewState => ({
  viewMode: "board",
  statusFilters: [],
  // ... 初始值
  
  setViewMode: (mode) => set({ viewMode: mode }),
  toggleStatusFilter: (status) => set((state) => ({
    statusFilters: state.statusFilters.includes(status)
      ? state.statusFilters.filter(s => s !== status)
      : [...state.statusFilters, status]
  })),
});
```

### 3.2 SelectionStore (selection-store.ts)

```typescript
// 多选状态 (列表视图中)
interface IssueSelectionState {
  selectedIds: Set<string>
  select(ids: string[]): void
  deselect(ids: string[]): void
  clear(): void
}
```

### 3.3 IssuesScopeStore (issues-scope-store.ts)

```typescript
interface IssuesScopeState {
  scope: "all" | "members" | "agents"
  setScope(scope: IssuesScope): void
}
```

---

## 4. 数据流与查询

### 4.1 数据获取

```typescript
// issues-page.tsx (L27)
const { data: allIssues = [], isLoading: loading } = useQuery(issueListOptions(wsId));
// TanStack Query 自动缓存 + 后台 refetch
```

### 4.2 筛选流水线

```
allIssues (原始数据)
  ↓
scopedIssues (按 scope 预过滤: members/agents)
  ↓
issues (按全部筛选条件过滤)
  ↓ buildColumns() / sortIssues()
columns (按 status 分组并按 sortBy 排序)
```

### 4.3 变更处理

```typescript
// issues-page.tsx (L88-108)
const handleMoveIssue = useCallback(
  (issueId: string, newStatus: IssueStatus, newPosition?: number) => {
    // 自动切换到手动排序模式
    if (viewState.sortBy !== "position") {
      viewState.setSortBy("position");
      viewState.setSortDirection("asc");
    }
    
    updateIssueMutation.mutate(
      { id: issueId, status: newStatus, position: newPosition },
      { onError: () => toast.error("Failed to move issue") }
    );
  },
  [updateIssueMutation]
);
```

---

## 5. 高级特性

### 5.1 无限滚动 (Done 列)

```typescript
// board-view.tsx (L120) & list-view.tsx (L41)
const { loadMore, hasMore, isLoading: loadingMore, doneTotal } = useLoadMoreDoneIssues();

// 使用 InfiniteScrollSentinel 组件检测可见性
// 当用户滚动到底部时自动加载更多
```

### 5.2 批量操作 (列表视图)

```typescript
// batch-action-toolbar.tsx (仅在列表模式显示)
// 在 selectedIds 有值时显示
// 支持: 删除选中、改状态、改优先级等
```

### 5.3 多工作区支持

```typescript
// 通过 useWorkspaceId() 获取当前工作区
// 数据查询和变更都通过 wsId 隔离
```

---

## 6. UI 库与交互模式

### 6.1 使用的 UI 库

| 库 | 用途 |
|----|------|
| @base-ui/react/accordion | 可折叠列表 (列表视图) |
| @dnd-kit | 看板拖拽 |
| sonner | Toast 通知 |
| lucide-react | 图标 |
| @multica/ui | 自定义组件 (Button, Dropdown, Popover, Switch, Tooltip) |

### 6.2 交互模式

| 操作 | 反馈 |
|------|------|
| 拖拽卡片 | 实时列重排 + DragOverlay |
| 点击字段 | 弹出编辑器 (Picker) |
| 选中卡片 | Checkbox + 蓝色高亮 |
| 筛选/排序 | 实时重组 |
| 变更失败 | Toast 错误通知 |

---

## 7. 性能优化

### 7.1 Memoization

```typescript
// buildColumns: 仅在 issues/visibleStatuses/sortBy/sortDirection 变化时重新计算
// issueMap: 拖拽期间冻结
// resolvedIssues: 按 issueIds 和 issueMap memo
// issuesByStatus: 按 issues/visibleStatuses/sortBy/sortDirection memo
```

### 7.2 事件冒泡控制

```typescript
// PickerWrapper: 阻止编辑器事件触发拖拽逻辑
```

### 7.3 响应式设计

```typescript
// 看板: 水平滚动 (flex-1 min-h-0 gap-4 overflow-x-auto)
// 列表: 垂直滚动 (flex-1 min-h-0 overflow-y-auto)
// 移动端: 单列响应 (包含隐藏列面板)
```

---

## 8. 配置系统

### 8.1 状态配置 (status.ts)

```typescript
// 7 个主状态 (board 显示 6 个, 隐藏 cancelled)
export const BOARD_STATUSES = [
  "backlog", "todo", "in_progress", "in_review", "done", "blocked"
];

// 每个状态的视觉配置
STATUS_CONFIG[status] = {
  label: string,
  iconColor: string,        // Tailwind class
  badgeBg: string,
  badgeText: string,
  columnBg: string,         // 列背景色
  // ...
}
```

### 8.2 优先级配置 (priority.ts)

```typescript
PRIORITY_CONFIG[priority] = {
  label: string,
  badgeBg: string,
  badgeText: string,
  // ...
}
```

---

## 9. 与 Agent-Nexus 的对比

| 维度 | Multica | Agent-Nexus |
|------|---------|------------|
| **框架** | React 18 + Next.js | Vanilla JS (主要) |
| **拖拽库** | @dnd-kit (headless) | HTML5 DnD (轻量级) |
| **状态管理** | Zustand | 对象属性 + 全局状态 |
| **视图模式** | Board + List | 仅 Kanban |
| **筛选** | 4 维多选 + 搜索 | 项目过滤 + 搜索 |
| **排序** | 5 个选项 | 位置/日期/优先级 |
| **拖拽粒度** | 位置精确计算 | 跨列轻检测 |
| **无限滚动** | Done 列分页 | 计划中 |
| **编辑** | 内联 Picker | 详情页 |
| **选择** | 多选 (列表模式) | 支持多选 |
| **架构** | monorepo (TS) | 单体 (JS) |

---

## 10. 可借鉴之处 (对 Agent-Nexus)

### 10.1 核心借鉴

1. **多视图支持**
   - 引入列表视图补充看板视图 (Accordion 分组)
   - 方便列表型任务浏览

2. **高级筛选**
   - 多维筛选 (Status/Priority/Assignee/Creator) + 搜索
   - 筛选计数显示
   - 重置按钮

3. **位置计算算法**
   - 使用浮点数插值而非整数
   - 支持无限拖拽而无冲突

4. **@dnd-kit 库**
   - 比 HTML5 DnD 功能丰富
   - 类型安全、collision detection 更灵活
   - 支持 DragOverlay 实时反馈

5. **状态设计**
   - Zustand 轻量且类型安全
   - Persist middleware 自动 localStorage
   - Context API 简化 prop drilling

6. **UI 组件库化**
   - Pickers 内联编辑 (Assignee/Priority/DueDate)
   - 减少弹窗打开/关闭开销

7. **Scope 概念**
   - 预过滤 (members/agents/all)
   - 降低视图负载

### 10.2 实施建议

1. **渐进式迁移**
   - 保持现有 7 列 kanban 结构
   - 添加列表视图作为新选项
   - 统一筛选/排序 UI

2. **Zustand 集成**
   - 逐步替换全局状态对象
   - 维持向后兼容

3. **@dnd-kit 迁移**
   - 逐步引入 @dnd-kit/core
   - 测试碰撞检测逻辑
   - 验证位置计算精度

4. **UI 组件系统**
   - 继续用 Picker 模式 (内联编辑)
   - 标准化 Filter/Sort/View 切换 UI

5. **性能监测**
   - 大数据集测试 (1000+ 任务)
   - 移动端响应性测试

---

## 11. 代码质量与架构评分

| 维度 | 评分 | 备注 |
|------|------|------|
| **类型安全** | 10/10 | 全 TypeScript + 严格模式 |
| **可维护性** | 9/10 | 清晰的组件分离，轻量 state |
| **性能** | 9/10 | 多层 memoization + 冻结策略 |
| **可扩展性** | 8/10 | 易加新筛选维度/排序选项 |
| **测试覆盖** | 6/10 | 有单元测试，集成测试偏少 |
| **文档** | 7/10 | 代码注释清晰，无生成文档 |

