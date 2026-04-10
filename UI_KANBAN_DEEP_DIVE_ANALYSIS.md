# UI / Kanban 深度对比分析

## 执行摘要

本分析深入对比了 Mission Control (React + TypeScript) 和 Agent Nexus (原生 JS) 的任务看板实现，识别出 **23 个具体可移植的 UI 功能点**，可用于显著增强 Nexus 的用户体验。

---

## 1. 看板核心架构对比

### 1.1 工作流状态列

| 系统 | 状态列 | 设计哲学 |
|------|--------|----------|
| **Mission Control** | 7 列: inbox → assigned → awaiting_owner → in_progress → review → quality_review → done | 强调人机协作流程，专门设立 `awaiting_owner` 等待人工干预 |
| **Agent Nexus (当前)** | 6 列: todo → doing → done → failed → cancelled → archived | 以任务执行为中心，缺少人机协作状态 |

**建议**: 引入 Mission Control 的 7 列模型，特别是 `awaiting_owner` 和 `quality_review` 状态。

### 1.2 拖拽交互

**Mission Control 实现:**
```typescript
// 基于 HTML5 Drag and Drop API
onDragStart={(e) => handleDragStart(e, task)}
onDragEnter={(e) => handleDragEnter(e, column.key)}
onDrop={(e) => handleDrop(e, column.key)}

// 视觉反馈
const priorityColors: Record<string, string> = {
  low: 'border-l-green-500',
  medium: 'border-l-yellow-500',
  high: 'border-l-orange-500',
  critical: 'border-l-red-500',
}
```

**Nexus 当前缺失:** 原生 JS 版本目前 **没有实现拖放功能**，只能通过点击查看详情修改状态。

---

## 2. 任务卡片设计对比

### 2.1 Mission Control 任务卡片特性

```typescript
// 卡片视觉层次
interface TaskCardVisual {
  priorityBorder: 'border-l-4' + priorityColors[task.priority]  // 左侧优先级彩条
  dragHandle: 'group-hover:text-muted-foreground/40'          // 悬停显示拖拽手柄
  recurrenceBadge: 'bg-cyan-500/20 text-cyan-400'             // 周期性任务标识
  githubLinks: 'bg-[#24292e]/30 text-gray-300'                // GitHub Issue/PR 链接
  aegisApproval: 'bg-emerald-500/15 text-emerald-400'         // 质量审核通过标识
  agentAvatar: '<AgentAvatar name={getAgentName(task.assigned_to)} />'
  dueDateHighlight: task.due_date * 1000 < Date.now() ? 'text-red-400' : ''
}
```

### 2.2 可移植的卡片功能清单

| # | 功能 | Mission Control 参考 | 实现复杂度 |
|---|------|---------------------|-----------|
| 1 | **左侧优先级彩条** | `border-l-4 ${priorityColors[task.priority]}` | 低 |
| 2 | **拖拽手柄图标** | 6-dot grip icon (SVG) | 低 |
| 3 | **周期性任务标识** | `bg-cyan-500/20 text-cyan-400` badge | 低 |
| 4 | **GitHub Issue/PR 链接** | 带状态色的动态链接 (open/merged/closed) | 中 |
| 5 | **Aegis 质量审核标识** | `bg-emerald-500/15 text-emerald-400` | 低 |
| 6 | **Agent 头像组件** | `<AgentAvatar name={...} size="xs" />` | 中 |
| 7 | **逾期日期高亮** | `text-red-400 font-medium` + "!" 前缀 | 低 |
| 8 | **标签云 (最多3个+计数)** | `task.tags.slice(0, 3)` + `+{n}` | 低 |
| 9 | **任务创建时间格式化** | `formatTaskTimestamp()` 相对时间 | 低 |
| 10 | **所属项目票号** | `ticket_ref` badge | 低 |

---

## 3. 任务详情模态框对比

### 3.1 Mission Control Task Detail Modal

