# NDDev builder rule

When NDDev builder context is active:

- Keep public setup-manager implementation, setup payloads, public contracts,
  and public documentation inside the public module.
- Keep private validation, private memories, private release evidence, and CI
  orchestration outside the public module.
- Use documented Antigravity CLI surfaces only.
- Do not introduce live credentials, generated runtime state, unsupported
  plugin marketplace formats, default hooks, or default MCP servers.
- Point to code-owned facts for versions, pins, profile payloads, setup file
  lists, and launch policy instead of copying them into long-lived prose.
