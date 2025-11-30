---
name: openspec
description: This skill provides spec-driven development workflow for Claude Code projects. Use this skill when users request to create proposals, plan changes, add features, or work with specifications. The skill handles project initialization, guides the three-stage OpenSpec workflow (proposal, apply, archive), and integrates with slash commands for explicit workflow control.
---

# OpenSpec Skill

This skill provides a complete spec-driven development workflow for managing changes in Claude Code projects through proposals, implementation tracking, and archival.

## Purpose

OpenSpec enables systematic change management through:
- **Proposal Stage**: Design and specify changes before implementation
- **Apply Stage**: Implement changes following the approved plan
- **Archive Stage**: Archive completed changes and update specifications

## When to Use This Skill

The skill activates automatically when users:
- Request new features or functionality ("add authentication", "implement dark mode")
- Want to create change proposals ("create a proposal for...", "plan a change to...")
- Mention specifications or planning ("I want to spec out...", "help me plan...")
- Use OpenSpec-related keywords: "proposal", "spec", "change" with action verbs

Skip OpenSpec for:
- Bug fixes that restore intended behavior
- Typos, formatting, or comments
- Simple configuration changes
- Tests for existing behavior

## Project Initialization

Check if the project has OpenSpec configured:
- Look for `openspec/` directory in the project root
- Look for `openspec/AGENTS.md` file

### If OpenSpec Exists
Skip initialization and proceed with the workflow using the project's existing configuration.

### If OpenSpec Does NOT Exist
Offer to initialize OpenSpec for the project:

1. Inform the user that OpenSpec will be initialized
2. Run the initialization script:
   ```bash
   python ~/.claude/skills/openspec/scripts/init_openspec.py <project-root-path>
   ```
3. The script will:
   - Create `openspec/` directory structure
   - Copy `AGENTS.md` (detailed workflow instructions)
   - Create `project.md` template (for project conventions)
   - Create empty `specs/` and `changes/` directories
   - Inject OpenSpec instruction block into `CLAUDE.md` (if it exists)

## Three-Stage Workflow

### Stage 1: Creating Proposals

**When to create proposals:**
- Adding new features or functionality
- Making breaking changes (API, schema, architecture)
- Performance optimizations that change behavior
- Security pattern updates

**Workflow:**
1. Review existing state:
   - Run `openspec list` to see active changes
   - Run `openspec list --specs` to see existing capabilities
   - Check for conflicts with pending changes

2. Create proposal directory:
   - Choose unique verb-led change-id (e.g., `add-two-factor-auth`)
   - Create `openspec/changes/<change-id>/` directory

3. Write proposal documents:
   - `proposal.md`: Why, what changes, impact
   - `tasks.md`: Implementation checklist
   - `design.md`: Technical decisions (when needed for complex changes)
   - `specs/<capability>/spec.md`: Specification deltas

4. Validate proposal:
   ```bash
   openspec validate <change-id> --strict
   ```

5. Fix any validation errors before proceeding

**Refer to `openspec/AGENTS.md` for:**
- Detailed proposal structure and format
- Spec delta syntax (ADDED/MODIFIED/REMOVED)
- Scenario formatting requirements
- Validation troubleshooting

### Stage 2: Implementing Changes

**Trigger:** User approves proposal or runs `/openspec:apply <change-id>`

**Workflow:**
1. Read proposal documents to understand scope
2. Work through `tasks.md` sequentially
3. Mark tasks in progress, then completed as work finishes
4. Keep changes minimal and focused
5. Validate implementation matches proposal

**Important:** Only update task checkboxes after confirming completion.

### Stage 3: Archiving Changes

**When to archive:** After change is deployed and verified in production

**Workflow:**
1. Confirm the change-id to archive
2. Run:
   ```bash
   openspec archive <change-id> --yes
   ```
3. The CLI will:
   - Move `changes/<change-id>/` to `changes/archive/YYYY-MM-DD-<change-id>/`
   - Apply spec deltas to `specs/` directory
   - Update capability specifications

4. Validate the archived change:
   ```bash
   openspec validate --strict
   ```

## Slash Commands

OpenSpec provides global slash commands for explicit workflow control:

- `/openspec:proposal` - Create a new change proposal
- `/openspec:apply <change-id>` - Implement an approved change
- `/openspec:archive <change-id>` - Archive a completed change

These commands are available globally from `~/.claude/commands/openspec/` and work in any project.

## Skill vs Slash Commands

**Use the skill (automatic activation):**
- When starting new feature work
- For guided workflow with context
- When you need initialization help

**Use slash commands (explicit invocation):**
- When you want direct control over workflow stages
- To apply or archive specific changes by ID
- For scripted or automated workflows

Both approaches work together - the skill provides context and guidance while slash commands offer precision control.

## Integration with Project

After initialization, the project will have:
- `openspec/AGENTS.md` - Detailed workflow instructions and conventions
- `openspec/project.md` - Project-specific context (fill this out!)
- `openspec/specs/` - Current specifications (truth of what's built)
- `openspec/changes/` - Active proposals (what should change)
- `CLAUDE.md` with OpenSpec instruction block (if file exists)

**Important:** Always refer to the project's `openspec/AGENTS.md` for detailed conventions, validation rules, and troubleshooting guidance.

## Common Operations

### Start a new feature
1. Check if openspec exists, initialize if needed
2. Review `openspec/project.md` for project context
3. Run `openspec list` to check for conflicts
4. Create proposal with change-id
5. Write proposal.md, tasks.md, and spec deltas
6. Validate with `openspec validate <change-id> --strict`

### Implement approved proposal
1. Read proposal.md, design.md (if exists), tasks.md
2. Work through tasks sequentially
3. Update task checkboxes after completion
4. Reference spec deltas for acceptance criteria

### Complete and archive
1. Verify change is deployed
2. Run `openspec archive <change-id> --yes`
3. Validate with `openspec validate --strict`

## Troubleshooting

### "openspec folder not found"
Run the initialization script as described in Project Initialization section.

### "Change must have at least one delta"
Ensure `changes/<id>/specs/<capability>/spec.md` exists with proper delta sections (## ADDED Requirements, etc.).

### "Requirement must have at least one scenario"
Use exact format: `#### Scenario: Name` (four hashtags, colon, space).

### Validation fails
- Run `openspec validate <change-id> --strict` for detailed errors
- Check `openspec/AGENTS.md` for format requirements
- Use `openspec show <change-id> --json --deltas-only` to inspect structure

### Skill doesn't activate
Manually invoke with: "help me with openspec" or use slash commands.

## Resources

**Bundled Assets:**
- `scripts/init_openspec.py` - Project initialization automation
- `assets/templates/AGENTS.md` - Detailed workflow documentation
- `assets/templates/project.md` - Project context template
- `assets/templates/claude_openspec_block.md` - CLAUDE.md instruction block

**Global Commands:**
- `~/.claude/commands/openspec/proposal.md`
- `~/.claude/commands/openspec/apply.md`
- `~/.claude/commands/openspec/archive.md`

For detailed workflow instructions, spec formats, and conventions, always consult the project's `openspec/AGENTS.md` file.
