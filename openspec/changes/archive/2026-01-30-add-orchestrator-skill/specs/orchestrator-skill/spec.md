# Spec: Orchestrator Skill

## Overview
Defines the behavior and interface of the new `orchestrator` skill.

## ADDED Requirements

### Requirement: REQ-SKILL-001 Orchestrator Skill Definition
The system MUST provide a skill definition at `prompts/skills/orchestrator/SKILL.md`.

#### Scenario: Agent loads orchestrator skill
- **Given** the agent context includes the `orchestrator` skill
- **When** the agent reads `prompts/skills/orchestrator/SKILL.md`
- **Then** it understands it acts as a "Chief Task Orchestrator" that outputs JSON plans.

### Requirement: REQ-SKILL-002 Orchestrator Execution Script
The system MUST provide a CLI script at `prompts/skills/orchestrator/scripts/orchestrator.py` that implements the task creation logic.

#### Scenario: Creating independent tasks
- **Given** a JSON plan with two independent tasks `A` and `B`
- **When** the script is executed with this plan
- **Then** it makes two POST requests to `/api/nexus/tasks`
- **And** both tasks are created with no dependencies.

#### Scenario: Creating dependent tasks (Serial)
- **Given** a JSON plan with task `B` depending on task `A` (via temporary ID)
- **When** the script is executed
- **Then** it creates task `A` first and captures its UUID
- **And** it creates task `B` with `depends_on` field containing task `A`'s UUID.

#### Scenario: Handling API errors
- **Given** the Nexus API is down or returns 500
- **When** the script attempts to create a task
- **Then** it prints a descriptive error message to stderr
- **And** exits with a non-zero status code (or reports partial success if robust).

### Requirement: REQ-SKILL-003 Task API Integration
The orchestrator script MUST communicate with the local Nexus API.

#### Scenario: API Endpoint Usage
- **Given** the standard Nexus API configuration
- **When** the script runs
- **Then** it targets `http://localhost:8000/api/nexus/tasks` by default.
