---
name: review
description: Review code changes for bugs, style, and improvements
arguments:
  - name: target
    description: File path or git ref to review (defaults to staged changes)
    required: false
---

Review the code changes for quality issues.

1. If a target file is specified, read it. Otherwise run `git diff` for unstaged or `git diff --staged` for staged changes
2. Check for: bugs, security issues, style problems, performance concerns
3. Provide specific feedback with file and line references
4. Rate overall quality and suggest improvements
