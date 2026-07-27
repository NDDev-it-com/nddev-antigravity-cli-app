# Native Antigravity CLI surfaces

Use only documented Antigravity CLI surfaces. Do not emulate a plugin
marketplace, MCP store, package manager, or runtime path that Antigravity CLI
does not expose.

## Settings and profiles

- Persistent CLI settings: `~/.gemini/antigravity-cli/settings.json`
- Keybindings: `~/.gemini/antigravity-cli/keybindings.json`

The NDDev setup manager owns only the setting keys declared in
`config/nddev-contract.json` and rendered by `cli-tools/nddev_antigravity_cli.py`.
Exact profile payloads live under `profiles/`.

## Plugins

- CLI-staged plugin root:
  `~/.gemini/antigravity-cli/plugins/<plugin_name>/`
- Required plugin manifest:
  `~/.gemini/antigravity-cli/plugins/<plugin_name>/plugin.json`
- Plugin manifest shape is an object with `$schema`, `name`, and optional
  `description`; `name` is the native plugin id.

NDDev manages only the `nddev-builder` plugin staged through the setup target.

## Skills and instructions

- Workspace Agent Skills:
  `<workspace-root>/.agents/skills/<skill-folder>/SKILL.md`
- Global Agent Skills:
  `~/.gemini/config/skills/<skill-folder>/SKILL.md`
- Plugin Agent Skills:
  `<plugin-root>/skills/<skill-folder>/SKILL.md`
- Workspace instruction files:
  `AGENTS.md` and `GEMINI.md`
- Global instruction/rules file:
  `~/.gemini/GEMINI.md`
- Workspace rules directory:
  `.agents/rules/`
- Plugin rules directory:
  `<plugin-root>/rules/`

Agent Skill frontmatter must include a useful `description`; `name` is used
when a stable routed identity is needed.

## Agents and subagents

- Workspace agents:
  `.agents/agents/<name>.md` or `.agents/agents/<name>/agent.md`
- Global agents:
  `~/.gemini/config/agents/<name>.md` or
  `~/.gemini/config/agents/<name>/agent.md`
- Plugin agents:
  `<plugin-root>/agents/<name>.md`

Use native Markdown agent frontmatter. Do not invent legacy fields.

## Hooks

- Workspace hooks: `.agents/hooks.json`
- Global hooks: `~/.gemini/config/hooks.json`
- Plugin hooks: `<plugin-root>/hooks.json`

The default NDDev builder setup does not install hooks.

## MCP

- Global MCP config: `~/.gemini/config/mcp_config.json`
- Workspace MCP config: `.agents/mcp_config.json`
- Config root: `mcpServers`
- Local transport: `command`
- Remote transport: `serverUrl`

The default NDDev builder setup does not install MCP servers or secrets.
