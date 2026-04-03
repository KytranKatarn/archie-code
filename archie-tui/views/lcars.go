package views

import (
	"strings"

	"github.com/charmbracelet/lipgloss"
)

var (
	LCARSCyan   = lipgloss.Color("#00e5ff")
	LCARSDim    = lipgloss.Color("#1a1a2e")
	LCARSText   = lipgloss.Color("#e5e7eb")
	LCARSPurple = lipgloss.Color("#8b5cf6")
)

// LCARSPanel renders content inside an LCARS-styled panel with elbow corners.
// accent is the panel's accent color, title is shown in the header bar.
func LCARSPanel(content string, title string, accent lipgloss.Color, width int) string {
	if width < 20 {
		return content
	}

	accentStyle := lipgloss.NewStyle().Foreground(accent)
	titleStyle := lipgloss.NewStyle().Foreground(accent).Bold(true)

	innerWidth := width - 4 // 2 border chars + 2 padding spaces each side

	// Top bar: elbow + colored segment + title
	titleText := titleStyle.Render(" " + title + " ")
	titleLen := lipgloss.Width(titleText)
	segmentLen := innerWidth - titleLen
	if segmentLen < 0 {
		segmentLen = 0
	}
	segment := accentStyle.Render(strings.Repeat("━", segmentLen))

	topBar := accentStyle.Render("╭━") + segment + titleText + accentStyle.Render("━╮")

	// Bottom bar: elbow corners
	bottomBar := accentStyle.Render("╰━") + accentStyle.Render(strings.Repeat("━", innerWidth)) + accentStyle.Render("━╯")

	// Wrap content lines with side borders
	contentLines := strings.Split(content, "\n")
	var framedLines []string
	framedLines = append(framedLines, topBar)

	for _, line := range contentLines {
		lineWidth := lipgloss.Width(line)
		padding := ""
		if lineWidth < innerWidth {
			padding = strings.Repeat(" ", innerWidth-lineWidth)
		}
		framedLines = append(framedLines, accentStyle.Render("│")+" "+line+padding+" "+accentStyle.Render("│"))
	}

	framedLines = append(framedLines, bottomBar)

	return strings.Join(framedLines, "\n")
}

// LCARSHeader renders a standalone LCARS header bar with colored segment and title.
func LCARSHeader(title string, accent lipgloss.Color, width int) string {
	accentStyle := lipgloss.NewStyle().Foreground(accent).Bold(true)
	labelStyle := lipgloss.NewStyle().Background(accent).Foreground(lipgloss.Color("#0a0a0f"))

	titleText := labelStyle.Render(" " + title + " ")
	titleLen := lipgloss.Width(titleText)
	segLen := width - titleLen - 4
	if segLen < 0 {
		segLen = 0
	}

	return accentStyle.Render("╭━") + accentStyle.Render(strings.Repeat("━", segLen)) + titleText + accentStyle.Render("━╮")
}

// LCARSStatusBar renders a bottom status bar with LCARS elbow corners.
func LCARSStatusBar(content string, accent lipgloss.Color, width int) string {
	accentStyle := lipgloss.NewStyle().Foreground(accent)

	contentWidth := lipgloss.Width(content)
	padLen := width - contentWidth - 4
	if padLen < 0 {
		padLen = 0
	}

	return accentStyle.Render("╰━") + " " + content + strings.Repeat(" ", padLen) + " " + accentStyle.Render("━╯")
}
