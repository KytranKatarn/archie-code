package views

import (
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/lipgloss"
)

// CompanionState represents the current expression.
type CompanionState int

const (
	StateIdle CompanionState = iota
	StateThinking
	StateHappy
	StateConcerned
	StateSurprised
	StateFocused
	StateSleeping
)

// CompanionView is the ASCII companion widget.
type CompanionView struct {
	State      CompanionState
	StatusText string
	blinking   bool
	swayRight  bool
	lastInput  time.Time
	Width      int
	Height     int
}

// NewCompanionView creates a companion in idle state.
func NewCompanionView() *CompanionView {
	return &CompanionView{
		State:      StateIdle,
		StatusText: "✦ ready",
		lastInput:  time.Now(),
	}
}

// BlinkTickMsg triggers a blink animation frame.
type BlinkTickMsg struct{}

// BlinkEndMsg ends the blink animation frame.
type BlinkEndMsg struct{}

// SwayTickMsg triggers a hair sway animation.
type SwayTickMsg struct{}

// SleepCheckMsg checks if companion should sleep.
type SleepCheckMsg struct{}

// expression returns the eyes and mouth strings for the current state.
func (c *CompanionView) expression() (eyes, mouth string) {
	if c.blinking {
		return "─ ─", "◡"
	}
	switch c.State {
	case StateThinking:
		return "◕ ◕", "─"
	case StateHappy:
		return "◕ ◕", "◠"
	case StateConcerned:
		return "◕ ◕", "╭╮"
	case StateSurprised:
		return "○ ○", "○"
	case StateFocused:
		return "▪ ▪", "─"
	case StateSleeping:
		return "─ ─", "z"
	default: // Idle
		return "◕ ◕", "◡"
	}
}

// Render returns the full companion block as a styled string.
func (c *CompanionView) Render() string {
	if c.Width < 60 {
		return ""
	}

	cyan := lipgloss.NewStyle().Foreground(lipgloss.Color("#00e5ff"))
	dim := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280"))

	eyes, mouth := c.expression()

	// Hair sway: bottom hair shifts 1 char
	bottomLeft := "▓▓"
	bottomRight := "▓▓"
	if c.swayRight {
		bottomLeft = " ▓▓"
		bottomRight = "▓▓"
	}

	face := []string{
		"    ╭───╮    ",
		"   ╱▓▓▓▓▓╲   ",
		"  │▓╭───╮▓│  ",
		fmt.Sprintf("  │▓│%s│▓│  ", eyes),
		fmt.Sprintf("  ╰─│ %s │─╯  ", mouth),
		"   ▓╰───╯▓   ",
		fmt.Sprintf("   %s   %s   ", bottomLeft, bottomRight),
	}

	var lines []string
	for _, line := range face {
		lines = append(lines, cyan.Render(line))
	}
	lines = append(lines, cyan.Bold(true).Render("  A.R.C.H.I.E.  "))
	lines = append(lines, dim.Render(fmt.Sprintf("   %s", c.StatusText)))

	return strings.Join(lines, "\n")
}
