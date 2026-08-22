package main

import (
	"fmt"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// SkillBridge is the PLATFORM skill palette (#5333), opened with Ctrl+K.
//
// Deliberately distinct from Palette ("/"), which lists the ENGINE's own local
// skills. This one lists the hub's invokable-skills registry -- known-tool
// delegates plus every LLM capability in CAPABILITY_DEPARTMENT_MAP -- so the TUI
// can fire the same work Claude fires, routed through DHQ and attributed to
// delegation_source='tui'. Two different registries, two different overlays;
// merging them would hide which side of the mesh a selection actually runs on.
//
// Pure list/filter/selection state plus a render. It holds no client and sends
// nothing: model.go owns the transport, which keeps every rule below unit-testable.
type SkillBridge struct {
	skills   []PlatformSkill
	filter   string
	Open     bool
	Selected int

	// Requested guards against re-requesting the registry on every open.
	Requested bool
	// Loaded is true once a reply arrived -- including an EMPTY one, so an
	// genuinely empty registry renders "(none)" instead of a forever "Loading".
	Loaded bool
	// Status is the one-line result of the last invocation (or the error).
	Status string
	// LastTaskID is the delegated task id, for the status poll.
	LastTaskID int
}

// dedot strips the dots from a branded agent name so "forge" matches "F.O.R.G.E.".
func dedot(s string) string { return strings.ReplaceAll(s, ".", "") }

func NewSkillBridge() *SkillBridge { return &SkillBridge{} }

// SetSkills replaces the registry and clamps the selection.
func (s *SkillBridge) SetSkills(sk []PlatformSkill) {
	s.skills = sk
	s.Loaded = true
	s.clamp()
}

// SetFilter sets the substring filter and resets the selection to the top.
func (s *SkillBridge) SetFilter(f string) {
	s.filter = f
	s.Selected = 0
}

func (s *SkillBridge) Filter() string { return s.filter }

// Visible returns the skills matching the filter (case-insensitive), matched
// across capability AND department so "engineering" finds F.O.R.G.E.'s work.
func (s *SkillBridge) Visible() []PlatformSkill {
	if s.filter == "" {
		return s.skills
	}
	f := strings.ToLower(s.filter)
	// Agent names are DOTTED (F.O.R.G.E., C.O.D.E.X.) and a human types "forge",
	// so the director is matched with dots stripped from BOTH sides. Without this
	// the filter silently returns nothing while the row visibly shows that
	// director -- the same trap as .claude/rules/database.md, where ILIKE
	// '%HAVEN%' never matches 'H.A.V.E.N.'. Caught live in the cockpit (#5959);
	// the original unit tests missed it because they searched WITH the dots.
	fd := dedot(f)
	var out []PlatformSkill
	for _, k := range s.skills {
		if strings.Contains(strings.ToLower(k.Capability), f) ||
			strings.Contains(strings.ToLower(k.HomeDepartment), f) ||
			strings.Contains(dedot(strings.ToLower(k.DirectorAgent)), fd) {
			out = append(out, k)
		}
	}
	return out
}

// clamp keeps Selected inside the visible range. Without this, filtering down
// to fewer rows than the current index leaves Selection() indexing out of range.
func (s *SkillBridge) clamp() {
	n := len(s.Visible())
	if n == 0 {
		s.Selected = 0
		return
	}
	if s.Selected >= n {
		s.Selected = n - 1
	}
	if s.Selected < 0 {
		s.Selected = 0
	}
}

func (s *SkillBridge) MoveUp() {
	if s.Selected > 0 {
		s.Selected--
	}
}

func (s *SkillBridge) MoveDown() {
	if s.Selected < len(s.Visible())-1 {
		s.Selected++
	}
}

// Selection returns the highlighted skill. ok is false when nothing matches, so
// Enter on an empty filter result is a no-op rather than a panic.
func (s *SkillBridge) Selection() (PlatformSkill, bool) {
	vis := s.Visible()
	if len(vis) == 0 || s.Selected < 0 || s.Selected >= len(vis) {
		return PlatformSkill{}, false
	}
	return vis[s.Selected], true
}

// Toggle opens/closes the overlay, resetting transient state on open.
func (s *SkillBridge) Toggle() {
	s.Open = !s.Open
	if s.Open {
		s.Selected = 0
		s.filter = ""
	}
}

// Render draws the overlay. Known-tool entries are marked so it is obvious at a
// glance which selections cost no LLM time.
func (s *SkillBridge) Render(width int) string {
	if !s.Open {
		return ""
	}
	amber := lipgloss.NewStyle().Foreground(lipgloss.Color("#ffb000")).Bold(true)
	dim := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280"))
	sel := lipgloss.NewStyle().Background(lipgloss.Color("#2a1a00")).Foreground(lipgloss.Color("#ffb000")).Bold(true)
	text := lipgloss.NewStyle().Foreground(lipgloss.Color("#e5e7eb"))
	tool := lipgloss.NewStyle().Foreground(lipgloss.Color("#00e5ff"))

	var lines []string
	lines = append(lines, amber.Render("  Platform Skills  "+s.filter))
	lines = append(lines, dim.Render("  Up/Down + Enter dispatches via DHQ · Esc closes"))

	switch {
	case !s.Loaded:
		lines = append(lines, dim.Render("  Loading registry…"))
	case len(s.skills) == 0:
		lines = append(lines, dim.Render("  (registry empty — is the hub reachable?)"))
	default:
		vis := s.Visible()
		for i, k := range vis {
			if i >= 12 { // keep the overlay a viewport, not the whole 237-row registry
				lines = append(lines, dim.Render(fmt.Sprintf("  … %d more (type to filter)", len(vis)-12)))
				break
			}
			st, prefix := text, "  "
			if i == s.Selected {
				st, prefix = sel, "> "
			}
			badge := "  llm"
			if k.Kind == "known_tool" {
				badge = " tool"
			}
			owner := k.DirectorAgent
			if owner == "" {
				owner = k.HomeDepartment
			}
			row := fmt.Sprintf("%-30s %s", k.Capability, owner)
			if i == s.Selected {
				lines = append(lines, st.Render(prefix+row))
			} else {
				lines = append(lines, tool.Render(badge)+" "+st.Render(row))
			}
		}
		if len(vis) == 0 {
			lines = append(lines, dim.Render("  (no match)"))
		}
	}

	if s.Status != "" {
		lines = append(lines, "", amber.Render("  "+s.Status))
	}

	border := lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).BorderForeground(lipgloss.Color("#ffb000")).Padding(1)
	if width > 4 {
		border = border.Width(width - 4)
	}
	return border.Render(strings.Join(lines, "\n"))
}

