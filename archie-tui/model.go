package main

import (
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/textarea"
	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/KytranKatarn/archie-tui/views"
)

type model struct {
	input       textinput.Model
	chat        *views.ChatView
	statusBar   *views.StatusBar
	skillPicker *views.SkillPicker
	companion   *views.CompanionView
	statusPanel *views.StatusPanel
	explorer    *views.FileExplorer
	editor      textarea.Model
	editing     bool
	client      *Client
	sessionID   string
	width       int
	height      int
	connected   bool
	err         error
}

func initialModel(wsURL string) model {
	ti := textinput.New()
	ti.Placeholder = "Type a message or /command..."
	ti.Focus()
	ti.CharLimit = 4096
	ti.Width = 80
	ti.Prompt = "❯ "
	ti.PromptStyle = InputPromptStyle

	ed := textarea.New()
	ed.Placeholder = "Edit file content — Ctrl+S apply · Esc cancel"
	ed.CharLimit = 0 // unbounded; apply_edit is path-safe + size-bounded server-side

	return model{
		input:       ti,
		chat:        views.NewChatView(),
		statusBar:   views.NewStatusBar(),
		skillPicker: views.NewSkillPicker(),
		companion:   views.NewCompanionView(),
		statusPanel: views.NewStatusPanel(),
		explorer:    views.NewFileExplorer(),
		editor:      ed,
		client:      NewClient(wsURL),
	}
}

func statusPanelRefreshCmd() tea.Cmd {
	return tea.Tick(30*time.Second, func(t time.Time) tea.Msg {
		return StatusPanelRefreshMsg{}
	})
}

func (m model) Init() tea.Cmd {
	return tea.Batch(
		textinput.Blink,
		m.connectCmd(),
		views.BlinkCmd(),
		views.SwayCmd(),
		views.SleepCheckCmd(),
		statusPanelRefreshCmd(),
	)
}

func (m model) connectCmd() tea.Cmd {
	return func() tea.Msg {
		err := m.client.Connect()
		if err != nil {
			return DisconnectedMsg{Err: err}
		}
		// Create session
		_ = m.client.Send(map[string]interface{}{
			"type":        "session_create",
			"working_dir": ".",
		})
		// Request skills
		_ = m.client.Send(map[string]interface{}{"type": "list_skills"})
		// Request hub status
		_ = m.client.Send(map[string]interface{}{"type": "hub_status"})
		return ConnectedMsg{}
	}
}

// listenCmd returns a tea.Cmd that waits for the next engine message
// and feeds it back into the Bubble Tea update loop.
func (m model) listenCmd() tea.Cmd {
	return func() tea.Msg {
		ch := make(chan map[string]interface{}, 1)
		m.client.SetOnMessage(func(msg map[string]interface{}) {
			ch <- msg
		})
		raw := <-ch

		// Parse into EngineResponseMsg
		resp := EngineResponseMsg{
			Type:           getString(raw, "type"),
			SessionID:      getString(raw, "session_id"),
			Content:        getString(raw, "content"),
			Intent:         getString(raw, "intent"),
			HubStatus:      getString(raw, "hub_status"),
			NodeID:         getString(raw, "node_id"),
			DispatchTarget: getString(raw, "dispatch_target"),
		}

		// Parse skills array if present
		if skillsRaw, ok := raw["skills"].([]interface{}); ok {
			for _, s := range skillsRaw {
				if sm, ok := s.(map[string]interface{}); ok {
					resp.Skills = append(resp.Skills, Skill{
						Name:        getString(sm, "name"),
						Description: getString(sm, "description"),
						Source:      getString(sm, "source"),
					})
				}
			}
		}

		// Parse platform_status fields
		if raw["hub"] != nil {
			resp.PlatformHub = getString(raw, "hub")
		}
		if raw["model"] != nil {
			resp.PlatformModel = getString(raw, "model")
		}
		if agentsMap, ok := raw["agents"].(map[string]interface{}); ok {
			active, _ := agentsMap["active"].(float64)
			total, _ := agentsMap["total"].(float64)
			resp.AgentsActive = int(active)
			resp.AgentsTotal = int(total)
		}

		return resp
	}
}