**功能标签页 (4 tabs):**
```typescript
const [activeTab, setActiveTab] = useState<'details' | 'comments' | 'quality' | 'session'>('details')
```

**详情页内容:**
- 任务基本信息 (标题、描述、Markdown 渲染)
- 项目信息
- 状态/优先级/负责人
- GitHub 关联 (Issue/Branch/PR)
- Agent Session 链接

**评论页特性:**
```typescript
// @提及自动完成
<MentionTextarea
  value={commentText}
  onChange={setCommentText}
  mentionTargets={mentionTargets}  // 从 agents + users 构建
/>

// 评论元数据显示
{meta && (
  <span>{meta.model} · {meta.tokens.toLocaleString()} tok · {(meta.durationMs/1000).toFixed(1)}s</span>
)}

// 嵌套回复支持
{comment.replies?.map(reply => renderComment(reply, depth + 1))}

// Broadcast (广播) 功能 - 一次性通知所有订阅者
```

**质量审核页:**
```typescript
// Aegis 质量审核历史
{reviews.map((review) => (
  <div key={review.id}>
    <span>{review.reviewer} — {review.status}</span>
    {review.notes && <div>{review.notes}</div>}
  </div>
))}

// 提交新审核表单
<form onSubmit={handleSubmitReview}>
  <input value={reviewer} />
  <select value={reviewStatus}>  // approved | rejected
  <input value={reviewNotes} />
</form>
```

**Session 页:**
```typescript
// 实时 Agent Session 流
<TaskSessionFeed
  sessionId={task.metadata.dispatch_session_id}
  agentName={task.assigned_to}
  isLive={task.status === 'in_progress'}
/>
```

### 3.2 Nexus 当前实现差距

| 功能 | Mission Control | Nexus 当前 |
|------|-----------------|------------|
| 标签页设计 | 4 tabs (details/comments/quality/session) | 单页展示 |
| @提及 | ✅ MentionTextarea 组件 | ❌ 缺失 |
| Markdown 渲染 | ✅ `<MarkdownRenderer />` | ❌ 纯文本 |
| 嵌套评论 | ✅ 支持多层级 | ❌ 无评论系统 |
| 质量审核 | ✅ Aegis 集成 | ❌ 缺失 |
| Session 直播 | ✅ 实时流展示 | ✅ 已有基础 |
| Broadcast | ✅ 批量通知 | ❌ 缺失 |

---

## 4. 创建/编辑任务模态框

### 4.1 Mission Control CreateTaskModal 特性

```typescript
// 基础字段
const formFields = [
  'title',           // 文本输入
  'description',     // MentionTextarea (支持 @提及)
  'priority',        // select: low/medium/high/critical
  'project_id',      // select: 项目列表
  'assigned_to',     // select: Agent 列表
  'target_session',  // select: Agent 活跃会话 (动态加载)
  'tags',            // 文本: "frontend, urgent, bug"
]

// 周期性任务支持
const [isRecurring, setIsRecurring] = useState(false)
const [scheduleInput, setScheduleInput] = useState('')
const [parsedSchedule, setParsedSchedule] = useState<{ cronExpr: string; humanReadable: string } | null>(null)

// NLP Cron 解析
const handleScheduleChange = async (value: string) => {
  const res = await fetch(`/api/schedule-parse?input=${encodeURIComponent(value)}`)
  // 返回: { cronExpr: "0 9 * * *", humanReadable: "每天早上9点" }
}
```

### 4.2 EditTaskModal 额外特性

- 状态修改下拉框 (可跨列移动任务)
- 目标会话选择 (Send task to existing agent session)

---

## 5. 底部扩展面板

Mission Control 在看板底部提供 3 个可折叠面板:

```typescript
// 1. Claude Code Tasks Section
<ClaudeCodeTasksSection />  // 集成本地 Claude Code 任务

// 2. CodeBuddy Sessions Section  
<CodeBuddySessionsSection />  // 显示活跃的 CodeBuddy 会话

// 3. Hermes Scheduled Tasks Section
<HermesCronSection />  // 定时任务管理
```

