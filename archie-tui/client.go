package main

import (
	"encoding/json"
	"fmt"
	"log"
	"sync"

	"github.com/gorilla/websocket"
)

type Client struct {
	conn      *websocket.Conn
	url       string
	mu        sync.Mutex
	onMessage func(map[string]interface{})
}

func NewClient(url string) *Client {
	return &Client{url: url}
}

func (c *Client) Connect() error {
	conn, _, err := websocket.DefaultDialer.Dial(c.url, nil)
	if err != nil {
		return fmt.Errorf("connect failed: %w", err)
	}
	c.conn = conn
	go c.readLoop()
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
	msg := map[string]interface{}{"type": "message", "content": content}
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

func (c *Client) SetOnMessage(fn func(map[string]interface{})) {
	c.onMessage = fn
}

func (c *Client) readLoop() {
	defer c.Close()
	for {
		_, message, err := c.conn.ReadMessage()
		if err != nil {
			log.Printf("read error: %v", err)
			return
		}
		var msg map[string]interface{}
		if err := json.Unmarshal(message, &msg); err != nil {
			log.Printf("unmarshal error: %v", err)
			continue
		}
		if c.onMessage != nil {
			c.onMessage(msg)
		}
	}
}