func getString(m map[string]interface{}, key string) string {
	if v, ok := m[key].(string); ok {
		return v
	}
	return ""
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		// Edit mode (#4264 PR 3): the textarea owns all keys except apply/cancel.
		if m.editing {
			switch msg.String() {
			case "ctrl+s":
				if m.connected && m.explorer.OpenPath != "" {
					_ = m.client.Send(map[string]interface{}{
						"type":    "apply_edit",
						"root":    m.explorer.CurrentRepo,
						"path":    m.explorer.OpenPath,
						"content": m.editor.Value(),
					})
				}
				m.editing = false
				m.editor.Blur()
				return m, nil
			case "esc":
				m.editing = false
				m.editor.Blur()
				return m, nil
			}
			var ecmd tea.Cmd
			m.editor, ecmd = m.editor.Update(msg)
			return m, ecmd
		}
		switch msg.String() {
		case "ctrl+c", "ctrl+d":
			m.client.Close()
			return m, tea.Quit
		case "enter":
			if m.explorer.Visible {
				return m.explorerEnter()
			}
			if m.skillPicker.Visible {
				filtered := m.skillPicker.Filtered()
				if len(filtered) > 0 && m.skillPicker.Selected < len(filtered) {
					skill := filtered[m.skillPicker.Selected]
					m.input.SetValue("/" + skill.Name + " ")
					m.skillPicker.Visible = false
				}
				return m, nil
			}
			val := strings.TrimSpace(m.input.Value())
			if val == "" {
				return m, nil
			}
			m.chat.AddMessage("user", val)
			m.input.SetValue("")
			if m.connected {
				_ = m.client.SendMessage(val, m.sessionID)
				m.companion.SetState(views.StateThinking, "hmm, thinking...")
			} else {
				m.chat.AddMessage("system", "Not connected to engine")
			}
			return m, nil
		case "esc":
			if m.explorer.Visible {
				if m.explorer.Mode == "diff" {
					m.explorer.Mode = "tree"
					return m, nil
				}
				m.explorer.Visible = false
				return m, nil
			}
			if m.skillPicker.Visible {
				m.skillPicker.Visible = false
				return m, nil
			}
		case "ctrl+s":
			m.statusPanel.Visible = !m.statusPanel.Visible
			if m.statusPanel.Visible && m.connected {
				_ = m.client.Send(map[string]interface{}{"type": "platform_status"})
			}
			return m, nil
		case "ctrl+e":
			m.explorer.Visible = !m.explorer.Visible
			if m.explorer.Visible {
				m.explorer.Mode = "repo"
				m.explorer.Selected = 0
				m.explorer.OpenPath = ""
				if len(m.explorer.Repos) == 0 && m.connected {
					_ = m.client.Send(map[string]interface{}{"type": "repo_list"})
				}
			}
			return m, nil
		case "backspace":
			if m.explorer.Visible && m.explorer.Mode == "diff" {
				m.explorer.Mode = "tree"
				return m, nil
			}
			if m.explorer.Visible && m.explorer.Mode == "tree" {
				m.explorer.Mode = "repo"
				m.explorer.Selected = 0
				m.explorer.OpenPath = ""
				return m, nil
			}
		case "d":
			if m.explorer.Visible && m.explorer.Mode != "repo" {
				if m.connected {
					payload := map[string]interface{}{"type": "git_diff", "root": m.explorer.CurrentRepo}
					if m.explorer.OpenPath != "" {
						payload["path"] = m.explorer.OpenPath
					}
					_ = m.client.Send(payload)
				}
				return m, nil
			}
		case "e":
			if m.explorer.Visible && m.explorer.OpenPath != "" {
				m.editing = true
				m.editor.SetValue(m.explorer.OpenContent)
				m.editor.Focus()
				return m, textarea.Blink
			}
		case "tab":
			m.skillPicker.Visible = !m.skillPicker.Visible
			return m, nil
		case "up":
			if m.explorer.Visible {
				if m.explorer.Selected > 0 {
					m.explorer.Selected--
				}
				return m, nil
			}
			if m.skillPicker.Visible && m.skillPicker.Selected > 0 {
				m.skillPicker.Selected--
				return m, nil
			}
		case "down":
			if m.explorer.Visible {
				if m.explorer.Selected < m.explorer.MaxIndex() {
					m.explorer.Selected++
				}
				return m, nil
			}
			if m.skillPicker.Visible {
				filtered := m.skillPicker.Filtered()
				if m.skillPicker.Selected < len(filtered)-1 {
					m.skillPicker.Selected++
				}
				return m, nil
			}
		}

	case StatusPanelRefreshMsg:
		if m.statusPanel.Visible && m.connected {
			_ = m.client.Send(map[string]interface{}{"type": "platform_status"})
		}
		return m, statusPanelRefreshCmd()

	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		m.input.Width = msg.Width - 4
		m.chat.Width = msg.Width
		m.chat.Height = msg.Height - 5
		m.statusBar.Width = msg.Width
		m.skillPicker.Width = msg.Width
		m.skillPicker.Height = msg.Height / 2
		m.companion.Width = msg.Width
		m.companion.Height = msg.Height
		m.statusPanel.Width = msg.Width / 3
		if m.statusPanel.Width < 25 {
			m.statusPanel.Width = 25
		}
		m.explorer.Width = msg.Width
		m.explorer.Height = msg.Height
		m.editor.SetWidth(msg.Width - 4)
		m.editor.SetHeight(msg.Height - 8)

	case ConnectedMsg:
		m.connected = true
		m.chat.AddMessage("system", "Connected to ARCHIE Engine")
		if msg.SessionID != "" {
			m.sessionID = msg.SessionID
		}
		// Start listening for engine responses
		return m, m.listenCmd()

	case DisconnectedMsg:
		m.connected = false
		if msg.Err != nil {
			m.chat.AddMessage("system", fmt.Sprintf("Engine not running: %v", msg.Err))
			m.chat.AddMessage("system", "Start engine: python3 -m archie_engine")
		}

	case views.BlinkTickMsg, views.BlinkEndMsg, views.SwayTickMsg, views.SleepCheckMsg:
		cmd := m.companion.Update(msg)
		return m, cmd

	case EngineResponseMsg:
		switch msg.Type {
		case "response":
			m.chat.AddMessage("assistant", msg.Content)
			if msg.SessionID != "" {
				m.sessionID = msg.SessionID
			}
			if msg.DispatchTarget != "" {
				meta := "via " + msg.DispatchTarget
				if msg.Intent != "" {
					meta += " · " + msg.Intent
				}
				if msg.DispatchReason != "" {
					meta += " — " + msg.DispatchReason
				}
				m.chat.AddMessage("system", meta)
			}
		case "session_created":
			m.sessionID = msg.SessionID
		case "hub_status":
			m.statusBar.HubStatus = msg.HubStatus
		case "skills_list":
			var items []views.SkillItem
			for _, s := range msg.Skills {
				items = append(items, views.SkillItem{Name: s.Name, Description: s.Description})
			}
			m.skillPicker.Skills = items
		case "repo_list":
			var repos []views.RepoItem
			for _, r := range msg.Repos {
				repos = append(repos, views.RepoItem{Name: r.Name, Path: r.Path, Label: r.Label})
			}
			m.explorer.Repos = repos
		case "file_tree":
			m.explorer.Files = msg.Files
			m.explorer.Truncated = msg.Truncated
			if msg.FileRoot != "" {
				m.explorer.CurrentRepo = msg.FileRoot
			}
			m.explorer.Selected = 0
		case "file_content":
			m.explorer.OpenPath = msg.FilePath
			m.explorer.OpenContent = msg.Content
		case "git_diff":
			m.explorer.DiffContent = msg.Diff
			m.explorer.Mode = "diff"
		case "apply_result":
			if msg.ApplyError != "" {
				m.chat.AddMessage("system", "apply failed: "+msg.ApplyError)
			} else {
				m.chat.AddMessage("system", fmt.Sprintf("✓ applied %s (%d bytes)", msg.FilePath, msg.ApplyBytes))
				m.explorer.OpenContent = m.editor.Value()
				if m.connected && m.explorer.OpenPath != "" {
					_ = m.client.Send(map[string]interface{}{"type": "git_diff", "root": m.explorer.CurrentRepo, "path": m.explorer.OpenPath})
				}
			}
		case "error":
			m.chat.AddMessage("system", fmt.Sprintf("Error: %s", msg.Content))
		case "platform_status":
			m.statusPanel.Hub = msg.PlatformHub
			m.statusPanel.Model = msg.PlatformModel
			if msg.AgentsTotal > 0 {
				m.statusPanel.Agents = &views.AgentStats{
					Active: msg.AgentsActive,
					Total:  msg.AgentsTotal,
				}
			}
		}
		// Update companion state based on engine message
		switch msg.Type {
		case "response":
			if strings.Contains(msg.Content, "error") || strings.Contains(msg.Content, "Error") {
				m.companion.SetState(views.StateConcerned, "oh no... let me retry")
			} else {
				m.companion.SetState(views.StateHappy, "done! ◡")
			}
		case "session_created":
			m.companion.SetState(views.StateHappy, "hello! ◡")
		case "hub_status":
			if msg.HubStatus == "connected" {
				m.companion.SetState(views.StateIdle, "✦ ready")
			} else {
				m.companion.SetState(views.StateIdle, "flying solo ✦")
			}
		case "error":
			m.companion.SetState(views.StateConcerned, "oh no... let me retry")
		}
		if msg.DispatchTarget == "platform" {
			m.companion.SetState(views.StateThinking, "asking the crew ✦")
		} else if msg.DispatchTarget == "local" {
			m.companion.SetState(views.StateThinking, "hmm, thinking...")
		}
		// Keep listening for next engine message
		return m, m.listenCmd()
	}

	var cmd tea.Cmd
	m.input, cmd = m.input.Update(msg)
	return m, cmd
}

