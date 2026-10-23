# CLAUDE.md

This repository's agent guidance lives in `AGENTS.md`, shared by every
coding agent (Claude Code, Codex, Cursor, etc.) so there is one source of
truth. It is imported here so Claude Code loads it too:

@AGENTS.md

## Claude Code specifics

- **Skills live in `.agents/skills/`**, not `.claude/skills/`. When a
  request matches a skill's purpose, read that skill's
  `.agents/skills/<dir>/SKILL.md` and follow it. Start a full pipeline run
  with `.agents/skills/pipeline_orchestrator/SKILL.md`. AGENTS.md's
  "Skills" table lists every orchestrator skill and the procedure skill it
  follows.
- **Dispatching a skill** in an orchestrator skill means: use the Agent
  tool to give a subagent the skill's `SKILL.md` path and its inputs, or
  follow it inline yourself.
- Don't add guidance here that other tools would also need. Put it in
  `AGENTS.md`, and keep this file to Claude Code-specific notes.
