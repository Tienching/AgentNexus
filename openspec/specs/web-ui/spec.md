# web-ui Specification

## Purpose
TBD - created by archiving change add-nexushub-web-viewer. Update Purpose after archive.
## Requirements
### Requirement: REQ-UI-001 Session List Page
系统必须提供会话列表页面。

#### Scenario: Display session list
- **Given** 用户访问 `/nexus/`
- **When** 页面加载完成
- **Then** 显示用户的所有会话
- **And** 会话按更新时间降序排列

#### Scenario: Group sessions by date
- **Given** 用户有不同日期的会话
- **When** 页面显示会话列表
- **Then** 会话按日期分组（今天、昨天、本周等）

#### Scenario: Display session status
- **Given** 会话有不同状态
- **When** 页面显示会话
- **Then** 显示状态标签（Running/Completed/Error）
- **And** Running 状态有动画指示

#### Scenario: Empty session list
- **Given** 用户没有会话
- **When** 页面加载完成
- **Then** 显示空状态提示

### Requirement: REQ-UI-002 Session Search
系统必须提供会话搜索功能。

#### Scenario: Search by title
- **Given** 用户在搜索框输入关键词
- **When** 输入完成后
- **Then** 列表过滤显示匹配的会话

#### Scenario: Clear search
- **Given** 搜索框有内容
- **When** 用户清空搜索框
- **Then** 显示所有会话

### Requirement: REQ-UI-003 Session Detail Page
系统必须提供会话详情页面。

#### Scenario: View session messages
- **Given** 用户点击会话
- **When** 跳转到详情页
- **Then** 显示会话的所有消息

#### Scenario: Display message roles
- **Given** 消息有不同角色
- **When** 显示消息列表
- **Then** 用户消息右对齐
- **And** 助手消息左对齐
- **And** 不同角色有不同样式

#### Scenario: Display tool calls
- **Given** 消息包含工具调用
- **When** 显示消息
- **Then** 工具调用以折叠卡片形式显示
- **And** 点击可展开查看详情

#### Scenario: Render markdown content
- **Given** 消息内容包含 Markdown
- **When** 显示消息
- **Then** Markdown 正确渲染（标题、列表、代码块等）

#### Scenario: Navigate back to list
- **Given** 用户在详情页
- **When** 点击返回按钮
- **Then** 返回会话列表页

### Requirement: REQ-UI-004 Delete Session
系统必须提供删除会话功能。

#### Scenario: Delete session from list
- **Given** 用户在会话列表
- **When** 点击会话的删除按钮
- **Then** 显示确认对话框

#### Scenario: Confirm delete
- **Given** 删除确认对话框显示
- **When** 用户确认删除
- **Then** 会话从列表移除
- **And** 后端数据删除

### Requirement: REQ-UI-005 Responsive Design
Web UI 必须支持响应式布局。

#### Scenario: Mobile view
- **Given** 用户使用移动设备访问
- **When** 页面加载
- **Then** 布局适应小屏幕
- **And** 所有功能可用

#### Scenario: Desktop view
- **Given** 用户使用桌面浏览器访问
- **When** 页面加载
- **Then** 充分利用大屏幕空间

### Requirement: REQ-UI-006 Static File Serving
Web UI 必须作为 FastAPI 静态文件服务。

#### Scenario: Access index page
- **Given** FastAPI 服务运行中
- **When** 访问 `/nexus/`
- **Then** 返回 `index.html`

#### Scenario: Access static assets
- **Given** FastAPI 服务运行中
- **When** 访问 `/nexus/js/app.js`
- **Then** 返回 JavaScript 文件
- **And** Content-Type 正确

### Requirement: REQ-UI-007 Error Handling
Web UI 必须优雅处理错误。

#### Scenario: API request fails
- **Given** 后端 API 不可用
- **When** 页面尝试加载数据
- **Then** 显示错误提示
- **And** 提供重试选项

#### Scenario: Session load fails
- **Given** 会话详情加载失败
- **When** 用户访问详情页
- **Then** 显示错误信息
- **And** 提供返回列表选项

