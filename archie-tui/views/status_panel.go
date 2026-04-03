package views

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/lipgloss"
)

// StatusPanel displays platform status info (agents, models, health).
type StatusPanel struct {
	Visible bool
	Width   int
	Hub     string
	Model   string
	Agents  *AgentStats
	Models  []ModelInfo
}

type AgentStats struct {
	Active int
	Total  int
}

type ModelInfo struct {
	Name string
	Size string
}

func NewStatusPanel() *StatusPanel {
	return &StatusPanel{}
}

func (p *StatusPanel) Render() string {
	if !p.Visible {
		return ""
	}

	cyan := lipgloss.NewStyle().Foreground(lipgloss.Color("#00e5ff"))
	green := lipgloss.NewStyle().Foreground(lipgloss.Color("#10b981"))
	dim := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280"))
	yellow := lipgloss.NewStyle().Foreground(lipgloss.Color("#fbbf24"))

	var lines []string

	// Hub status
	if p.Hub == "connected" {
		lines = append(lines, green.Bold(true).Render("●")+" "+cyan.Render("HUB")+" "+green.Render("ONLINE"))
	} else {
		lines = append(lines, dim.Render("○")+" "+cyan.Render("HUB")+" "+dim.Render("OFFLINE"))
	}

	// Model
	modelName := p.Model
	if modelName == "" {
		modelName = "—"
	}
	lines = append(lines, dim.Render("Model: ")+cyan.Render(modelName))

	// Agents
	if p.Agents != nil {
		lines = append(lines, dim.Render("Agents: ")+yellow.Render(fmt.Sprintf("%d", p.Agents.Active))+dim.Render(fmt.Sprintf("/%d active", p.Agents.Total)))
	} else {
		lines = append(lines, dim.Render("Agents: —"))
	}

	// Loaded models
	if len(p.Models) > 0 {
		lines = append(lines, "")
		lines = append(lines, cyan.Bold(true).Render("Loaded Models"))
		for _, m := range p.Models {
			size := ""
			if m.Size != "" {
				size = dim.Render(" (" + m.Size + ")")
			}
			lines = append(lines, dim.Render("  • ")+lipgloss.NewStyle().Foreground(lipgloss.Color("#e5e7eb")).Render(m.Name)+size)
		}
	}

	content := strings.Join(lines, "\n")
	return LCARSPanel(content, "STATUS", lipgloss.Color("#8b5cf6"), p.Width)
}
