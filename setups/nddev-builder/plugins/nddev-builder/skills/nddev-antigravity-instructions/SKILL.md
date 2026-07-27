---
name: nddev-antigravity-instructions
description: Author or check Antigravity CLI instructions, rules, and Agent Skills with progressive disclosure.
---

# Antigravity instructions, rules, and Agent Skills

Use this skill for `AGENTS.md`, `GEMINI.md`, plugin rules, and skill content.

## Native paths

- Workspace instructions: `AGENTS.md` and `GEMINI.md`
- Global instruction/rules file: `~/.gemini/GEMINI.md`
- Workspace rules: `.agents/rules/`
- Plugin rules: `<plugin-root>/rules/`
- Workspace skills: `.agents/skills/<skill-folder>/SKILL.md`
- Global skills: `~/.gemini/config/skills/<skill-folder>/SKILL.md`
- Plugin skills: `<plugin-root>/skills/<skill-folder>/SKILL.md`

## Progressive disclosure

- Entry skills route.
- Focused skills carry task-specific instructions.
- References hold stable path/schema guidance.
- Volatile pins, versions, digests, and current setup lists stay in code-owned
  files listed by `../nddev-builder/references/source-owners.md`.

## Check

Run:

```bash
python3 cli-tools/validate_public_contracts.py
```
