# Nanobot Source Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge nanobot engine source code into agent-nexus as the default in-process chat provider, with orchestrator/mission skills auto-loaded.

**Architecture:** Copy nanobot core modules (~65 files, ~12k LOC) into `src/nanobot/`, rewrite imports from `nanobot.*` to `src.nanobot.*`, fix NanobotExecutor's `execute()` signature to match StreamOrchestrator's 3-arg calling convention, add `extra_skills_dirs` to SkillsLoader for nexus skill injection, and switch the default provider to `"nanobot"`.

**Tech Stack:** Python 3.11+, FastAPI, asyncio, pydantic-settings, OpenAI SDK, loguru

---

## File Structure

### New files (copied + rewritten)
- `src/nanobot/` — entire nanobot engine (~65 .py files across agent/, bus/, config/, mission/, providers/, session/, command/, cron/, skills/, utils/, security/)

### Modified files
- `src/providers/nanobot/executor.py` — fix `execute()` signature from 2-arg to 3-arg; change imports from `nanobot.*` to `src.nanobot.*`; replace symlink injection with `extra_skills_dirs`
- `src/nanobot/agent/skills.py` — add `extra_skills_dirs` parameter to `SkillsLoader`
- `src/providers/dispatcher.py` — change `_default_provider()` to return `"nanobot"`
- `pyproject.toml` — add nanobot runtime dependencies; remove `nanobot-ai` optional dep
- `tests/providers/nanobot/test_executor.py` — update for new `execute()` signature
- `tests/unit/test_provider_dispatcher.py` — update default provider expectations

### Unchanged files
- `src/runtime/streaming/orchestrator.py` — no changes needed
- `src/server/services/stream_handler.py` — no changes needed (slash commands still route to claude)
- `src/server/routers/chat.py` — no changes needed
- `src/providers/nanobot/adapter.py` — no changes needed
- `src/providers/nanobot/event_schema.py` — no changes needed
- `src/providers/nanobot/session_bridge.py` — no changes needed

---

### Task 1: Copy nanobot source + rewrite imports

**Files:**
- Create: `src/nanobot/` (entire directory tree, ~65 files)

- [ ] **Step 1: Copy included nanobot directories**

```bash
cd ~/Projects/agent-nexus_feature-dev

# Create target directory
mkdir -p src/nanobot

# Copy included modules (excluding channels, cli, gateway, heartbeat, templates)
for dir in agent bus command config cron mission providers session skills utils security; do
    cp -r ~/Projects/nanobot/nanobot/$dir src/nanobot/
done

# Copy root __init__.py
cp ~/Projects/nanobot/nanobot/__init__.py src/nanobot/
```

- [ ] **Step 2: Remove __pycache__ directories**

```bash
find src/nanobot -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
```

- [ ] **Step 3: Batch rewrite all imports**

```bash
# from nanobot.xxx → from src.nanobot.xxx
find src/nanobot -name "*.py" -exec sed -i 's/from nanobot\./from src.nanobot./g' {} +

# import nanobot.xxx → import src.nanobot.xxx
find src/nanobot -name "*.py" -exec sed -i 's/import nanobot\./import src.nanobot./g' {} +

# String references like "nanobot.xxx" module paths
find src/nanobot -name "*.py" -exec sed -i 's/"nanobot\./"src.nanobot./g' {} +
```

- [ ] **Step 4: Verify no old imports remain**

Run: `grep -rn "from nanobot\." src/nanobot/ | grep -v "src.nanobot" | head -20`
Expected: No output (all imports rewritten)

Run: `grep -rn "import nanobot\." src/nanobot/ | grep -v "src.nanobot" | head -20`
Expected: No output

- [ ] **Step 5: Verify top-level import works**

Run: `cd ~/Projects/agent-nexus_feature-dev && python3 -c "from src.nanobot.agent.loop import AgentLoop; print('AgentLoop import OK')"`
Expected: `AgentLoop import OK` (or a dependency error we fix in Task 3)

- [ ] **Step 6: Commit**

```bash
git add src/nanobot/
git commit -m "feat: copy nanobot engine source into src/nanobot/

Copy core nanobot modules (agent, bus, config, mission, providers,
session, command, cron, skills, utils, security) and rewrite all
imports from nanobot.* to src.nanobot.*.

Excludes: channels, cli, gateway, heartbeat, templates (agent-nexus
has its own implementations for these)."
```

