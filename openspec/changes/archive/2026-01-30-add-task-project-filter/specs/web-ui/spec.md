## ADDED Requirements

### Requirement: REQ-UI-011 Project Filter
The Task view MUST provide a mechanism to filter visible tasks by their associated project.

#### Scenario: Filter tasks by specific project
- **Given** Multiple tasks exist across different projects (e.g., "Project A", "Project B")
- **And** The user is on the Task view
- **When** The user selects "Project A" from the project filter
- **Then** Only tasks belonging to "Project A" are displayed
- **And** Tasks from "Project B" are hidden

#### Scenario: Show all tasks (Clear filter)
- **Given** A specific project is currently selected in the filter
- **When** The user selects "All Projects" (or equivalent default option)
- **Then** Tasks from all projects are displayed

#### Scenario: Populate project filter
- **Given** The system has tasks associated with distinct project IDs
- **When** The Task view loads
- **Then** The filter dropdown contains a list of all unique project IDs
