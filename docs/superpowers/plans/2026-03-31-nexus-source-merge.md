# Nexus Source Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge nexus engine source code into agent-nexus as the default in-process chat provider, with orchestrator/mission skills auto-loaded.

**Architecture:** Copy nexus core modules (~65 files, ~12k LOC) into `src/nexus/`, rewrite imports from `nexus.*` to `src.nexus.*`, fix NexusExecutor's `execute()` signature to match StreamOrchestrator's 3-arg calling convention, add `extra_skills_dirs` to SkillsLoader for nexus skill injection, and switch the default provider to `"nexus"`.

**Tech Stack:** Python 3.11+, FastAPI, asyncio, pydantic-settings, OpenAI SDK, loguru

---

## File Structure

### New files (copied + rewritten)
- `src/nexus/` — entire nexus engine (~65 .py files across agent/, bus/, config/, mission/, providers/, session/, command/, cron/, skills/, utils/, security/)

### Modified files
- `src/providers/nexus/executor.py` — fix `execute()` signature from 2-arg to 3-arg; change imports from `nexus.*` to `src.nexus.*`; replace symlink injection with `extra_skills_dirs`
- `src/nexus/agent/skills.py` — add `extra_skills_dirs` parameter to `SkillsLoader`
- `src/providers/dispatcher.py` — change `_default_provider()` to return `"nexus"`
- `pyproject.toml` — add nexus runtime dependencies; remove `nexus-ai` optional dep
- `tests/providers/nexus/test_executor.py` — update for new `execute()` signature
- `tests/unit/test_provider_dispatcher.py` — update default provider expectations

### Unchanged files
- `src/runtime/streaming/orchestrator.py` — no changes needed
- `src/server/services/stream_handler.py` — no changes needed (slash commands still route to claude)
- `src/server/routers/chat.py` — no changes needed
- `src/providers/nexus/adapter.py` — no changes needed
- `src/providers/nexus/event_schema.py` — no changes needed
- `src/providers/nexus/session_bridge.py` — no changes needed

---

### Task 1: Copy nexus source + rewrite imports

**Files:**
- Create: `src/nexus/` (entire directory tree, ~65 files)

- [ ] **Step 1: Copy included nexus directories**

```bash
cd ~/Projects/agent-nexus_feature-dev

# Create target directory
mkdir -p src/nexus

# Copy included modules (excluding channels, cli, gateway, heartbeat, templates)
for dir in agent bus command config cron mission providers session skills utils security; do
    cp -r ~/Projects/nexus/nexus/$dir src/nexus/
done

# Copy root __init__.py
cp ~/Projects/nexus/nexus/__init__.py src/nexus/
```

- [ ] **Step 2: Remove __pycache__ directories**

```bash
find src/nexus -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
```

- [ ] **Step 3: Batch rewrite all imports**

```bash
# from nexus.xxx → from src.nexus.xxx
find src/nexus -name "*.py" -exec sed -i 's/from nexus\./from src.nexus./g' {} +

# import nexus.xxx → import src.nexus.xxx
find src/nexus -name "*.py" -exec sed -i 's/import nexus\./import src.nexus./g' {} +

# String references like "nexus.xxx" module paths
find src/nexus -name "*.py" -exec sed -i 's/"nexus\./"src.nexus./g' {} +
```

- [ ] **Step 4: Verify no old imports remain**

Run: `grep -rn "from nexus\." src/nexus/ | grep -v "src.nexus" | head -20`
Expected: No output (all imports rewritten)

Run: `grep -rn "import nexus\." src/nexus/ | grep -v "src.nexus" | head -20`
Expected: No output

- [ ] **Step 5: Verify top-level import works**

Run: `cd ~/Projects/agent-nexus_feature-dev && python3 -c "from src.nexus.agent.loop import AgentLoop; print('AgentLoop import OK')"`
Expected: `AgentLoop import OK` (or a dependency error we fix in Task 3)

- [ ] **Step 6: Commit**

```bash
git add src/nexus/
git commit -m "feat: copy nexus engine source into src/nexus/

Copy core nexus modules (agent, bus, config, mission, providers,
session, command, cron, skills, utils, security) and rewrite all
imports from nexus.* to src.nexus.*.

Excludes: channels, cli, gateway, heartbeat, templates (agent-nexus
has its own implementations for these)."
```

---

### Task 2: Add nexus dependencies to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add nexus runtime dependencies**

In `pyproject.toml`, add these to the `dependencies` list (after existing entries):