---

### Task 2: Add nanobot dependencies to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add nanobot runtime dependencies**

In `pyproject.toml`, add these to the `dependencies` list (after existing entries):

```toml
dependencies = [
    # ... existing deps ...
    # Nanobot engine dependencies
    "openai>=2.8.0",
    "tiktoken>=0.12.0",
    "loguru>=0.7.3",
    "mcp>=1.26.0",
    "json-repair>=0.57.0",
    "chardet>=3.0.2",
    "ddgs>=9.5.5",
    "readability-lxml>=0.8.4",
]
```

- [ ] **Step 2: Remove nanobot-ai optional dependency**

Remove the `mission` optional-dependencies group that references `nanobot-ai`:

```toml
# DELETE this:
# mission = [
#     "nanobot-ai",
# ]
```

Also remove any `[tool.uv.sources]` entry for `nanobot-ai`.

- [ ] **Step 3: Install dependencies**

Run: `cd ~/Projects/agent-nexus_feature-dev && pip install -e . 2>&1 | tail -5`
Expected: Successful installation

- [ ] **Step 4: Verify import chain works end-to-end**

Run: `cd ~/Projects/agent-nexus_feature-dev && python3 -c "from src.nanobot.agent.loop import AgentLoop; from src.nanobot.providers.base import LLMProvider; print('All core imports OK')"`
Expected: `All core imports OK`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add nanobot engine runtime dependencies

Add openai, tiktoken, loguru, mcp, json-repair, chardet, ddgs,
readability-lxml. Remove nanobot-ai optional dependency (source
is now inline)."
```

---

### Task 3: Fix import errors from excluded modules

After copying, some nanobot code may import things that don't exist in our trimmed copy. This task handles those errors iteratively.

**Files:**
- Modify: various files in `src/nanobot/` as needed

- [ ] **Step 1: Run full import smoke test**

```bash
cd ~/Projects/agent-nexus_feature-dev
python3 -c "
import importlib, pkgutil, sys
errors = []
for importer, name, ispkg in pkgutil.walk_packages(['src/nanobot'], prefix='src.nanobot.'):
    try:
        importlib.import_module(name)
    except Exception as e:
        errors.append(f'{name}: {type(e).__name__}: {e}')
print(f'{len(errors)} import errors:')
for e in errors[:20]:
    print(f'  {e}')
"
```

- [ ] **Step 2: Fix each import error**

For each error found in Step 1:
- If it's a missing module from an excluded directory (channels, cli, gateway, etc.) — guard the import with `try/except ImportError` or remove the dead code path.
- If it's a missing third-party dependency — add it to `pyproject.toml` and `pip install`.
- If it's a file-not-found for a non-Python resource — create a stub or fix the path.

Iterate: run the smoke test again after each fix until zero errors.

- [ ] **Step 3: Verify key module imports**

```bash
cd ~/Projects/agent-nexus_feature-dev
python3 -c "
from src.nanobot.agent.loop import AgentLoop
from src.nanobot.agent.skills import SkillsLoader
from src.nanobot.agent.context import ContextBuilder
from src.nanobot.bus.queue import MessageBus
from src.nanobot.config.loader import load_config
from src.nanobot.session.manager import SessionManager
from src.nanobot.mission.service import MissionService
print('All key imports OK')
"
```
Expected: `All key imports OK`

- [ ] **Step 4: Commit**

```bash
git add -A src/nanobot/
git commit -m "fix: resolve import errors from excluded nanobot modules"
```

---

### Task 4: Fix NanobotExecutor.execute() signature

**Files:**
- Modify: `src/providers/nanobot/executor.py`
- Test: `tests/providers/nanobot/test_executor.py`

- [ ] **Step 1: Write failing test for 3-arg signature**

In `tests/providers/nanobot/test_executor.py`, add this test:

```python
@pytest.mark.asyncio
async def test_execute_accepts_request_model_and_exec_user(self):
    """execute() must accept (request, exec_user, output_format) like other executors."""
    from unittest.mock import MagicMock, AsyncMock, patch

    mock_request = MagicMock()
    mock_request.content = "Hello"
    mock_request.session_id = "test-session"
    mock_request.cwd = None
    mock_request.model = None

    mock_loop = AsyncMock()
    async def fake_process_direct(**kwargs):
        kwargs['on_stream'] and await kwargs['on_stream']("Hi!")
        kwargs['on_stream_end'] and await kwargs['on_stream_end'](resuming=False)
        return MagicMock(content="Hi!")
    mock_loop.process_direct = lambda *a, **kw: fake_process_direct(**kw)

    with patch.object(_NanobotPool, "get_or_create", return_value=mock_loop):
        executor = NanobotExecutor()
        lines = []
        # Key: call with (request_model, exec_user=..., output_format=...)
        async for line in executor.execute(mock_request, exec_user="ubuntu", output_format="raw"):
            lines.append(line)

    assert len(lines) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/agent-nexus_feature-dev && python3 -m pytest tests/providers/nanobot/test_executor.py::TestNanobotExecutorExecute::test_execute_accepts_request_model_and_exec_user -v`
Expected: FAIL (TypeError: execute() got unexpected keyword argument 'exec_user')

- [ ] **Step 3: Fix execute() signature**

In `src/providers/nanobot/executor.py`, replace the `execute()` method signature:

```python
async def execute(
    self,
    request: Any,              # RequestModel from StreamHandler
    exec_user: str = "default",
    output_format: str = "raw",
) -> AsyncGenerator[str, None]:
    """Execute a user message through nanobot's AgentLoop.

    Signature matches CLIExecutor/GeminiExecutor for StreamOrchestrator
    compatibility. The request parameter is a RequestModel instance.
    """
    # Extract fields from RequestModel
    content = getattr(request, 'content', '') or ''
    session_id = getattr(request, 'session_id', 'default') or 'default'
    cwd = getattr(request, 'cwd', None)
    model_override = getattr(request, 'model', None)

    if not content.strip():
        return

    # Resolve workspace
    workspace = cwd or self._workspace or str(Path.home() / "Projects")

    # ... rest of implementation unchanged, using content/session_id/workspace ...