// skillBridgeKey handles every keystroke while the platform-skill palette is
// open (#5333). It lives here, beside the palette state, rather than as five
// more branches inside the 886-line Update switch.
//
// Enter DISPATCHES the highlighted capability through DHQ. The reason string is
// stamped with the surface so a row in unified_tasks/task_execution_log says
// where it came from without anyone having to guess.
func (m model) skillBridgeKey(key string) (tea.Model, tea.Cmd) {
	switch key {
	case "esc":
		m.skillBridge.Open = false
		m.skillBridge.Status = ""
		return m, nil

	case "up":
		m.skillBridge.MoveUp()
		return m, nil

	case "down":
		m.skillBridge.MoveDown()
		return m, nil

	case "backspace":
		f := m.skillBridge.Filter()
		if f != "" {
			m.skillBridge.SetFilter(f[:len(f)-1])
		}
		return m, nil

	case "enter":
		sel, ok := m.skillBridge.Selection()
		if !ok {
			// Nothing matches the filter -- a no-op, never a panic.
			return m, nil
		}
		if !m.connected {
			m.skillBridge.Status = "not connected to the engine"
			return m, nil
		}
		_ = m.client.Send(map[string]interface{}{
			"type":       "platform_skill_invoke",
			"capability": sel.Capability,
			"reason":     "archie-tui skill palette: " + sel.Capability,
		})
		m.skillBridge.Status = "dispatching " + sel.Capability + "…"
		return m, nil

	default:
		// Printable single runes extend the filter; everything else is ignored
		// so an unmapped key cannot leak through to the main handler and, say,
		// quit or send the input line while an overlay is up.
		if len(key) == 1 {
			m.skillBridge.SetFilter(m.skillBridge.Filter() + key)
		}
		return m, nil
	}
}
