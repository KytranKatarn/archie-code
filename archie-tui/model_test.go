package main

import (
	"testing"

	tea "github.com/charmbracelet/bubbletea"
)

// parseEngineMessage previously omitted every coding-surface field, so
// repo_list/file_tree/file_content/git_diff arrived zero-valued (dead explorer)
// and a failed apply looked like a success. These tests lock the parse in.

func TestParseEngineMessageCodingSurface(t *testing.T) {
	r := parseEngineMessage(map[string]interface{}{
		"type": "repo_list",
		"repos": []interface{}{
			map[string]interface{}{"name": "archie-code", "path": "/x/archie-code", "label": "archie-code"},
		},
	})
	if len(r.Repos) != 1 || r.Repos[0].Name != "archie-code" || r.Repos[0].Path != "/x/archie-code" {
		t.Fatalf("repo_list not parsed: %+v", r.Repos)
	}

	ft := parseEngineMessage(map[string]interface{}{
		"type": "file_tree", "root": "/x/archie-code",
		"files": []interface{}{"a.go", "b.go"}, "truncated": true,
	})
	if len(ft.Files) != 2 || ft.Files[0] != "a.go" || ft.FileRoot != "/x/archie-code" || !ft.Truncated {
		t.Fatalf("file_tree not parsed: files=%v root=%q trunc=%v", ft.Files, ft.FileRoot, ft.Truncated)
	}

	fc := parseEngineMessage(map[string]interface{}{
		"type": "file_content", "root": "/x", "path": "a.go",
		"content": "package main", "truncated": false,
	})
	if fc.FilePath != "a.go" || fc.Content != "package main" || fc.Truncated {
		t.Fatalf("file_content not parsed: path=%q content=%q trunc=%v", fc.FilePath, fc.Content, fc.Truncated)
	}

	gd := parseEngineMessage(map[string]interface{}{"type": "git_diff", "diff": "@@ -1 +1 @@"})
	if gd.Diff != "@@ -1 +1 @@" {
		t.Fatalf("git_diff not parsed: %q", gd.Diff)
	}
}

func TestParseEngineMessageApplyResult(t *testing.T) {
	// JSON numbers arrive as float64 from a real ws frame.
	ok := parseEngineMessage(map[string]interface{}{
		"type": "apply_result", "root": "/x", "path": "a.go", "bytes": float64(1234),
	})
	if ok.ApplyError != "" {
		t.Fatalf("clean apply must have empty ApplyError, got %q", ok.ApplyError)
	}
	if ok.ApplyBytes != 1234 {
		t.Fatalf("apply bytes not parsed: %d", ok.ApplyBytes)
	}

	fail := parseEngineMessage(map[string]interface{}{
		"type": "apply_result", "error": "write failed: permission denied",
	})
	if fail.ApplyError != "write failed: permission denied" {
		t.Fatalf("failed apply must surface its error (else UI shows a false success), got %q", fail.ApplyError)
	}
}

func TestParseEngineMessageErrorFrame(t *testing.T) {
	e := parseEngineMessage(map[string]interface{}{"type": "error", "error": "Unknown message type: foo"})
	if e.ApplyError != "Unknown message type: foo" {
		t.Fatalf("error text must be parsed from the 'error' key, got %q", e.ApplyError)
	}
}

func TestParseEngineMessageChatResponse(t *testing.T) {
	c := parseEngineMessage(map[string]interface{}{
		"type": "response", "session_id": "s1", "content": "hi",
		"dispatch_target": "local", "dispatch_reason": "cheap", "intent": "chat",
	})
	if c.Content != "hi" || c.SessionID != "s1" || c.DispatchTarget != "local" || c.DispatchReason != "cheap" {
		t.Fatalf("chat response regressed: %+v", c)
	}
}

func TestParseEngineMessagePlatformStatus(t *testing.T) {
	p := parseEngineMessage(map[string]interface{}{
		"type": "platform_status", "hub": "192.168.1.200", "model": "qwen2.5:7b",
		"agents": map[string]interface{}{"active": float64(79), "total": float64(162)},
	})
	if p.PlatformHub != "192.168.1.200" || p.PlatformModel != "qwen2.5:7b" ||
		p.AgentsActive != 79 || p.AgentsTotal != 162 {
		t.Fatalf("platform_status regressed: %+v", p)
	}
}

