---
name: refactor
description: Refactor code for clarity, performance, or maintainability
arguments:
  - name: target
    description: File or function to refactor
    required: true
  - name: goal
    description: What to improve (clarity, performance, DRY, etc.)
    required: false
---

Refactor the specified code.

1. Read the target code
2. Identify improvement opportunities based on the goal
3. Apply refactoring while preserving behavior
4. Run existing tests to verify nothing broke
5. Summarize changes made
