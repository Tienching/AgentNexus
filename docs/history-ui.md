# Nexus History UI

This note documents the current frontend presentation for the history browser.

## User-facing model

- **Chat** is the default live workspace.
- **History** is a read-only browser for previous CLI sessions.
- History no longer uses the old "Browse History" wording in the primary UI.

## History layout

- History sessions are grouped and sorted by **Provider → Alias**.
- Within each alias group, sessions are shown newest-first.
- The session header surfaces the provider/alias pairing so users can see where a history item came from.

## Actions

- **Open in Chat** keeps the session in read-only mode for inspection.
- **Continue in Chat** creates a live chat session from the selected history entry.

## Compatibility

- Legacy promote / fetch flows may still exist behind compatibility helpers, but the primary UI stays read-only for history.