```

Also update the import at the top — change `from nanobot.` to `from src.nanobot.`:

```python
# In _NanobotPool._create_loop():
from src.nanobot.config.loader import load_config
from src.nanobot.providers.factory import create_provider
from src.nanobot.bus.queue import MessageBus
from src.nanobot.agent.loop import AgentLoop
```

- [ ] **Step 4: Update existing tests for new signature**

In the existing test methods (`test_streaming_text`, `test_tool_events`, `test_error_on_pool_failure`), change mock call patterns from:

```python
ctx = RequestContext(content="hi", session_id="s2")
async for line in executor.execute(ctx):
```

to:

```python
mock_request = MagicMock()
mock_request.content = "hi"
mock_request.session_id = "s2"
mock_request.cwd = None
mock_request.model = None
async for line in executor.execute(mock_request, exec_user="ubuntu"):
```

- [ ] **Step 5: Run all nanobot tests**

Run: `cd ~/Projects/agent-nexus_feature-dev && python3 -m pytest tests/providers/nanobot/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/providers/nanobot/executor.py tests/providers/nanobot/test_executor.py
git commit -m "fix: NanobotExecutor.execute() matches StreamOrchestrator 3-arg signature

Change execute(context, output_format) to execute(request, exec_user,
output_format) to match CLIExecutor/GeminiExecutor calling convention
used by StreamOrchestrator.stream_agui()."
```

---

### Task 5: Add extra_skills_dirs to SkillsLoader

**Files:**
- Modify: `src/nanobot/agent/skills.py`

- [ ] **Step 1: Add extra_skills_dirs parameter**

In `src/nanobot/agent/skills.py`, modify `SkillsLoader.__init__`:

```python
def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None, extra_skills_dirs: list[Path] | None = None):
    self.workspace = workspace
    self.workspace_skills = workspace / "skills"
    self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR
    self.extra_skills_dirs = extra_skills_dirs or []
```

- [ ] **Step 2: Add extra dirs to list_skills()**

In `list_skills()`, add the extra skills dirs scan between workspace and builtin:

```python
def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
    skills = []

    # Workspace skills (highest priority)
    if self.workspace_skills.exists():
        for skill_dir in self.workspace_skills.iterdir():
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "workspace"})

    # Extra skills directories (e.g., agent-nexus prompts/skills/)
    for extra_dir in self.extra_skills_dirs:
        if extra_dir.exists():
            for skill_dir in extra_dir.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists() and not any(s["name"] == skill_dir.name for s in skills):
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "extra"})

    # Built-in skills (lowest priority)
    if self.builtin_skills and self.builtin_skills.exists():
        for skill_dir in self.builtin_skills.iterdir():
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists() and not any(s["name"] == skill_dir.name for s in skills):
                    skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "builtin"})

    if filter_unavailable:
        return [s for s in skills if self._check_requirements(self._get_skill_meta(s["name"]))]
    return skills
