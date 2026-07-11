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

// pendingEdit is an edit staged by the editor (Ctrl+S) awaiting operator approval
// before it is sent as an apply_edit (Task 5).
type pendingEdit struct {
	sessionID string
	path      string
}

type model struct {
	input        textinput.Model
	chat         *views.ChatView
	statusBar    *views.StatusBar
	skillPicker  *views.SkillPicker
	toolPalette  *views.ToolPalette
	palette      *Palette
	companion    *views.CompanionView
	statusPanel  *views.StatusPanel
	explorer     *views.FileExplorer
	editor       textarea.Model
	editing      bool
	pendingApply *pendingEdit
	client       *Client
	sessionID    string
	width        int
	height       int
	connected    bool
	err          error
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
		toolPalette: views.NewToolPalette(),
		palette:     NewPalette(nil),
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
		select {
		case raw, ok := <-m.client.Messages():
			if !ok {
				return DisconnectedMsg{Err: fmt.Errorf("engine connection closed")}
			}
			return parseEngineMessage(raw)
		case err := <-m.client.Errs():
			return DisconnectedMsg{Err: err}
		}
	}
}

// parseEngineMessage converts a decoded engine frame into an EngineResponseMsg.
// It is pure (no client/IO) so it can be unit-tested. Every field the Update
// switch reads MUST be extracted here: the frame is decoded into a map and never
// unmarshalled into the struct, so the struct's json tags are not used and any
// omitted field silently arrives zero-valued. That omission previously left the
// whole coding surface dead (repo_list/file_tree/file_content/git_diff never
// populated) and made a FAILED apply render as success (ApplyError always "").
func parseEngineMessage(raw map[string]interface{}) EngineResponseMsg {
	resp := EngineResponseMsg{
		Type:           getString(raw, "type"),
		SessionID:      getString(raw, "session_id"),
		Content:        getString(raw, "content"),
		Intent:         getString(raw, "intent"),
		HubStatus:      getString(raw, "hub_status"),
		NodeID:         getString(raw, "node_id"),
		DispatchTarget: getString(raw, "dispatch_target"),
		DispatchReason: getString(raw, "dispatch_reason"),
		// Progress streaming (Task 3/4)
		Stage:  getString(raw, "stage"),
		Detail: getString(raw, "detail"),
		// Provenance badge (Task 7)
		Agent: getString(raw, "agent"),
		Node:  getString(raw, "node"),
		Model: getString(raw, "model"),
		// build_result (Task 5)
		BuildSuccess: getBool(raw, "success"),
		BuildStage:   getString(raw, "stage"),
		Branch:       getString(raw, "branch"),
		PRURL:        getString(raw, "pr_url"),
		// Coding-surface fields (#4264): file_tree / file_content / git_diff /
		// apply_result. The shared root/path/error keys are reused across message
		// types — harmless because Update dispatches on Type first.
		Files:      getStringSlice(raw, "files"),
		Truncated:  getBool(raw, "truncated"),
		FileRoot:   getString(raw, "root"),
		FilePath:   getString(raw, "path"),
		Diff:       getString(raw, "diff"),
		ApplyBytes: getInt(raw, "bytes"),
		ApplyError: getString(raw, "error"),
		Kind:       getString(raw, "kind"),
	}

	// repo_list: repos: [{name, path, label}]
	if reposRaw, ok := raw["repos"].([]interface{}); ok {
		for _, rr := range reposRaw {
			if rm, ok := rr.(map[string]interface{}); ok {
				resp.Repos = append(resp.Repos, Repo{
					Name:  getString(rm, "name"),
					Path:  getString(rm, "path"),
					Label: getString(rm, "label"),
				})
			}
		}
	}

	// skills_list: skills: [{name, description, source}]
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

	// tools_list: tools: [{name, description}] (Task 5)
	if toolsRaw, ok := raw["tools"].([]interface{}); ok {
		for _, tr := range toolsRaw {
			if tm, ok := tr.(map[string]interface{}); ok {
				resp.Tools = append(resp.Tools, Tool{
					Name:        getString(tm, "name"),
					Description: getString(tm, "description"),
				})
			}
		}
	}

	// platform_status: hub / model / agents{active,total}
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

func getString(m map[string]interface{}, key string) string {
	if v, ok := m[key].(string); ok {
		return v
	}
	return ""
}

func getBool(m map[string]interface{}, key string) bool {
	v, _ := m[key].(bool)
	return v
}

func getInt(m map[string]interface{}, key string) int {
	// JSON numbers decode into float64 in a map[string]interface{}.
	if v, ok := m[key].(float64); ok {
		return int(v)
	}
	return 0
}

func getStringSlice(m map[string]interface{}, key string) []string {
	raw, ok := m[key].([]interface{})
	if !ok {
		return nil
	}
	out := make([]string, 0, len(raw))
	for _, v := range raw {
		if s, ok := v.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

// agentBadge formats the per-response provenance badge (Task 7 / DispatchResult):
// who (agent) / where (node) / what (model) served the turn, joined with " \u00b7 "
// and wrapped in \u27e8\u27e9. Empty parts are omitted; an all-empty badge yields ""
// so the caller can skip rendering it.
func agentBadge(agent, node, model string) string {
	parts := make([]string, 0, 3)
	for _, p := range []string{agent, node, model} {
		if p != "" {
			parts = append(parts, p)
		}
	}
	if len(parts) == 0 {
		return ""
	}
	return "\u27e8" + strings.Join(parts, " \u00b7 ") + "\u27e9"
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		// Edit mode (#4264 PR 3): the textarea owns all keys except apply/cancel.
		if m.editing {
			switch msg.String() {
			case "ctrl+s":
				// Send the edit to the engine, which gates it behind an approval_request
				// (Task 5) — we never write client-side. Never send a buffer from a
				// truncated read (also blocked in the "e" handler).
				if m.connected && m.explorer.OpenPath != "" && !m.explorer.OpenTruncated {
					_ = m.client.Send(map[string]interface{}{
						"type":       "apply_edit",
						"session_id": m.sessionID,
						"root":       m.explorer.CurrentRepo,
						"path":       m.explorer.OpenPath,
						"content":    m.editor.Value(),
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
		// Apply-edit approval (Task 5): the engine emitted an approval_request;
		// the operator vets it with y/n. The send status is surfaced so a
		// disconnected/failed decision is never silently dropped (F.O.R.G.E.).
		if m.pendingApply != nil {
			switch msg.String() {
			case "y", "Y", "enter":
				m.sendApproval(true)
				m.pendingApply = nil
				return m, nil
			case "n", "N", "esc":
				m.sendApproval(false)
				m.pendingApply = nil
				return m, nil
			}
			return m, nil
		}
		// Command palette (Task 5): while open, keys filter/navigate/run.
		if m.palette.Open {
			switch msg.String() {
			case "esc":
				m.palette.Open = false
				return m, nil
			case "up":
				if m.palette.Selected > 0 {
					m.palette.Selected--
				}
				return m, nil
			case "down":
				if m.palette.Selected < len(m.palette.Visible())-1 {
					m.palette.Selected++
				}
				return m, nil
			case "enter":
				vis := m.palette.Visible()
				if m.palette.Selected < len(vis) {
					cmd := vis[m.palette.Selected]
					m.palette.Open = false
					if m.connected {
						m.chat.AddMessage("user", "/"+cmd)
						_ = m.client.SendMessage("/"+cmd, m.sessionID)
					}
				}
				return m, nil
			case "backspace":
				f := m.palette.Filter()
				if len(f) > 0 {
					m.palette.SetFilter(f[:len(f)-1])
				}
				return m, nil
			default:
				if len(msg.String()) == 1 {
					m.palette.SetFilter(m.palette.Filter() + msg.String())
				}
				return m, nil
			}
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
			if m.toolPalette.Visible {
				if m.toolPalette.Selected < len(m.toolPalette.Tools) {
					m.input.SetValue(m.input.Value() + m.toolPalette.Tools[m.toolPalette.Selected].Name)
				}
				m.toolPalette.Visible = false
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
			if m.toolPalette.Visible {
				m.toolPalette.Visible = false
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
		case "/":
			if m.input.Value() == "" && !m.explorer.Visible && !m.skillPicker.Visible && m.pendingApply == nil {
				m.palette.Open = true
				m.palette.SetFilter("")
				return m, nil
			}
		case "ctrl+t":
			m.toolPalette.Visible = !m.toolPalette.Visible
			if m.toolPalette.Visible {
				m.toolPalette.Selected = 0
				if len(m.toolPalette.Tools) == 0 && m.connected {
					_ = m.client.Send(map[string]interface{}{"type": "list_tools"})
				}
			}
			return m, nil
		case "ctrl+b":
			task := strings.TrimSpace(m.input.Value())
			if task == "" {
				m.chat.AddMessage("system", "Type a build task, then Ctrl+B to drive the build loop.")
				return m, nil
			}
			if m.connected {
				m.input.SetValue("")
				m.chat.AddMessage("user", "build: "+task)
				_ = m.client.Send(map[string]interface{}{"type": "build", "task": task})
				m.companion.SetState(views.StateThinking, "building...")
			} else {
				m.chat.AddMessage("system", "Not connected to engine")
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
				if m.explorer.OpenTruncated {
					m.chat.AddMessage("system", "Cannot edit: preview truncated at 200 KB — saving would discard everything past the cap.")
					return m, nil
				}
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
			if m.toolPalette.Visible && m.toolPalette.Selected > 0 {
				m.toolPalette.Selected--
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
			if m.toolPalette.Visible && m.toolPalette.Selected < len(m.toolPalette.Tools)-1 {
				m.toolPalette.Selected++
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
		m.toolPalette.Width = msg.Width
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
		case "progress":
			// Streamed intermediate step (Task 4): render a subtle progress line
			// and hold the companion in a working state. The final "response"
			// frame follows on the same session and replaces this state.
			if msg.Detail != "" {
				m.chat.AddMessage("system", "· "+msg.Detail)
			}
			m.companion.SetState(views.StateThinking, "working...")
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
			// Provenance badge (Task 7): agent / node / model that served the turn.
			if badge := agentBadge(msg.Agent, msg.Node, msg.Model); badge != "" {
				m.chat.AddMessage("system", badge)
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
			cmds := make([]string, 0, len(msg.Skills))
			for _, s := range msg.Skills {
				cmds = append(cmds, s.Name)
			}
			m.palette.SetCommands(cmds)
		case "tools_list":
			var titems []views.ToolItem
			for _, tl := range msg.Tools {
				titems = append(titems, views.ToolItem{Name: tl.Name, Description: tl.Description})
			}
			m.toolPalette.Tools = titems
		case "build_result":
			if msg.BuildSuccess {
				pr := msg.PRURL
				if pr == "" {
					pr = "(no PR url)"
				}
				m.chat.AddMessage("system", "\u2713 build passed \u2014 PR: "+pr)
				m.companion.SetState(views.StateHappy, "shipped!")
			} else {
				detail := msg.ApplyError
				if detail == "" {
					detail = msg.BuildStage
				}
				m.chat.AddMessage("system", "build failed at "+msg.BuildStage+": "+detail)
				m.companion.SetState(views.StateConcerned, "build broke...")
			}
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
			m.explorer.OpenTruncated = msg.Truncated
			if msg.Truncated {
				m.chat.AddMessage("system", "Note: file preview truncated at 200 KB — read-only (editing is blocked to prevent data loss).")
			}
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
		case "approval_request":
			// Engine wants to write (Task 5): stage a pending approval; the y/n
			// handler + the View banner drive the operator's decision.
			m.pendingApply = &pendingEdit{sessionID: msg.SessionID, path: msg.FilePath}
			m.chat.AddMessage("system", "Approve write to "+msg.FilePath+"?  [y] apply  [n] decline")
		case "apply_cancelled":
			m.chat.AddMessage("system", "apply declined: "+msg.FilePath)
		case "error":
			// Engine error frames carry the message under "error" (parsed into
			// ApplyError); fall back to Content for any legacy shape.
			errText := msg.ApplyError
			if errText == "" {
				errText = msg.Content
			}
			m.chat.AddMessage("system", "Error: "+errText)
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

// sendApproval delivers the operator's decision on a staged apply_edit and reports
// whether it actually reached the engine. A disconnected or failed send is surfaced
// (not silently dropped) so the operator knows the engine will DENY BY TIMEOUT
// rather than assuming their keypress landed (F.O.R.G.E. review on #34).
func (m model) sendApproval(approved bool) {
	verb := "approved"
	if !approved {
		verb = "denied"
	}
	if !m.connected {
		m.chat.AddMessage("system", "approval not delivered (disconnected) \u2014 engine will deny by timeout")
		return
	}
	if err := m.client.Send(map[string]interface{}{
		"type": "approval", "session_id": m.pendingApply.sessionID, "approved": approved,
	}); err != nil {
		m.chat.AddMessage("system", "approval not delivered (send failed) \u2014 engine will deny by timeout")
		return
	}
	m.chat.AddMessage("system", "approval sent: "+verb)
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

	// Tool palette overlay (Task 5)
	var toolSection string
	if m.toolPalette.Visible {
		toolSection = m.toolPalette.Render()
	}

	// Command palette overlay (Task 5)
	var paletteSection string
	if m.palette.Open {
		paletteSection = m.palette.Render(m.width)
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
	if toolSection != "" {
		sections = append(sections, toolSection)
	}
	if paletteSection != "" {
		sections = append(sections, paletteSection)
	}
	if m.pendingApply != nil {
		confirm := lipgloss.NewStyle().Foreground(lipgloss.Color("#fbbf24")).Bold(true).
			Render("Approve write to " + m.pendingApply.path + "?  [y] apply   [n] decline")
		sections = append(sections, confirm)
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
