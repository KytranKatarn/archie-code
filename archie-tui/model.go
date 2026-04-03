package main

import (
	"fmt"
	"strings"

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

	return model{
		input:       ti,
		chat:        views.NewChatView(),
		statusBar:   views.NewStatusBar(),
		skillPicker: views.NewSkillPicker(),
		companion:   views.NewCompanionView(),
		client:      NewClient(wsURL),
	}
}

func (m model) Init() tea.Cmd {
	return tea.Batch(
		textinput.Blink,
		m.connectCmd(),
		views.BlinkCmd(),
		views.SwayCmd(),
		views.SleepCheckCmd(),
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
		switch msg.String() {
		case "ctrl+c", "ctrl+d":
			m.client.Close()
			return m, tea.Quit
		case "enter":
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
			if m.skillPicker.Visible {
				m.skillPicker.Visible = false
				return m, nil
			}
		case "tab":
			m.skillPicker.Visible = !m.skillPicker.Visible
			return m, nil
		case "up":
			if m.skillPicker.Visible && m.skillPicker.Selected > 0 {
				m.skillPicker.Selected--
				return m, nil
			}
		case "down":
			if m.skillPicker.Visible {
				filtered := m.skillPicker.Filtered()
				if m.skillPicker.Selected < len(filtered)-1 {
					m.skillPicker.Selected++
				}
				return m, nil
			}
		}

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
			m.chat.AddMessage("system", "Start engine: python -m archie_engine")
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
		case "error":
			m.chat.AddMessage("system", fmt.Sprintf("Error: %s", msg.Content))
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
	sections = append(sections, mainPanel)
	if skillSection != "" {
		sections = append(sections, skillSection)
	}

	mainContent := strings.Join(sections, "\n")
	mainLines := strings.Count(mainContent, "\n") + 1
	if mainLines < m.height-3 {
		mainContent += strings.Repeat("\n", m.height-3-mainLines)
	}

	return mainContent + "\n" + inputLine + "\n" + statusBar
}