```

Also add extra dirs to `load_skill()`:

```python
def load_skill(self, name: str) -> str | None:
    # Check workspace first
    workspace_skill = self.workspace_skills / name / "SKILL.md"
    if workspace_skill.exists():
        return workspace_skill.read_text(encoding="utf-8")

    # Check extra dirs
    for extra_dir in self.extra_skills_dirs:
        extra_skill = extra_dir / name / "SKILL.md"
        if extra_skill.exists():
            return extra_skill.read_text(encoding="utf-8")

    # Check built-in
    if self.builtin_skills:
        builtin_skill = self.builtin_skills / name / "SKILL.md"
        if builtin_skill.exists():
            return builtin_skill.read_text(encoding="utf-8")

    return None
```

- [ ] **Step 3: Verify unchanged behavior without extra dirs**

Run: `cd ~/Projects/agent-nexus_feature-dev && python3 -c "
from pathlib import Path
from src.nanobot.agent.skills import SkillsLoader
loader = SkillsLoader(Path('/tmp/test-workspace'))
skills = loader.list_skills(filter_unavailable=False)
print(f'Found {len(skills)} builtin skills')
for s in skills[:5]:
    print(f'  {s[\"name\"]} ({s[\"source\"]})')
"`
Expected: Lists built-in skills (like `memory`, `skill-creator`)

- [ ] **Step 4: Commit**

```bash
git add src/nanobot/agent/skills.py
git commit -m "feat: SkillsLoader supports extra_skills_dirs for external skill injection

Add extra_skills_dirs parameter to SkillsLoader. Extra dirs are searched
after workspace skills but before builtin skills. This allows agent-nexus
to inject its orchestrator/mission skills into the nanobot engine."
```

---

### Task 6: Inject nexus skills in NanobotExecutor

**Files:**
- Modify: `src/providers/nanobot/executor.py`

- [ ] **Step 1: Replace symlink injection with extra_skills_dirs**

In `_NanobotPool._create_loop()`, after creating the AgentLoop, replace the old `_inject_nexus_skills()` symlink logic with:

```python
# Inject agent-nexus skills (orchestrator, mission) via SkillsLoader
nexus_skills_dir = Path(__file__).resolve().parents[3] / "prompts" / "skills"
if nexus_skills_dir.exists():
    loop.context.skills.extra_skills_dirs = [nexus_skills_dir]
    logger.info("Injected nexus skills from %s", nexus_skills_dir)
```

Remove the `_inject_nexus_skills()` static method entirely (no more symlinks).

- [ ] **Step 2: Verify skill injection works**

Run: `cd ~/Projects/agent-nexus_feature-dev && python3 -c "
from pathlib import Path
from src.nanobot.agent.skills import SkillsLoader
nexus_skills = Path('prompts/skills')
loader = SkillsLoader(Path('/tmp/test-workspace'), extra_skills_dirs=[nexus_skills])
skills = loader.list_skills(filter_unavailable=False)
names = [s['name'] for s in skills]
print('orchestrator' in names, 'mission' in names)
for s in skills:
    if s['name'] in ('orchestrator', 'mission'):
        print(f'  {s[\"name\"]} -> {s[\"path\"]} ({s[\"source\"]})')
"`
Expected: `True True` and paths pointing to `prompts/skills/orchestrator/SKILL.md` and `prompts/skills/mission/SKILL.md`

- [ ] **Step 3: Commit**

```bash
git add src/providers/nanobot/executor.py
git commit -m "feat: inject nexus skills via SkillsLoader.extra_skills_dirs

Replace symlink-based skill injection with extra_skills_dirs parameter.
orchestrator and mission skills from prompts/skills/ are now
automatically discovered by the nanobot engine."
```

---

### Task 7: Switch default provider to nanobot

**Files:**
- Modify: `src/providers/dispatcher.py`
- Modify: `tests/unit/test_provider_dispatcher.py`
- Modify: `tests/providers/nanobot/test_dispatcher.py`

- [ ] **Step 1: Change _default_provider() to return "nanobot"**

In `src/providers/dispatcher.py`, line 28:

