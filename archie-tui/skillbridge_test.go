package main

import "testing"

func sample() []PlatformSkill {
	return []PlatformSkill{
		{Capability: "health_check", Kind: "known_tool", Description: "no LLM"},
		{Capability: "run_qa_suite", Kind: "known_tool", Description: "P.R.O.B.E."},
		{Capability: "code_review", Kind: "llm", HomeDepartment: "Engineering & Technology", DirectorAgent: "F.O.R.G.E."},
		{Capability: "documentation", Kind: "llm", HomeDepartment: "Documentation & Knowledge", DirectorAgent: "C.O.D.E.X."},
	}
}

func TestSkillBridgeFilterMatchesCapabilityDepartmentAndDirector(t *testing.T) {
	s := NewSkillBridge()
	s.SetSkills(sample())

	s.SetFilter("qa")
	if got := s.Visible(); len(got) != 1 || got[0].Capability != "run_qa_suite" {
		t.Fatalf("capability filter: got %v", got)
	}
	// Department and director are searchable too -- "who owns this?" is how a
	// human looks for work, not by exact capability slug.
	s.SetFilter("engineering")
	if got := s.Visible(); len(got) != 1 || got[0].Capability != "code_review" {
		t.Fatalf("department filter: got %v", got)
	}
	s.SetFilter("c.o.d.e.x.")
	if got := s.Visible(); len(got) != 1 || got[0].Capability != "documentation" {
		t.Fatalf("director filter: got %v", got)
	}
	s.SetFilter("")
	if len(s.Visible()) != 4 {
		t.Fatalf("empty filter must show all, got %d", len(s.Visible()))
	}
}

// The bug this exists for: filtering to fewer rows than the current index used
// to leave Selection() indexing past the end of the slice.
func TestSelectionNeverIndexesOutOfRange(t *testing.T) {
	s := NewSkillBridge()
	s.SetSkills(sample())
	s.Selected = 3
	s.SetFilter("health") // 1 row, selection was 3
	if _, ok := s.Selection(); !ok {
		t.Fatal("selection should be valid after filtering")
	}
	if sel, _ := s.Selection(); sel.Capability != "health_check" {
		t.Fatalf("wrong row: %v", sel)
	}
}

func TestSelectionIsNotOkWhenNothingMatches(t *testing.T) {
	s := NewSkillBridge()
	s.SetSkills(sample())
	s.SetFilter("zzzz-no-such-capability")
	if _, ok := s.Selection(); ok {
		t.Fatal("Enter on an empty result must be a no-op, not a panic")
	}
}

func TestMoveUpDownClampAtBothEnds(t *testing.T) {
	s := NewSkillBridge()
	s.SetSkills(sample())
	s.MoveUp() // already at 0
	if s.Selected != 0 {
		t.Fatalf("MoveUp past the top: %d", s.Selected)
	}
	for i := 0; i < 10; i++ {
		s.MoveDown()
	}
	if s.Selected != len(sample())-1 {
		t.Fatalf("MoveDown past the end: %d", s.Selected)
	}
}

func TestToggleResetsFilterAndSelection(t *testing.T) {
	s := NewSkillBridge()
	s.SetSkills(sample())
	s.SetFilter("code")
	s.Selected = 0
	s.Toggle() // open
	if !s.Open || s.Filter() != "" || s.Selected != 0 {
		t.Fatalf("open must reset: open=%v filter=%q sel=%d", s.Open, s.Filter(), s.Selected)
	}
	s.Toggle()
	if s.Open {
		t.Fatal("second toggle must close")
	}
}

// Loaded must distinguish "no reply yet" from "the registry really is empty",
// otherwise an empty registry renders "Loading…" forever.
func TestLoadedDistinguishesEmptyFromPending(t *testing.T) {
	s := NewSkillBridge()
	if s.Loaded {
		t.Fatal("must not start Loaded")
	}
	s.Open = true // a CLOSED overlay renders nothing at all -- see TestRenderIsEmptyWhenClosed
	if got := s.Render(80); got == "" || !contains(got, "Loading") {
		t.Fatalf("pending must render Loading, got %q", got)
	}
	s.SetSkills(nil) // an EMPTY reply is still a reply
	if !s.Loaded {
		t.Fatal("an empty reply must mark Loaded")
	}
	if got := s.Render(80); contains(got, "Loading") {
		t.Fatal("an empty registry must not render as Loading")
	}
}

func TestRenderIsEmptyWhenClosed(t *testing.T) {
	s := NewSkillBridge()
	s.SetSkills(sample())
	if s.Render(80) != "" {
		t.Fatal("a closed overlay must render nothing")
	}
}

func contains(hay, needle string) bool {
	return len(hay) >= len(needle) && (func() bool {
		for i := 0; i+len(needle) <= len(hay); i++ {
			if hay[i:i+len(needle)] == needle {
				return true
			}
		}
		return false
	})()
}

// #5959 — found by a live DOM drive of the cockpit, which shares this filter logic.
// A human types "forge", not "F.O.R.G.E.". The original test searched WITH the dots,
// so it passed while the real filter returned zero rows.
func TestDirectorFilterMatchesTheUndottedName(t *testing.T) {
	s := NewSkillBridge()
	s.SetSkills(sample())

	for _, typed := range []string{"forge", "FORGE", "f.o.r.g.e.", "F.O.R.G.E."} {
		s.SetFilter(typed)
		got := s.Visible()
		if len(got) != 1 || got[0].Capability != "code_review" {
			t.Fatalf("typing %q must find F.O.R.G.E.'s row, got %v", typed, got)
		}
	}
	s.SetFilter("codex")
	if got := s.Visible(); len(got) != 1 || got[0].Capability != "documentation" {
		t.Fatalf("typing \"codex\" must find C.O.D.E.X.'s row, got %v", got)
	}
}
