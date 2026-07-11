package main

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
)

// Palette is the command palette (Task 5): the agent's skills/commands, opened
// with "/", substring-filtered, Enter sends the selected command. Populated from
// the engine's list_skills reply. Distinct from SkillPicker (legacy Tab overlay).
type Palette struct {
	cmds     []string
	filter   string
	Open     bool
	Selected int
}

func NewPalette(cmds []string) *Palette { return &Palette{cmds: cmds} }

// SetCommands replaces the palette's command list (e.g. from list_skills).
func (p *Palette) SetCommands(cmds []string) { p.cmds = cmds }

// SetFilter sets the substring filter and resets the selection.
func (p *Palette) SetFilter(s string) {
	p.filter = s
	p.Selected = 0
}

// Filter returns the current filter string.
func (p *Palette) Filter() string { return p.filter }

// Visible returns the commands matching the current substring filter
// (case-insensitive). An empty filter returns all commands.
func (p *Palette) Visible() []string {
	if p.filter == "" {
		return p.cmds
	}
	var out []string
	f := strings.ToLower(p.filter)
	for _, c := range p.cmds {
		if strings.Contains(strings.ToLower(c), f) {
			out = append(out, c)
		}
	}
	return out
}

// Render draws the palette overlay (Task 5): the filtered command list with the
// current selection highlighted. Not covered by TestPalette (pure list logic is).
func (p *Palette) Render(width int) string {
	if !p.Open {
		return ""
	}
	cyan := lipgloss.NewStyle().Foreground(lipgloss.Color("#00e5ff")).Bold(true)
	dim := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280"))
	sel := lipgloss.NewStyle().Background(lipgloss.Color("#1a1a2e")).Foreground(lipgloss.Color("#00e5ff")).Bold(true)
	text := lipgloss.NewStyle().Foreground(lipgloss.Color("#e5e7eb"))

	var lines []string
	lines = append(lines, cyan.Render("  Commands  /"+p.filter))
	lines = append(lines, dim.Render("  Up/Down + Enter to run \u00b7 Esc closes"))
	vis := p.Visible()
	for i, c := range vis {
		st, prefix := text, "  "
		if i == p.Selected {
			st, prefix = sel, "> "
		}
		lines = append(lines, st.Render(prefix+"/"+c))
	}
	if len(vis) == 0 {
		lines = append(lines, dim.Render("  (no match)"))
	}
	border := lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).BorderForeground(lipgloss.Color("#00e5ff")).Padding(1)
	if width > 4 {
		border = border.Width(width - 4)
	}
	return border.Render(strings.Join(lines, "\n"))
}
