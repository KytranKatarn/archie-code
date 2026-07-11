package main

import "testing"

func TestPalette(t *testing.T) {
	p := NewPalette([]string{"code", "code_review", "documentation", "security"})
	p.SetFilter("code")
	if got := p.Visible(); len(got) != 2 {
		t.Fatalf("filter 'code' should match code + code_review, got %v", got)
	}
	p.SetFilter("")
	if got := p.Visible(); len(got) != 4 {
		t.Fatalf("empty filter should show all 4, got %d", len(got))
	}
	p.SetFilter("sec")
	if got := p.Visible(); len(got) != 1 || got[0] != "security" {
		t.Fatalf("filter 'sec' should match security only, got %v", got)
	}
}
