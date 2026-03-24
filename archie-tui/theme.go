package main

import "github.com/charmbracelet/lipgloss"

var (
	ColorCyan   = lipgloss.Color("#00e5ff")
	ColorPurple = lipgloss.Color("#8b5cf6")
	ColorPink   = lipgloss.Color("#f472b6")
	ColorYellow = lipgloss.Color("#fbbf24")
	ColorGreen  = lipgloss.Color("#10b981")
	ColorRed    = lipgloss.Color("#ef4444")
	ColorOrange = lipgloss.Color("#f97316")
	ColorDim    = lipgloss.Color("#6b7280")
	ColorBg     = lipgloss.Color("#0a0a0f")
	ColorText   = lipgloss.Color("#e5e7eb")

	TitleStyle           = lipgloss.NewStyle().Bold(true).Foreground(ColorCyan).Padding(0, 1)
	UserMsgStyle         = lipgloss.NewStyle().Foreground(ColorText)
	AssistantMsgStyle    = lipgloss.NewStyle().Foreground(ColorCyan)
	SystemMsgStyle       = lipgloss.NewStyle().Foreground(ColorDim).Italic(true)
	StatusBarStyle       = lipgloss.NewStyle().Background(lipgloss.Color("#1a1a2e")).Foreground(ColorText).Padding(0, 1)
	HubConnectedStyle    = lipgloss.NewStyle().Foreground(ColorGreen).Bold(true)
	HubDisconnectedStyle = lipgloss.NewStyle().Foreground(ColorDim)
	SkillNameStyle       = lipgloss.NewStyle().Foreground(ColorPurple).Bold(true)
	InputPromptStyle     = lipgloss.NewStyle().Foreground(ColorCyan).Bold(true)
	ErrorStyle           = lipgloss.NewStyle().Foreground(ColorRed)
	BannerStyle          = lipgloss.NewStyle().Foreground(ColorCyan).Bold(true)
)
