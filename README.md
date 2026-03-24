# A.R.C.H.I.E. Code CLI

**AI-powered terminal development tool with LCARS-themed interface.**

ARCHIE Code CLI is a local-first coding assistant that runs on your machine with Ollama. Optional hub connectivity unlocks 107 AI agents, 18,000+ knowledge base entries, and fleet-wide model orchestration.

## Install

```bash
curl -sSL https://raw.githubusercontent.com/KytranKatarn/archie-code/main/install.sh | bash
```

Or manually:

```bash
# Python engine
pip install archie-engine

# Go TUI (build from source)
cd archie-tui && go build -o archie-code .
```

## Quick Start

```bash
# 1. Start the engine daemon
python -m archie_engine

# 2. Launch the TUI (in another terminal)
archie-code
```

## Features

- **6 Built-in Skills** — `/commit`, `/review`, `/explain`, `/debug`, `/refactor`, `/test`
- **Local-First** — Runs entirely on your machine with Ollama
- **Hub Connectivity** — Optional connection to ARCHIE platform for 107 agents + 18K KB
- **Claude Collaboration** — MCP server exposes tools to Claude CLI
- **LCARS Theme** — Sci-fi terminal interface with Bubble Tea
- **Custom Skills** — Create your own slash commands as markdown files

## Architecture

```
┌─────────────┐     WebSocket      ┌──────────────────┐
│  Go TUI     │ ◄──────────────► │  Python Engine    │
│  (Bubble Tea)│     ws://9090     │  (asyncio daemon) │
└─────────────┘                    │                    │
                                   │  ├─ Intent Parser  │
                                   │  ├─ Command Router │
┌─────────────┐                    │  ├─ Tool Registry  │
│  Claude CLI │ ◄── MCP stdio ──► │  ├─ Skill System   │
└─────────────┘                    │  ├─ Session (SQLite)│
                                   │  └─ Hub Connector  │
                                   └────────┬───────────┘
                                            │ REST API
                                   ┌────────▼───────────┐
                                   │  ARCHIE Hub        │
                                   │  (optional)        │
                                   │  107 agents, 18K KB │
                                   └────────────────────┘
```

## Distribution Tiers

| Feature | Community | Node | Hub |
|---------|-----------|------|-----|
| Local inference (Ollama) | Yes | Yes | Yes |
| 6 community skills | Yes | Yes | Yes |
| Custom skills | Yes | Yes | Yes |
| Rule-based intent parsing | Yes | Yes | Yes |
| Hub agent orchestration | - | Yes | Yes |
| Knowledge base RAG | - | Yes | Yes |
| Fleet model coordination | - | Yes | Yes |
| Starbase visibility | - | - | Yes |
| Full 107-agent roster | - | - | Yes |

## Comparison

| | ARCHIE Code | Claude Code | Cursor | Copilot CLI |
|---|---|---|---|---|
| Local-first | Yes | No | No | No |
| Open source | Apache 2.0 | No | No | No |
| Custom skills | Markdown | Plugins | Rules | - |
| Self-hosted hub | Yes | - | - | - |
| Multi-agent | 107 agents | 1 | 1 | 1 |
| Terminal TUI | LCARS themed | Yes | IDE | Yes |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for skill authoring guide.

## License

Apache 2.0 — see [LICENSE](LICENSE)

Built by [Kytran Empowerment Inc.](https://kytranempowerment.com)
