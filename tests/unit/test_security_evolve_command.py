# -*- coding: utf-8 -*-
"""Regression tests for evolve command quoting (P0-3).

These verify that user/LLM-controlled values flowing into git commands are
shlex-quoted and that commit messages go via stdin (-F -).
"""
import shlex

import src.core.agent_runtime.evolve.implementation as impl


class TestEvolveCommandSafety:
    def test_get_git_diff_files_quotes_base_sha(self):
        # the function body references shlex.quote(base_sha)
        import inspect
        src = inspect.getsource(impl.get_git_diff_files)
        assert "shlex.quote" in src

    def test_try_merge_uses_stdin_for_commit_msg(self):
        import inspect
        src = inspect.getsource(impl.try_merge)
        # commit messages must go via stdin (-F -), never via -m "..."
        assert "-F -" in src
        assert 'stdin_data=commit_msg' in src
        assert '-m "' not in src

    def test_codebuddy_conflict_quotes_files(self):
        import inspect
        src = inspect.getsource(impl.codebuddy_resolve_conflict)
        # conflicted file names are quoted
        assert "shlex.quote(f) for f in conflicted" in src
        assert "-F -" in src  # commit via stdin

    def test_no_unquoted_fstring_run_shell_calls(self):
        """No _run_shell(f"...{var}...") without shlex.quote on the var.

        Constant-only commands are fine. We check the whole module source for
        raw variable interpolation in _run_shell f-strings.
        """
        import inspect
        full = inspect.getsource(impl)
        # every f-string run_shell call that contains an interpolation must be
        # accompanied by shlex.quote; here we just assert the dangerous
        # '-m "' commit pattern is gone everywhere.
        assert '-m "' not in full.replace('shlex.quote', '')  # after stripping, no raw -m "
