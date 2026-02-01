# Add Workspace and Exit Commands

## Why
This change introduces `/workspace` and `/exit` commands to allow users to switch context between tasks and return to the main session. This improves workflow efficiency when managing multiple tasks.

## What Changes
- Adds `/workspace` slash command to switch CWD
- Adds `/exit` slash command to return to home/session root
- Implements context inheritance for workspace switching

## Summary
Add `/workspace` and `/exit` slash commands to allow users to navigate the file system directly from the chat interface.

## Goals
- Enable users to switch the agent's current working directory (CWD) to a specific path or task workspace.
- Provide a quick way to return to the original startup directory.

## Impact
- **Modules**: `slash-commands`, `agent-runtime`
- **User Interface**: New slash commands available in chat.
- **System State**: The underlying process CWD will be modified by these commands.
