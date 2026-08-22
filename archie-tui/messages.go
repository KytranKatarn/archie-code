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
	DispatchReason string   `json:"dispatch_reason"`
	// Progress streaming (Task 3/4): intermediate frames before the final response.
	Stage  string `json:"stage"`
	Detail string `json:"detail"`
	// Provenance badge (Task 7): who / where / what served the turn. Populated
	// manually by parseEngineMessage (json tags are not used for decoding).
	Agent string
	Node  string
	Model string
	// Tool palette (Task 5): tools_list frame.
	Tools []Tool
	// Driveable build (Task 5): build_result frame.
	BuildSuccess bool
	BuildStage   string
	Branch       string
	PRURL        string
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
	// approval_request (Task 5): kind + path(FilePath) + diff; SessionID reused.
	Kind string `json:"kind"`
	// --- #5333 platform skill bridge -------------------------------------
	// platform_skills: the hub's invokable-skills registry. Named distinctly from
	// Skills (the engine's OWN local skills) -- they are different registries and
	// collapsing them would hide which side of the mesh a selection runs on.
	// NOTE the deliberate `json:"-"`: the hub's registry frame also uses the key
	// "skills", which would COLLIDE with Skills above -- and Go drops BOTH fields
	// on a duplicate json tag, silently. Decoding here is manual
	// (parseEngineMessage reads a map), so the tag is unused either way; keeping
	// it "-" means a future switch to json.Unmarshal cannot quietly empty both.
	PlatformSkills []PlatformSkill `json:"-"`
	KnownToolCount int             `json:"known_tool_count"`
	LLMCount       int             `json:"llm_count"`
	// platform_skill_result / platform_skill_status
	TaskID     int    `json:"task_id"`
	TaskStatus string `json:"status"`
	Capability string `json:"capability"`
	WorkNotes  string `json:"work_notes"`
	// Error carries a fail-soft hub error ({"error": ...}) for any of the three.
	// `json:"-"` for the same reason as PlatformSkills: "error" is already
	// claimed by ApplyError above, and a duplicate tag makes Go drop BOTH.
	// go vet catches this one -- keep it that way.
	Error string `json:"-"`
}

// PlatformSkill is one entry in the hub's invokable-skills registry (#5333).
// kind is "known_tool" (runs directly, no LLM) or "llm" (routed via
// CAPABILITY_DEPARTMENT_MAP to a department director).
type PlatformSkill struct {
	Capability     string `json:"capability"`
	Kind           string `json:"kind"`
	HomeDepartment string `json:"home_department"`
	DirectorAgent  string `json:"director_agent"`
	Description    string `json:"description"`
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

type Tool struct {
	Name        string `json:"name"`
	Description string `json:"description"`
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
