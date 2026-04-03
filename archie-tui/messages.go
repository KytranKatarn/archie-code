package main

type EngineResponseMsg struct {
	Type      string   `json:"type"`
	SessionID string   `json:"session_id"`
	Content   string   `json:"content"`
	Intent    string   `json:"intent"`
	ToolCalls []string `json:"tool_calls"`
	HubStatus string   `json:"hub_status"`
	NodeID    string   `json:"node_id"`
	Skills         []Skill  `json:"skills"`
	DispatchTarget string   `json:"dispatch_target"`
}

type Skill struct {
	Name        string `json:"name"`
	Description string `json:"description"`
	Source      string `json:"source"`
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
