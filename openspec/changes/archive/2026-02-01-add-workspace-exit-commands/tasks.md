# Tasks

1.  [ ] **Store Startup CWD**
    - Modify `SlashCommandHandler.__init__` in `src/runtime/commands/slash/handler.py` to capture `os.getcwd()` as `self.startup_cwd`.

2.  [ ] **Implement `/workspace` Command**
    - Add `_handle_workspace(self, args: str)` method.
    - Validate path existence.
    - Perform `os.chdir()`.
    - Handle exceptions (permissions, not found).

3.  [ ] **Implement `/exit` Command**
    - Add `_handle_exit(self)` method.
    - Check current vs startup CWD.
    - Perform restore or return warning.

4.  [ ] **Register Commands**
    - Update `SLASH_COMMANDS` list in `src/runtime/commands/slash/handler.py` (or `__init__.py`) to include `/workspace` and `/exit`.
    - Update `handle_command` dispatch logic.

5.  [ ] **Verify & Test**
    - Add unit tests in `tests/unit/test_slash_commands.py` covering:
        - Successful directory change.
        - Invalid path handling.
        - Exit when changed.
        - Exit when already at home.
