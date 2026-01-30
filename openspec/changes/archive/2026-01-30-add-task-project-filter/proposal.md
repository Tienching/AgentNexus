# Add Project Filter to Task View

## Background
The current Task Kanban view displays all tasks for an agent regardless of which project they belong to. As the number of tasks grows across different projects, it becomes difficult to track progress for specific initiatives.

## Goal
Add a project selection dropdown to the Task view that allows users to filter the visible tasks by `project_id`.

## Scope
- **Backend**: Add an API endpoint to retrieve the list of unique projects.
- **Frontend**: Add a dropdown UI element to the Task view header.
- **Interaction**: Update the task list when the filter selection changes.

## Risks
- If the number of projects is very large, the dropdown UI might become unwieldy (mitigated by standard HTML select for now).
- Performance of extracting unique projects if not indexed (mitigated by expected low volume in single-agent context).
