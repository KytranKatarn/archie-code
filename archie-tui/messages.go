package main

type EngineResponseMsg struct {
	Type           string   `json:"type"`
	SessionID      string   `json:"session_id"`
	Content        string   `json:"content"`
	Intent         string   `json:"intent"`
	ToolCalls      []string `json:"tool_calls"`
	HubStatus      string   `json:"hub_status"`
	NodeID         string   `json:"node_id"`
	Skills         []Skill  `json:"skills"`
	DispatchTarget string   `json:"dispatch_target"`
	// Platform status fields
	PlatformHub   string `json:"hub"`
	PlatformModel string `json:"model"`
	AgentsActive  int
	AgentsTotal   int
	// Coding-surface fields (#4264): repo_list / file_tree / file_content.
	// The file body reuses Content (json:"content") — file_content is a distinct
	// message type from chat "response", so there's no semantic clash.
	Repos     []Repo   `json:"repos"`
	Files     []string `json:"files"`
	Truncated bool     `json:"truncated"`
	FileRoot  string   `json:"root"`
	FilePath  string   `json:"path"`
	// git_diff / apply_edit (#4264 PR 3)
	Diff       string `json:"diff"`
	ApplyBytes int    `json:"bytes"`
	ApplyError string `json:"error"`
}

type Skill struct {
	Name        string `json:"name"`
	Description string `json:"description"`
	Source      string `json:"source"`
}

type Repo struct {
	Name  string `json:"name"`
	Path  string `json:"path"`
	Label string `json:"label"`
}

type ConnectedMsg struct {
	SessionID string
}

type DisconnectedMsg struct {
	Err error
}

type ErrorMsg struct {
	Err error
}

type StatusPanelRefreshMsg struct{}