**设计模式:**
- 折叠/展开状态管理
- 懒加载数据 (expanded 时才 fetch)
- 数量徽章显示

---

## 6. 实时更新机制

### 6.1 Mission Control

```typescript
// Smart Polling Hook
function useSmartPoll(callback: () => void, intervalMs: number = 10000) {
  const [pageVisible, setPageVisible] = useState(true)
  const lastPollRef = useRef<number>(Date.now())

  useEffect(() => {
    const handleVisibilityChange = () => {
      setPageVisible(!document.hidden)
      if (!document.hidden) {
        const away = Date.now() - lastPollRef.current
        if (away > intervalMs) callback()  // 页面重新可见时立即刷新
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
  }, [])

  useEffect(() => {
    if (!pageVisible) return
    const timer = setInterval(callback, intervalMs)
    return () => clearInterval(timer)
  }, [pageVisible, intervalMs, callback])
}
```

### 6.2 Nexus 当前

- 5 秒轮询 (`_pollInterval = 5000`)
- SSE 流用于任务对话 (`_streamTaskConversation`)
- 页面可见性检测未实现

---

## 7. 可移植 UI 组件清单

### 高价值组件 (建议优先实现)

| 组件名 | 功能描述 | 参考文件 | 移植难度 |
|--------|----------|----------|----------|
| **MentionTextarea** | @提及自动完成输入框 | task-board-panel.tsx:1623 | 中 |
| **AgentAvatar** | Agent 头像组件 (带状态指示) | AgentAvatar component | 低 |
| **MarkdownRenderer** | Markdown 渲染 (含代码高亮) | markdown-renderer.tsx | 中 |
| **TaskCard** | 增强任务卡片 | task-board-panel.tsx:951-1109 | 中 |
| **TaskDetailModal** | 任务详情模态框 (4 tabs) | task-board-panel.tsx:1188-1735 | 高 |
| **CreateTaskModal** | 创建任务模态框 | task-board-panel.tsx:2035-2296 | 中 |
| **DraggableKanban** | 拖拽看板实现 | task-board-panel.tsx:928-1125 | 高 |

### 辅助 Hooks/工具

| 工具 | 功能 | 参考 | 移植难度 |
|------|------|------|----------|
| **useSmartPoll** | 智能轮询 (页面可见性感知) | use-smart-poll.ts | 低 |
| **useFocusTrap** | 模态框焦点陷阱 | use-focus-trap.ts | 低 |
| **formatTaskTimestamp** | 相对时间格式化 | task-board-panel.tsx | 低 |
| **detectAwaitingOwner** | 检测需人工干预任务 | task-board-panel.tsx:106-111 | 低 |

---

## 8. CSS/样式系统对比

### 8.1 Mission Control 设计 tokens

```css
/* Tailwind 自定义配置 */
{
  colors: {
    'priority-low': 'var(--green-500)',
    'priority-medium': 'var(--yellow-500)',
    'priority-high': 'var(--orange-500)',
    'priority-critical': 'var(--red-500)',
    'status-inbox': 'var(--secondary)',
    'status-assigned': 'var(--blue-500)',
    'status-awaiting_owner': 'var(--orange-500)',
    'status-in_progress': 'var(--yellow-500)',
    'status-review': 'var(--purple-500)',
    'status-quality_review': 'var(--indigo-500)',
    'status-done': 'var(--green-500)',
  }
}
```

### 8.2 建议的 Nexus CSS 变量映射

```css
:root {
  /* 优先级 */
  --priority-low: #22c55e;
  --priority-medium: #eab308;
  --priority-high: #f97316;
  --priority-critical: #ef4444;

  /* 状态列 */
  --status-inbox: #6b7280;
  --status-assigned: #3b82f6;
  --status-awaiting-owner: #f97316;
  --status-in-progress: #eab308;
  --status-review: #a855f7;
  --status-quality-review: #6366f1;
  --status-done: #22c55e;
}
```

