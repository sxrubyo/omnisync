---
description: Omni Agent runtime bridge selector for Claude Code, Codex, Gemini, and OpenCode
---

Omni Agent router. Arguments provided: "$ARGUMENTS"

Load the Omni skill first:

```text
skill({ name: "omni-sync" })
```

Then prefer:
- `omni agent`
- `omni chat "$ARGUMENTS"`
- `omni guide`
