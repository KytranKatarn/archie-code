---
name: commit
description: Create a git commit with an auto-generated or provided message
arguments:
  - name: message
    description: Optional commit message (auto-generated if omitted)
    required: false
---

Create a git commit for the current staged changes.

1. Run `git diff --staged` to review what will be committed
2. If no message was provided, analyze the diff and write a concise commit message
3. Run `git commit -m "<message>"`
4. Report the commit hash and summary
