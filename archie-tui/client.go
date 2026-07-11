package main

import (
	"encoding/json"
	"fmt"
	"sync"

	"github.com/gorilla/websocket"
)

// Client is a thin websocket client to the archie_engine. Decoded engine
// messages are delivered on a single, persistent buffered channel (Messages);
// a read-loop failure is reported once on Errs. This replaces the previous
// per-message SetOnMessage re-registration, which lost messages arriving
// between listener registrations and could deadlock the read loop entirely.
type Client struct {
	url      string
	mu       sync.Mutex
	conn     *websocket.Conn
	messages chan map[string]interface{}
	errs     chan error
}

func NewClient(url string) *Client {
	return &Client{
		url:      url,
		messages: make(chan map[string]interface{}, 64),
		errs:     make(chan error, 1),
	}
}

func (c *Client) Connect() error {
	conn, _, err := websocket.DefaultDialer.Dial(c.url, nil)
	if err != nil {
		return fmt.Errorf("connect failed: %w", err)
	}
	c.mu.Lock()
	c.conn = conn
	c.mu.Unlock()
	go c.readLoop(conn)
	return nil
}

func (c *Client) Send(msg map[string]interface{}) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.conn == nil {
		return fmt.Errorf("not connected")
	}
	data, err := json.Marshal(msg)
	if err != nil {
		return err
	}
	return c.conn.WriteMessage(websocket.TextMessage, data)
}

func (c *Client) SendMessage(content string, sessionID string) error {
	// Opt into progress streaming (Task 4): the engine emits intermediate
	// `progress` frames before the final `response`. Engine-side this is gated on
	// stream:true, so clients that omit it stay one-shot (backward compat).
	msg := map[string]interface{}{"type": "message", "content": content, "stream": true}
	if sessionID != "" {
		msg["session_id"] = sessionID
	}
	return c.Send(msg)
}

func (c *Client) Close() {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.conn != nil {
		c.conn.Close()
		c.conn = nil
	}
}

// Messages is the single persistent stream of decoded engine messages.
func (c *Client) Messages() <-chan map[string]interface{} { return c.messages }

// Errs delivers the read-loop failure (disconnect) that ends the live
// connection, so the UI can leave "connected" state instead of silently
// dropping the user's messages.
func (c *Client) Errs() <-chan error { return c.errs }

func (c *Client) readLoop(conn *websocket.Conn) {
	for {
		_, message, err := conn.ReadMessage()
		if err != nil {
			c.mu.Lock()
			// Only surface a disconnect for the connection that is still live;
			// a conn already replaced by Close()/reconnect is expected to end.
			live := c.conn == conn
			if live {
				c.conn = nil
			}
			c.mu.Unlock()
			if live {
				select {
				case c.errs <- err:
				default:
				}
			}
			return
		}
		var msg map[string]interface{}
		if err := json.Unmarshal(message, &msg); err != nil {
			continue
		}
		// Single persistent reader (listenCmd); the 64-slot buffer absorbs the
		// back-to-back response bursts (connect handshake, repo pick) that used
		// to wedge the old per-message channel.
		c.messages <- msg
	}
}
