package main

import (
	"flag"
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"
)

var version = "0.1.0"

func main() {
	wsURL := flag.String("url", "ws://127.0.0.1:9090", "Engine WebSocket URL")
	showVersion := flag.Bool("version", false, "Show version")
	flag.Parse()

	if *showVersion {
		fmt.Printf("ARCHIE Code CLI v%s\n", version)
		os.Exit(0)
	}

	p := tea.NewProgram(
		initialModel(*wsURL),
		tea.WithAltScreen(),
	)

	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}
