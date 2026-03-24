---
name: test
description: Write or run tests for specified code
arguments:
  - name: target
    description: File or function to test
    required: true
  - name: action
    description: write to create tests, run to execute existing tests
    required: false
---

Work with tests for the specified code.

1. If action is run or not specified, find and run existing tests
2. If action is write, read the target code and write comprehensive tests
3. Cover edge cases, error paths, and expected behavior
4. Report test results with pass/fail counts