// explorerEnter handles Enter in the file explorer: pick a repo (→ file_tree +
// session working_dir) or open a file (→ file_read). #4264 PR 2.
func (m model) explorerEnter() (tea.Model, tea.Cmd) {
	if m.explorer.Mode == "repo" {
		if m.explorer.Selected >= 0 && m.explorer.Selected < len(m.explorer.Repos) {
			r := m.explorer.Repos[m.explorer.Selected]
			m.explorer.CurrentRepo = r.Path
			m.explorer.CurrentName = r.Name
			m.explorer.Mode = "tree"
			m.explorer.Selected = 0
			m.explorer.Files = nil
			m.explorer.OpenPath = ""
			if m.connected {
				_ = m.client.Send(map[string]interface{}{"type": "file_tree", "root": r.Path})
				// Point the chat/build session at the chosen repo (was hardcoded ".").
				_ = m.client.Send(map[string]interface{}{"type": "session_create", "working_dir": r.Path})
			}
		}
		return m, nil
	}
	if m.explorer.Selected >= 0 && m.explorer.Selected < len(m.explorer.Files) {
		path := m.explorer.Files[m.explorer.Selected]
		if m.connected {
			_ = m.client.Send(map[string]interface{}{"type": "file_read", "root": m.explorer.CurrentRepo, "path": path})
		}
	}
	return m, nil
}

