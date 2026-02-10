## ADDED Requirements

### Requirement: REQ-API-013 List Projects
The system MUST provide an endpoint to retrieve a list of unique projects derived from existing tasks.

#### Scenario: Get list of projects
- **Given** Tasks exist with `project_id` values "proj-1" and "proj-2"
- **When** Request `GET /api/nexus/projects`
- **Then** Return a list containing "proj-1" and "proj-2"
- **And** The list does not contain duplicates
- **And** The list contains project names if available

#### Scenario: Get projects for specific agent
- **Given** Multiple agents exist
- **When** Request `GET /api/nexus/projects?exec_user=ubuntu`
- **Then** Only return projects associated with the specified agent's tasks
