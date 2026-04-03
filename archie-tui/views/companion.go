package views

import (
	"time"
)

// CompanionState represents the current expression.
type CompanionState int

const (
	StateIdle CompanionState = iota
	StateThinking
	StateHappy
	StateConcerned
	StateSurprised
	StateFocused
	StateSleeping
)

// CompanionView is the ASCII companion widget.
type CompanionView struct {
	State      CompanionState
	StatusText string
	blinking   bool
	swayRight  bool
	lastInput  time.Time
	Width      int
	Height     int
}

// NewCompanionView creates a companion in idle state.
func NewCompanionView() *CompanionView {
	return &CompanionView{
		State:      StateIdle,
		StatusText: "✦ ready",
		lastInput:  time.Now(),
	}
}

// BlinkTickMsg triggers a blink animation frame.
type BlinkTickMsg struct{}

// BlinkEndMsg ends the blink animation frame.
type BlinkEndMsg struct{}

// SwayTickMsg triggers a hair sway animation.
type SwayTickMsg struct{}

// SleepCheckMsg checks if companion should sleep.
type SleepCheckMsg struct{}
