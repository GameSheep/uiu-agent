- Communicates in Chinese (writes in Simplified Chinese). Confidence: 0.85
- Prefers agent-to-agent delegation architecture — their custom agent should orchestrate external coding agents (Claude Code, Codex, OpenCode, etc.) via CLI invocation, not just act alone. Confidence: 0.80
- Prefers CLI-based subprocess integration over API-based integration for wrapping external tools. Confidence: 0.65
- Develops on Windows (paths use `E:\`, `.cmd` wrappers, GBK console encoding constraints). Confidence: 0.85
: 0.85
- Expects agent to reason about execution environment before running commands — UI automation should run in independent system terminal, not IDE built-in terminal (IDE steals focus and breaks window-management scripts). Prefers thinking ahead over trial-and-error. Confidence: 0.70