---

## 9. 数据结构对比

### 9.1 Mission Control Task 接口

```typescript
interface Task {
  id: number
  title: string
  description?: string
  status: 'inbox' | 'assigned' | 'in_progress' | 'review' | 'quality_review' | 'done' | 'awaiting_owner'
  priority: 'low' | 'medium' | 'high' | 'critical' | 'urgent'
  assigned_to?: string
  created_by: string
  created_at: number
  updated_at: number
  due_date?: number
  estimated_hours?: number
  actual_hours?: number
  tags?: string[]
  metadata?: any
  aegisApproved?: boolean
  project_id?: number
  project_ticket_no?: number
  project_name?: string
  project_prefix?: string
  ticket_ref?: string
  github_issue_number?: number
  github_repo?: string
  github_branch?: string
  github_pr_number?: number
  github_pr_state?: string
}
```

### 9.2 Nexus 当前 Task 结构

```javascript
{
  id: string,
  description: string,
  status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'cancelled',
  priority: 'normal' | 'serious' | 'critical',
  alias?: string,
  provider?: string,
  workspace?: string,
  created_at: string,
  updated_at: string,
  session_id?: string,
  // 缺失字段:
  // - title (只有 description)
  // - assigned_to
  // - tags
  // - due_date
  // - project 关联
  // - GitHub 关联
  // - metadata.recurrence
}
```

---

## 10. 推荐的 UI 增强实施计划

### 阶段 1: 基础增强 (2 周)
1. 新增 7 列看板布局
2. 任务卡片视觉增强 (优先级彩条、标签、时间格式化)
3. AgentAvatar 组件
4. Markdown 渲染器

### 阶段 2: 交互增强 (2 周)
1. 拖拽看板实现
2. @提及输入框
3. 任务详情模态框 (4 tabs)
4. 评论系统

### 阶段 3: 高级功能 (2 周)
1. 质量审核 (Aegis) 集成
2. 周期性任务 UI
3. 底部扩展面板 (Claude/CodeBuddy/Hermes)
4. 智能轮询优化

---

## 附录: 关键代码片段

### A. 拖拽实现参考

```typescript
const handleDragStart = (e: React.DragEvent, task: Task) => {
  setDraggedTask(task)
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('application/json', JSON.stringify(task))
}

const handleDrop = async (e: React.DragEvent, newStatus: string) => {
  e.preventDefault()
  if (!draggedTask || draggedTask.status === newStatus) return

  const updatedTask = { ...draggedTask, status: newStatus }
  // Optimistic update
  setTasks(prev => prev.map(t => t.id === updatedTask.id ? updatedTask : t))

  // API call
  await fetch(`/api/tasks/${draggedTask.id}`, {
    method: 'PUT',
    body: JSON.stringify({ status: newStatus })
  })
}
```

### B. MentionTextarea 实现思路

```typescript
// 核心逻辑:
// 1. 监听 @ 字符输入
// 2. 显示下拉建议列表 (agents + users)
// 3. 选择后插入 @handle 格式文本
// 4. 高亮显示 @mention
```

### C. 智能轮询 Hook

```typescript
function useSmartPoll(callback, intervalMs = 10000) {
  const [pageVisible, setPageVisible] = useState(true)
  const lastPollRef = useRef(Date.now())

  useEffect(() => {
    const handleVisibilityChange = () => {
      const visible = !document.hidden
      setPageVisible(visible)
      if (visible && Date.now() - lastPollRef.current > intervalMs) {
        callback()  // 立即刷新
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [])

  useEffect(() => {
    if (!pageVisible) return
    const timer = setInterval(() => {
      lastPollRef.current = Date.now()
      callback()
    }, intervalMs)
    return () => clearInterval(timer)
  }, [pageVisible, intervalMs, callback])
}
```

---

*分析完成时间: 2026-04-10*
*分析师: AI Agent Team*