func TestParseEngineMessageProgress(t *testing.T) {
	// Task 3/4 streaming: a progress frame must expose stage + detail so the REPL
	// can render intermediate steps before the final response.
	pr := parseEngineMessage(map[string]interface{}{
		"type": "progress", "session_id": "s1", "stage": "dispatch",
		"detail": "chat -> local",
	})
	if pr.Type != "progress" || pr.Stage != "dispatch" || pr.Detail != "chat -> local" || pr.SessionID != "s1" {
		t.Fatalf("progress frame not parsed: %+v", pr)
	}
}

func TestParseEngineMessageBadge(t *testing.T) {
	// Task 7: agent/node/model provenance on a response frame drives the badge.
	r := parseEngineMessage(map[string]interface{}{
		"type": "response", "content": "hi",
		"agent": "F.O.R.G.E.", "node": "hub", "model": "qwen2.5:7b",
	})
	if r.Agent != "F.O.R.G.E." || r.Node != "hub" || r.Model != "qwen2.5:7b" {
		t.Fatalf("badge fields not parsed: %+v", r)
	}
}

func TestAgentBadge(t *testing.T) {
	if got := agentBadge("F.O.R.G.E.", "Starship-246", "qwen2.5:7b"); got != "\u27e8F.O.R.G.E. \u00b7 Starship-246 \u00b7 qwen2.5:7b\u27e9" {
		t.Fatalf("badge format: %q", got)
	}
	if got := agentBadge("A.R.C.H.I.E.", "", "qwen2.5:1.5b"); got != "\u27e8A.R.C.H.I.E. \u00b7 qwen2.5:1.5b\u27e9" {
		t.Fatalf("badge omit-empty: %q", got)
	}
	if got := agentBadge("", "", ""); got != "" {
		t.Fatalf("empty badge must be empty: %q", got)
	}
}

func TestParseEngineMessageToolsList(t *testing.T) {
	// Task 5 (tool palette): tools_list frame → Tools with name+description.
	r := parseEngineMessage(map[string]interface{}{
		"type": "tools_list",
		"tools": []interface{}{
			map[string]interface{}{"name": "git_status", "description": "show git status"},
			map[string]interface{}{"name": "shell_exec", "description": "run a command"},
		},
	})
	if len(r.Tools) != 2 || r.Tools[0].Name != "git_status" || r.Tools[1].Description != "run a command" {
		t.Fatalf("tools_list not parsed: %+v", r.Tools)
	}
}

func TestParseEngineMessageBuildResult(t *testing.T) {
	// Task 5 (driveable build): build_result carries success/stage/branch/pr_url.
	ok := parseEngineMessage(map[string]interface{}{
		"type": "build_result", "success": true, "stage": "done",
		"branch": "engine/x", "pr_url": "https://gh/pr/9",
	})
	if !ok.BuildSuccess || ok.BuildStage != "done" || ok.Branch != "engine/x" || ok.PRURL != "https://gh/pr/9" {
		t.Fatalf("build_result not parsed: %+v", ok)
	}
	fail := parseEngineMessage(map[string]interface{}{
		"type": "build_result", "success": false, "stage": "test", "error": "2 failed",
	})
	if fail.BuildSuccess || fail.BuildStage != "test" || fail.ApplyError != "2 failed" {
		t.Fatalf("failed build_result not parsed: %+v", fail)
	}
}

func TestApplyEditRequiresApproval(t *testing.T) {
	// Task 5 (apply_edit approval): Ctrl+S stages the edit for confirmation and
	// does NOT send it until approved; 'n' cancels.
	m := initialModel("ws://x")
	m.connected = true
	m.explorer.CurrentRepo = "/repo"
	m.explorer.OpenPath = "a.go"
	m.editing = true
	m.editor.SetValue("new content")

	nm, _ := m.Update(tea.KeyMsg{Type: tea.KeyCtrlS})
	mm := nm.(model)
	if mm.editing {
		t.Fatal("Ctrl+S should exit edit mode")
	}
	if mm.pendingApply == nil {
		t.Fatal("Ctrl+S must stage a pending apply for approval, not send immediately")
	}
	if mm.pendingApply.path != "a.go" || mm.pendingApply.content != "new content" {
		t.Fatalf("pending apply wrong: %+v", mm.pendingApply)
	}

	nm2, _ := mm.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'n'}})
	if nm2.(model).pendingApply != nil {
		t.Fatal("'n' must cancel/clear the pending apply")
	}
}
