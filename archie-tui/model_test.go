package main

import "testing"

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
