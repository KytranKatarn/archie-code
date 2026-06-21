package views

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/lipgloss"
)

// RepoItem is a selectable workspace the engine can operate on.
type RepoItem struct {
	Name  string
	Path  string
	Label string
}

// FileExplorer is a toggleable repo picker + file tree + read pane (#4264 PR 2).
// Mode "repo": pick a workspace. Mode "tree": browse files in the selected repo;
// opening a file shows a bounded preview in the read pane.
type FileExplorer struct {
	Visible     bool
	Mode        string // "repo" | "tree"
	Repos       []RepoItem
	CurrentRepo string // resolved path of the selected repo (root for ws calls)
	CurrentName string
	Files       []string
	Selected    int
	Truncated   bool
	OpenPath    string
	OpenContent string
	Width       int
	Height      int
}

func NewFileExplorer() *FileExplorer {
	return &FileExplorer{Mode: "repo"}
}

// MaxIndex is the highest selectable row for the current mode.
func (e *FileExplorer) MaxIndex() int {
	if e.Mode == "repo" {
		return len(e.Repos) - 1
	}
	return len(e.Files) - 1
}

func (e *FileExplorer) visibleRows() int {
	r := e.Height - 10
	if r < 5 {
		r = 5
	}
	return r
}

// windowBounds returns the [start,end) slice of an n-item list to render so the
// selected index stays visible within rows lines.
func windowBounds(sel, n, rows int) (int, int) {
	if n <= rows {
		return 0, n
	}
	start := sel - rows/2
	if start < 0 {
		start = 0
	}
	end := start + rows
	if end > n {
		end = n
		start = end - rows
	}
	if start < 0 {
		start = 0
	}
	return start, end
}

func (e *FileExplorer) Render() string {
	if !e.Visible {
		return ""
	}
	accent := lipgloss.NewStyle().Foreground(lipgloss.Color("#00e5ff")).Bold(true)
	text := lipgloss.NewStyle().Foreground(lipgloss.Color("#e5e7eb"))
	dim := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280"))
	sel := lipgloss.NewStyle().
		Background(lipgloss.Color("#1a1a2e")).
		Foreground(lipgloss.Color("#00e5ff")).
		Bold(true)

	var lines []string
	if e.Mode == "repo" {
		lines = append(lines, accent.Render("  Select a repo"))
		lines = append(lines, dim.Render("  ↑/↓ move · Enter open · Ctrl+E close"))
		lines = append(lines, "")
		for i, r := range e.Repos {
			prefix, style := "  ", text
			if i == e.Selected {
				prefix, style = "> ", sel
			}
			lines = append(lines, style.Render(fmt.Sprintf("%s%s  (%s)", prefix, r.Name, r.Label)))
		}
		if len(e.Repos) == 0 {
			lines = append(lines, dim.Render("  (loading repos…)"))
		}
	} else {
		lines = append(lines, accent.Render("  "+e.CurrentName))
		lines = append(lines, dim.Render("  ↑/↓ move · Enter open file · Bksp repos · Ctrl+E close"))
		lines = append(lines, "")
		start, end := windowBounds(e.Selected, len(e.Files), e.visibleRows())
		for i := start; i < end; i++ {
			prefix, style := "  ", text
			if i == e.Selected {
				prefix, style = "> ", sel
			}
			lines = append(lines, style.Render(prefix+e.Files[i]))
		}
		if len(e.Files) == 0 {
			lines = append(lines, dim.Render("  (empty)"))
		}
		if e.Truncated {
			lines = append(lines, dim.Render(fmt.Sprintf("  …(showing first %d files)", len(e.Files))))
		}
	}

	// Read pane — bounded preview of the opened file.
	if e.OpenPath != "" {
		lines = append(lines, "")
		lines = append(lines, accent.Render("  ▸ "+e.OpenPath))
		body := strings.Split(e.OpenContent, "\n")
		const maxRows = 20
		shown := body
		if len(body) > maxRows {
			shown = body[:maxRows]
		}
		for _, l := range shown {
			lines = append(lines, text.Render("  "+l))
		}
		if len(body) > maxRows {
			lines = append(lines, dim.Render(fmt.Sprintf("  …(%d more lines)", len(body)-maxRows)))
		}
	}

	border := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("#00e5ff")).
		Padding(1)
	if e.Width > 4 {
		border = border.Width(e.Width - 4)
	}
	return border.Render(strings.Join(lines, "\n"))
}