```python
def _default_provider() -> str:
    """Return the default provider key (configurable via env var)."""
    import os
    return os.environ.get("AGENT_NEXUS_DEFAULT_PROVIDER", "nanobot")
```

- [ ] **Step 2: Update unit test expectations**

In `tests/unit/test_provider_dispatcher.py`:

- `test_none_defaults_to_claude` → rename to `test_none_defaults_to_nanobot`, assert `== "nanobot"`
- `test_empty_string_defaults_to_claude` → rename, assert `== "nanobot"`
- `test_whitespace_defaults_to_claude` → rename, assert `== "nanobot"`
- `test_unknown_provider_falls_back_to_claude` → rename, assert `== "nanobot"`
- `test_unknown_provider_falls_back_to_claude` (executor) → mock `NanobotExecutor` instead of `CLIExecutor`
- `test_none_provider_falls_back_to_claude` (executor) → mock `NanobotExecutor` instead of `CLIExecutor`
- `test_unknown_provider_uses_claude_adapter` → mock `NanobotAGUIAdapter` instead of `AGUIAdapter`

- [ ] **Step 3: Run all tests**

Run: `cd ~/Projects/agent-nexus_feature-dev && python3 -m pytest tests/providers/nanobot/ tests/unit/test_provider_dispatcher.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add src/providers/dispatcher.py tests/unit/test_provider_dispatcher.py tests/providers/nanobot/test_dispatcher.py
git commit -m "feat: switch default chat provider to nanobot

Default provider changes from 'claude' to 'nanobot'. Override with
AGENT_NEXUS_DEFAULT_PROVIDER=claude env var, ?provider=claude query
param, or /switch claude command."
```

---

### Task 8: End-to-end verification

- [ ] **Step 1: Run full import chain test**

```bash
cd ~/Projects/agent-nexus_feature-dev
python3 -c "
# 1. Nanobot engine imports
from src.nanobot.agent.loop import AgentLoop
from src.nanobot.agent.skills import SkillsLoader
from src.nanobot.config.loader import load_config

# 2. Provider imports
from src.providers.nanobot import NanobotExecutor, NanobotAGUIAdapter
from src.providers.nanobot.event_schema import TextDeltaEvent, ToolStartEvent

# 3. Dispatcher integration
from src.providers.dispatcher import normalize_provider, create_adapter
assert normalize_provider(None) == 'nanobot'
assert normalize_provider('claude') == 'claude'
adapter = create_adapter('nanobot')
assert type(adapter).__name__ == 'NanobotAGUIAdapter'

print('All imports and assertions OK')
"
```
Expected: `All imports and assertions OK`

- [ ] **Step 2: Run all nanobot tests**

Run: `cd ~/Projects/agent-nexus_feature-dev && python3 -m pytest tests/providers/nanobot/ -v`
Expected: All PASS

- [ ] **Step 3: Run full dispatcher tests**

Run: `cd ~/Projects/agent-nexus_feature-dev && python3 -m pytest tests/unit/test_provider_dispatcher.py -v`
Expected: All PASS

- [ ] **Step 4: Verify skill injection**

```bash
cd ~/Projects/agent-nexus_feature-dev
python3 -c "
from pathlib import Path
from src.nanobot.agent.skills import SkillsLoader
loader = SkillsLoader(Path('/tmp/ws'), extra_skills_dirs=[Path('prompts/skills')])
names = [s['name'] for s in loader.list_skills(filter_unavailable=False)]
assert 'orchestrator' in names, f'orchestrator not found in {names}'
assert 'mission' in names, f'mission not found in {names}'
print(f'Skills OK: {len(names)} skills found, including orchestrator and mission')
"
```
Expected: `Skills OK: N skills found, including orchestrator and mission`

- [ ] **Step 5: Verify safe fallback to claude**

```bash
cd ~/Projects/agent-nexus_feature-dev
AGENT_NEXUS_DEFAULT_PROVIDER=claude python3 -c "
from src.providers.dispatcher import normalize_provider
assert normalize_provider(None) == 'claude', 'Env var fallback broken'
assert normalize_provider('nanobot') == 'nanobot', 'Explicit nanobot broken'
print('Fallback to claude OK')
"
```
Expected: `Fallback to claude OK`

- [ ] **Step 6: Final commit with test results**

```bash
git add -A
git status
# Only commit if there are uncommitted test fixes
git diff --cached --stat | head -5
```
