# Spec: Slash Commands - Workspace Navigation

## ADDED Requirements

### Requirement: Workspace Switching
The system MUST provide a command to change the current working directory of the agent process.

#### Scenario: Switch to valid directory
Given the agent is running in `/app`
And a directory `/app/projects/foo` exists
When the user sends `/workspace -w /app/projects/foo`
Then the system changes the process working directory to `/app/projects/foo`
And returns a success message indicating the new path.

#### Scenario: Switch to task workspace
Given a task with ID `123` exists
And the task has a workspace at `/app/tasks/123`
When the user sends `/workspace -t 123`
Then the system changes the process working directory to `/app/tasks/123`
And sets up context inheritance for the task.

#### Scenario: Switch to invalid directory
Given the agent is running in `/app`
When the user sends `/workspace -w /nonexistent/path`
Then the system DOES NOT change the working directory
And returns an error message stating the path does not exist.

### Requirement: Exit Navigation
The system MUST provide a command to revert the working directory to the initial startup location.

#### Scenario: Exit to default from other directory
Given the agent started in `/app/home`
And the current working directory is `/app/projects/foo`
When the user sends `/exit`
Then the system changes the process working directory back to `/app/home`
And returns a success message confirming the return to default.

#### Scenario: Exit when already at default
Given the agent started in `/app/home`
And the current working directory is `/app/home`
When the user sends `/exit`
Then the system DOES NOT change the directory
And returns a message stating "Already at default address" (or similar).
