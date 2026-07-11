package views

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/lipgloss"
)

// ToolItem is one entry in the tool palette (Task 5) — the engine's MCP tools,
// fetched via a list_tools frame.
type ToolItem struct {
	Name        string
	Description string
}

// ToolPalette is a lightweight overlay listing the engine's tools. It mirrors
// SkillPicker: toggle with Ctrl+T, Up/Down to move, Enter inserts the tool name.
type ToolPalette struct {
	Tools    []ToolItem
	Selected int
	Visible  bool
	Width    int
	Height   int
}

func NewToolPalette() *ToolPalette {
	return &ToolPalette{}
}

func (tp *ToolPalette) Render() string {
	if !tp.Visible {
		return ""
	}

	cyan := lipgloss.NewStyle().Foreground(lipgloss.Color("#00e5ff")).Bold(true)
	text := lipgloss.NewStyle().Foreground(lipgloss.Color("#e5e7eb"))
	dim := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280"))
	sel := lipgloss.NewStyle().
		Background(lipgloss.Color("#1a1a2e")).
		Foreground(lipgloss.Color("#00e5ff")).
		Bold(true)

	var lines []string
	lines = append(lines, cyan.Render("  Tools"))
	lines = append(lines, dim.Render("  Up/Down + Enter to insert · Ctrl+B builds with the current input · Esc closes"))
	lines = append(lines, "")

	for i, tool := range tp.Tools {
		prefix := "  "
		style := text
		if i == tp.Selected {
			prefix = "> "
			style = sel
		}
		lines = append(lines, style.Render(fmt.Sprintf("%s%s - %s", prefix, tool.Name, tool.Description)))
	}
	if len(tp.Tools) == 0 {
		lines = append(lines, dim.Render("  No tools available"))
	}

	border := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("#00e5ff")).
		Padding(1)
	if tp.Width > 4 {
		border = border.Width(tp.Width - 4)
	}
	return border.Render(strings.Join(lines, "\n"))
}
