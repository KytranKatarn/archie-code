package views

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/lipgloss"
)

type SkillItem struct {
	Name        string
	Description string
}

type SkillPicker struct {
	Skills   []SkillItem
	Selected int
	Visible  bool
	Filter   string
	Width    int
	Height   int
}

func NewSkillPicker() *SkillPicker {
	return &SkillPicker{}
}

func (sp *SkillPicker) Filtered() []SkillItem {
	if sp.Filter == "" {
		return sp.Skills
	}
	var filtered []SkillItem
	lower := strings.ToLower(sp.Filter)
	for _, s := range sp.Skills {
		if strings.Contains(strings.ToLower(s.Name), lower) ||
			strings.Contains(strings.ToLower(s.Description), lower) {
			filtered = append(filtered, s)
		}
	}
	return filtered
}

func (sp *SkillPicker) Render() string {
	if !sp.Visible {
		return ""
	}

	purple := lipgloss.NewStyle().Foreground(lipgloss.Color("#8b5cf6")).Bold(true)
	text := lipgloss.NewStyle().Foreground(lipgloss.Color("#e5e7eb"))
	dim := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280"))
	sel := lipgloss.NewStyle().
		Background(lipgloss.Color("#1a1a2e")).
		Foreground(lipgloss.Color("#00e5ff")).
		Bold(true)

	var lines []string
	lines = append(lines, purple.Render("  Skills"))
	lines = append(lines, dim.Render("  Type to filter, Enter to select, Esc to close"))
	lines = append(lines, "")

	filtered := sp.Filtered()
	for i, skill := range filtered {
		prefix := "  "
		style := text
		if i == sp.Selected {
			prefix = "> "
			style = sel
		}
		line := fmt.Sprintf("%s/%s - %s", prefix, skill.Name, skill.Description)
		lines = append(lines, style.Render(line))
	}

	if len(filtered) == 0 {
		lines = append(lines, dim.Render("  No matching skills"))
	}

	border := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("#8b5cf6")).
		Padding(1)

	if sp.Width > 4 {
		border = border.Width(sp.Width - 4)
	}

	return border.Render(strings.Join(lines, "\n"))
}
