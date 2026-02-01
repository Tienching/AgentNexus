# Design: Workspace Navigation

## Context
Users often need to switch contexts between different projects or tasks. Currently, the agent operates in a fixed directory or relies on task-specific workspaces that might not be easily navigable manually.

## Architecture

### State Management
The `SlashCommandHandler` will need to track the **startup working directory** to support the `/exit` command.

```python
class SlashCommandHandler:
    def __init__(self, ...):
        self.startup_cwd = Path.cwd()
```

### Command Behavior

#### `/workspace <path>`
1.  **Validation**: Check if the path exists and is a directory.
2.  **Execution**: Use `os.chdir(path)` to change the current process's working directory.
3.  **Feedback**: Return a success message with the new path, or an error if invalid.

#### `/exit`
1.  **Check**: Compare current CWD with `self.startup_cwd`.
2.  **Execution**: If different, `os.chdir(self.startup_cwd)`.
3.  **Feedback**:
    - If already at startup: "Already at default directory."
    - If moved: "Returned to default directory: {path}"

## Trade-offs
- **Global State**: Changing CWD via `os.chdir` is a global change for the process. This is intended behavior per user requirements, but implies that concurrent operations relying on relative paths might be affected. (Note: The system seems to be designed as a single-agent session, so this is acceptable).
