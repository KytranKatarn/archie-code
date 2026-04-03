package views

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/lipgloss"
)

type ChatMessage struct {
	Role    string
	Content string
}

type ChatView struct {
	Messages []ChatMessage
	Width    int
	Height   int
}

func NewChatView() *ChatView {
	return &ChatView{Messages: []ChatMessage{}}
}

func (c *ChatView) AddMessage(role, content string) {
	c.Messages = append(c.Messages, ChatMessage{Role: role, Content: content})
}

func (c *ChatView) Render() string {
	if len(c.Messages) == 0 {
		dim := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280"))
		return dim.Render("  No messages yet. Type a message or /command to begin.")
	}

	cyan := lipgloss.NewStyle().Foreground(lipgloss.Color("#00e5ff"))
	text := lipgloss.NewStyle().Foreground(lipgloss.Color("#e5e7eb"))
	dimStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280")).Italic(true)

	maxWidth := c.Width - 4 // 2 chars padding each side
	if maxWidth < 20 {
		maxWidth = 80
	}

	var lines []string
	for _, msg := range c.Messages {
		switch msg.Role {
		case "user":
			wrapped := wordWrap(msg.Content, maxWidth-2) // account for "> " prefix
			for i, line := range strings.Split(wrapped, "\n") {
				if i == 0 {
					lines = append(lines, text.Render(fmt.Sprintf("  > %s", line)))
				} else {
					lines = append(lines, text.Render(fmt.Sprintf("    %s", line)))
				}
			}
		case "assistant":
			wrapped := wordWrap(msg.Content, maxWidth)
			for _, line := range strings.Split(wrapped, "\n") {
				lines = append(lines, cyan.Render(fmt.Sprintf("  %s", line)))
			}
		case "system":
			lines = append(lines, dimStyle.Render(fmt.Sprintf("  [%s]", msg.Content)))
		}
		lines = append(lines, "")
	}

	if c.Height > 0 && len(lines) > c.Height {
		lines = lines[len(lines)-c.Height:]
	}

	return strings.Join(lines, "\n")
}

// wordWrap breaks text into lines that fit within maxWidth characters.
func wordWrap(text string, maxWidth int) string {
	if maxWidth <= 0 {
		return text
	}
	var result strings.Builder
	for _, paragraph := range strings.Split(text, "\n") {
		if result.Len() > 0 {
			result.WriteString("\n")
		}
		words := strings.Fields(paragraph)
		if len(words) == 0 {
			continue
		}
		lineLen := 0
		for i, word := range words {
			wl := len(word)
			if i > 0 && lineLen+1+wl > maxWidth {
				result.WriteString("\n")
				lineLen = 0
			} else if i > 0 {
				result.WriteString(" ")
				lineLen++
			}
			result.WriteString(word)
			lineLen += wl
		}
	}
	return result.String()
}
