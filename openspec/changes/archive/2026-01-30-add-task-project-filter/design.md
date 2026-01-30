# Design Decisions

## API Strategy
To populate the filter dropdown, the frontend needs a list of available projects.
We have two options:
1. **Client-side extraction**: Fetch all tasks and distinct project IDs in Javascript.
   - *Pros*: Zero backend changes.
   - *Cons*: Inefficient if task history grows large; requires fetching potentially closed/archived tasks just to find project names.
2. **Dedicated Endpoint** (Selected): `GET /api/nexus/projects`.
   - *Pros*: Clean separation of concerns; allows backend to optimize the query (e.g., using Redis sets or SQL `DISTINCT`).
   - *Cons*: Requires backend change.

We choose **Option 2** for better scalability and cleaner architecture.

## UI/UX
- **Location**: The filter will be placed in the Task view header (top control bar), adjacent to the "Refresh" or existing controls.
- **Default State**: "All Projects" (show everything).
- **Selection**:
    - When a specific project is selected, the Kanban board reloads with `?project_id=...`.
    - The selection persists during the session (in memory state) but does not need to persist across page reloads for this iteration.

## Data Flow
1. Page loads -> `NexusAPI.getProjects()` -> Populates dropdown.
2. `NexusAPI.getTasks()` called initially (no filter).
3. User selects "Project A".
4. Event listener triggers `NexusAPI.getTasks({ projectId: 'Project A' })`.
5. Board re-renders with filtered data.
