# Add Orchestrator Skill

## Summary
Introduce a new "Orchestrator" skill (`prompts/skills/orchestrator`) that empowers agents to autonomously break down complex user requests into atomic, trackable tasks.

## Problem
Currently, when a user provides a complex, multi-step instruction (e.g., "Analyze 5 competitors and summarize"), the agent either attempts to do it all in one go (risking context overflow or timeout) or asks the user to break it down. There is no mechanism for the agent to "self-project-manage" and create structural tasks in the system's `TaskQueue` to track progress.

## Solution
Implement a **Chief Task Orchestrator** skill containing:
1.  **Prompt Strategy (`SKILL.md`)**: A specialized persona that analyzes requests and outputs a structured JSON execution plan.
2.  **Execution Tool (`scripts/orchestrator.py`)**: A lightweight Python script that consumes the JSON plan and interacts with the local Nexus API (`/api/nexus/tasks`) to create tasks, handling dependency resolution (linking serial tasks) automatically.

## Impact
- **Agent Autonomy**: Agents can handle higher-order goals by decomposing them.
- **Observability**: Users can see the breakdown of complex work in the Task Kanban/List.
- **Reliability**: Long-running workflows are persisted as distinct tasks, resilient to individual failures.
