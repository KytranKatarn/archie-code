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

	var lines []string
	for _, msg := range c.Messages {
		switch msg.Role {
		case "user":
			lines = append(lines, text.Render(fmt.Sprintf("  > %s", msg.Content)))
		case "assistant":
			lines = append(lines, cyan.Render(fmt.Sprintf("  %s", msg.Content)))
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