func (m model) View() string {
	if m.width == 0 {
		return "Loading..."
	}

	// LCARS header
	header := views.LCARSHeader("A.R.C.H.I.E. Code CLI", ColorCyan, m.width)

	// Chat content with companion
	chatContent := m.chat.Render()
	companionBlock := m.companion.Render()

	var mainPanel string
	if companionBlock != "" {
		companionWidth := 20
		chatWidth := m.width - companionWidth - 6 // account for panel borders
		if chatWidth < 40 {
			mainPanel = views.LCARSPanel(chatContent, "COMMS", ColorCyan, m.width)
		} else {
			chatStyled := lipgloss.NewStyle().Width(chatWidth).Render(chatContent)
			companionStyled := lipgloss.NewStyle().Width(companionWidth).Render(companionBlock)
			combined := lipgloss.JoinHorizontal(lipgloss.Bottom, chatStyled, companionStyled)
			mainPanel = views.LCARSPanel(combined, "COMMS", ColorCyan, m.width)
		}
	} else {
		mainPanel = views.LCARSPanel(chatContent, "COMMS", ColorCyan, m.width)
	}

	// Status panel (side panel, toggled with Ctrl+S)
	statusPanelBlock := m.statusPanel.Render()

	// Skill picker overlay
	var skillSection string
	if m.skillPicker.Visible {
		skillSection = m.skillPicker.Render()
	}

	// Input area
	inputLine := lipgloss.NewStyle().Padding(0, 1).Render(m.input.View())

	// LCARS status bar
	statusContent := m.statusBar.RenderContent()
	statusBar := views.LCARSStatusBar(statusContent, ColorCyan, m.width)

	// Assemble
	var sections []string
	sections = append(sections, header)

	if statusPanelBlock != "" {
		panelWidth := m.width - m.statusPanel.Width - 1
		if panelWidth < 40 {
			panelWidth = m.width
		}
		mainPanelStyled := lipgloss.NewStyle().Width(panelWidth).Render(mainPanel)
		combined := lipgloss.JoinHorizontal(lipgloss.Top, mainPanelStyled, statusPanelBlock)
		sections = append(sections, combined)
	} else {
		sections = append(sections, mainPanel)
	}
	if skillSection != "" {
		sections = append(sections, skillSection)
	}
	if explorerSection := m.explorer.Render(); explorerSection != "" {
		sections = append(sections, explorerSection)
	}
	if m.editing {
		sections = append(sections, views.LCARSHeader("EDIT — "+m.explorer.OpenPath, ColorCyan, m.width))
		sections = append(sections, m.editor.View())
	}

	mainContent := strings.Join(sections, "\n")
	mainLines := strings.Count(mainContent, "\n") + 1
	if mainLines < m.height-3 {
		mainContent += strings.Repeat("\n", m.height-3-mainLines)
	}

	return mainContent + "\n" + inputLine + "\n" + statusBar
}