```toml
dependencies = [
    # ... existing deps ...
    # Nexus engine dependencies
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

- [ ] **Step 2: Remove nexus-ai optional dependency**

Remove the `mission` optional-dependencies group that references `nexus-ai`:

```toml
# DELETE this:
# mission = [
#     "nexus-ai",
# ]
```

Also remove any `[tool.uv.sources]` entry for `nexus-ai`.

- [ ] **Step 3: Install dependencies**

Run: `cd ~/Projects/agent-nexus_feature-dev && pip install -e . 2>&1 | tail -5`
Expected: Successful installation

- [ ] **Step 4: Verify import chain works end-to-end**

Run: `cd ~/Projects/agent-nexus_feature-dev && python3 -c "from src.nexus.agent.loop import AgentLoop; from src.nexus.providers.base import LLMProvider; print('All core imports OK')"`
Expected: `All core imports OK`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add nexus engine runtime dependencies

Add openai, tiktoken, loguru, mcp, json-repair, chardet, ddgs,
readability-lxml. Remove nexus-ai optional dependency (source
is now inline)."
```

---

### Task 3: Fix import errors from excluded modules

After copying, some nexus code may import things that don't exist in our trimmed copy. This task handles those errors iteratively.

**Files:**
- Modify: various files in `src/nexus/` as needed

- [ ] **Step 1: Run full import smoke test**

```bash
cd ~/Projects/agent-nexus_feature-dev
python3 -c "
import importlib, pkgutil, sys
errors = []
for importer, name, ispkg in pkgutil.walk_packages(['src/nexus'], prefix='src.nexus.'):
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
from src.nexus.agent.loop import AgentLoop
from src.nexus.agent.skills import SkillsLoader
from src.nexus.agent.context import ContextBuilder
from src.nexus.bus.queue import MessageBus
from src.nexus.config.loader import load_config
from src.nexus.session.manager import SessionManager
from src.nexus.mission.service import MissionService
print('All key imports OK')
"
```
Expected: `All key imports OK`

- [ ] **Step 4: Commit**

```bash
git add -A src/nexus/
git commit -m "fix: resolve import errors from excluded nexus modules"
```

---

### Task 4: Fix NexusExecutor.execute() signature

**Files:**
- Modify: `src/providers/nexus/executor.py`
- Test: `tests/providers/nexus/test_executor.py`

- [ ] **Step 1: Write failing test for 3-arg signature**

