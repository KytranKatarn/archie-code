package views

import (
	"fmt"

	"github.com/charmbracelet/lipgloss"
)

type StatusBar struct {
	HubStatus string
	Branch    string
	Model     string
	Width     int
}

func NewStatusBar() *StatusBar {
	return &StatusBar{HubStatus: "disconnected"}
}

func (s *StatusBar) Render() string {
	bg := lipgloss.NewStyle().
		Background(lipgloss.Color("#1a1a2e")).
		Foreground(lipgloss.Color("#e5e7eb")).
		Width(s.Width).
		Padding(0, 1)

	green := lipgloss.NewStyle().Foreground(lipgloss.Color("#10b981")).Bold(true)
	dim := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280"))
	cyan := lipgloss.NewStyle().Foreground(lipgloss.Color("#00e5ff"))

	var hubIndicator string
	switch s.HubStatus {
	case "connected":
		hubIndicator = green.Render("HUB")
	case "offline":
		hubIndicator = dim.Render("HUB:OFF")
	default:
		hubIndicator = dim.Render("LOCAL")
	}

	var parts []string
	parts = append(parts, hubIndicator)
	if s.Branch != "" {
		parts = append(parts, cyan.Render(fmt.Sprintf("git:%s", s.Branch)))
	}
	if s.Model != "" {
		parts = append(parts, dim.Render(s.Model))
	}

	content := ""
	for i, p := range parts {
		if i > 0 {
			content += dim.Render(" | ")
		}
		content += p
	}

	return bg.Render(content)
}

// RenderContent returns the status bar content without background styling.
func (s *StatusBar) RenderContent() string {
	green := lipgloss.NewStyle().Foreground(lipgloss.Color("#10b981")).Bold(true)
	dim := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280"))
	cyan := lipgloss.NewStyle().Foreground(lipgloss.Color("#00e5ff"))

	var hubIndicator string
	switch s.HubStatus {
	case "connected":
		hubIndicator = green.Render("HUB")
	case "offline":
		hubIndicator = dim.Render("HUB:OFF")
	default:
		hubIndicator = dim.Render("LOCAL")
	}

	var parts []string
	parts = append(parts, hubIndicator)
	if s.Branch != "" {
		parts = append(parts, cyan.Render(fmt.Sprintf("git:%s", s.Branch)))
	}
	if s.Model != "" {
		parts = append(parts, dim.Render(s.Model))
	}

	content := ""
	for i, p := range parts {
		if i > 0 {
			content += dim.Render(" | ")
		}
		content += p
	}

	return content
}
