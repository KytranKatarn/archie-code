# Contributing to ARCHIE Code CLI

## Creating Custom Skills

Skills are markdown files with YAML frontmatter. Place them in `~/.archie/skills/` for personal use, or submit a PR to add community skills.

### Skill File Format

```
---
name: my-skill
description: What this skill does
arguments:
  - name: target
    description: What this argument is
    required: true
---

Instructions for the AI when this skill is invoked.

1. Step one
2. Step two
3. Step three
```

### Skill Directory

| Directory | Source | Priority |
|-----------|--------|----------|
| `archie_engine/skills/community/` | Built-in | Loaded first |
| `~/.archie/skills_cache/skills/` | Hub-synced | Loaded second |
| `~/.archie/skills/` | Custom | Loaded last (overrides) |

### Testing Skills Locally

1. Create your skill file in `~/.archie/skills/`
2. Start the engine: `python -m archie_engine`
3. Launch the TUI: `archie-code`
4. Type `/your-skill-name` to invoke it

### Submitting Community Skills

1. Fork the repository
2. Add your skill to `archie_engine/skills/community/`
3. Ensure it has clear frontmatter (name, description, arguments)
4. Submit a Pull Request

### Guidelines

- Keep skill prompts concise and actionable
- Use numbered steps for multi-step workflows
- Declare all arguments in frontmatter
- Set `required: true` only for essential arguments

## Reporting Issues

Open an issue on GitHub with:
- ARCHIE Engine version (`python -m archie_engine --version`)
- TUI version (`archie-code --version`)
- Steps to reproduce
- Expected vs actual behavior

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