In `tests/providers/nexus/test_executor.py`, add this test:

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

    with patch.object(_NexusPool, "get_or_create", return_value=mock_loop):
        executor = NexusExecutor()
        lines = []
        # Key: call with (request_model, exec_user=..., output_format=...)
        async for line in executor.execute(mock_request, exec_user="ubuntu", output_format="raw"):
            lines.append(line)

    assert len(lines) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/agent-nexus_feature-dev && python3 -m pytest tests/providers/nexus/test_executor.py::TestNexusExecutorExecute::test_execute_accepts_request_model_and_exec_user -v`
Expected: FAIL (TypeError: execute() got unexpected keyword argument 'exec_user')

- [ ] **Step 3: Fix execute() signature**

In `src/providers/nexus/executor.py`, replace the `execute()` method signature:

```python
async def execute(
    self,
    request: Any,              # RequestModel from StreamHandler
    exec_user: str = "default",
    output_format: str = "raw",
) -> AsyncGenerator[str, None]:
    """Execute a user message through nexus's AgentLoop.

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

Also update the import at the top — change `from nexus.` to `from src.nexus.`:

```python
# In _NexusPool._create_loop():
from src.nexus.config.loader import load_config
from src.nexus.providers.factory import create_provider
from src.nexus.bus.queue import MessageBus
from src.nexus.agent.loop import AgentLoop
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

- [ ] **Step 5: Run all nexus tests**

Run: `cd ~/Projects/agent-nexus_feature-dev && python3 -m pytest tests/providers/nexus/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/providers/nexus/executor.py tests/providers/nexus/test_executor.py
git commit -m "fix: NexusExecutor.execute() matches StreamOrchestrator 3-arg signature

Change execute(context, output_format) to execute(request, exec_user,
output_format) to match CLIExecutor/GeminiExecutor calling convention
used by StreamOrchestrator.stream_agui()."
```

---

### Task 5: Add extra_skills_dirs to SkillsLoader

**Files:**
- Modify: `src/nexus/agent/skills.py`

- [ ] **Step 1: Add extra_skills_dirs parameter**

In `src/nexus/agent/skills.py`, modify `SkillsLoader.__init__`:

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
from src.nexus.agent.skills import SkillsLoader
loader = SkillsLoader(Path('/tmp/test-workspace'))
skills = loader.list_skills(filter_unavailable=False)
print(f'Found {len(skills)} builtin skills')
for s in skills[:5]:
    print(f'  {s[\"name\"]} ({s[\"source\"]})')
"`
Expected: Lists built-in skills (like `memory`, `skill-creator`)

- [ ] **Step 4: Commit**

```bash
git add src/nexus/agent/skills.py
git commit -m "feat: SkillsLoader supports extra_skills_dirs for external skill injection

Add extra_skills_dirs parameter to SkillsLoader. Extra dirs are searched
after workspace skills but before builtin skills. This allows agent-nexus
to inject its orchestrator/mission skills into the nexus engine."
```

---

### Task 6: Inject nexus skills in NexusExecutor

**Files:**
- Modify: `src/providers/nexus/executor.py`

- [ ] **Step 1: Replace symlink injection with extra_skills_dirs**

In `_NexusPool._create_loop()`, after creating the AgentLoop, replace the old `_inject_nexus_skills()` symlink logic with:

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
from src.nexus.agent.skills import SkillsLoader
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
git add src/providers/nexus/executor.py
git commit -m "feat: inject nexus skills via SkillsLoader.extra_skills_dirs

Replace symlink-based skill injection with extra_skills_dirs parameter.
orchestrator and mission skills from prompts/skills/ are now
automatically discovered by the nexus engine."
```

---

### Task 7: Switch default provider to nexus

**Files:**
- Modify: `src/providers/dispatcher.py`
- Modify: `tests/unit/test_provider_dispatcher.py`
- Modify: `tests/providers/nexus/test_dispatcher.py`

- [ ] **Step 1: Change _default_provider() to return "nexus"**

In `src/providers/dispatcher.py`, line 28:

```python
def _default_provider() -> str:
    """Return the default provider key (configurable via env var)."""
    import os
    return os.environ.get("AGENT_NEXUS_DEFAULT_PROVIDER", "nexus")
```

- [ ] **Step 2: Update unit test expectations**

In `tests/unit/test_provider_dispatcher.py`:

- `test_none_defaults_to_claude` → rename to `test_none_defaults_to_nexus`, assert `== "nexus"`
- `test_empty_string_defaults_to_claude` → rename, assert `== "nexus"`
- `test_whitespace_defaults_to_claude` → rename, assert `== "nexus"`
- `test_unknown_provider_falls_back_to_claude` → rename, assert `== "nexus"`
- `test_unknown_provider_falls_back_to_claude` (executor) → mock `NexusExecutor` instead of `CLIExecutor`
- `test_none_provider_falls_back_to_claude` (executor) → mock `NexusExecutor` instead of `CLIExecutor`
- `test_unknown_provider_uses_claude_adapter` → mock `NexusAGUIAdapter` instead of `AGUIAdapter`

- [ ] **Step 3: Run all tests**

Run: `cd ~/Projects/agent-nexus_feature-dev && python3 -m pytest tests/providers/nexus/ tests/unit/test_provider_dispatcher.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add src/providers/dispatcher.py tests/unit/test_provider_dispatcher.py tests/providers/nexus/test_dispatcher.py
git commit -m "feat: switch default chat provider to nexus

Default provider changes from 'claude' to 'nexus'. Override with
AGENT_NEXUS_DEFAULT_PROVIDER=claude env var, ?provider=claude query
param, or /switch claude command."
```

---

### Task 8: End-to-end verification

- [ ] **Step 1: Run full import chain test**

```bash
cd ~/Projects/agent-nexus_feature-dev
python3 -c "
# 1. Nexus engine imports
from src.nexus.agent.loop import AgentLoop
from src.nexus.agent.skills import SkillsLoader
from src.nexus.config.loader import load_config

# 2. Provider imports
from src.providers.nexus import NexusExecutor, NexusAGUIAdapter
from src.providers.nexus.event_schema import TextDeltaEvent, ToolStartEvent

# 3. Dispatcher integration
from src.providers.dispatcher import normalize_provider, create_adapter
assert normalize_provider(None) == 'nexus'
assert normalize_provider('claude') == 'claude'
adapter = create_adapter('nexus')
assert type(adapter).__name__ == 'NexusAGUIAdapter'

print('All imports and assertions OK')
"
```
Expected: `All imports and assertions OK`

- [ ] **Step 2: Run all nexus tests**

Run: `cd ~/Projects/agent-nexus_feature-dev && python3 -m pytest tests/providers/nexus/ -v`
Expected: All PASS

- [ ] **Step 3: Run full dispatcher tests**

Run: `cd ~/Projects/agent-nexus_feature-dev && python3 -m pytest tests/unit/test_provider_dispatcher.py -v`
Expected: All PASS

- [ ] **Step 4: Verify skill injection**

```bash
cd ~/Projects/agent-nexus_feature-dev
python3 -c "
from pathlib import Path
from src.nexus.agent.skills import SkillsLoader
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
assert normalize_provider('nexus') == 'nexus', 'Explicit nexus broken'
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
