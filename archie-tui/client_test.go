package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

func startTestWSServer(onConn func(*websocket.Conn)) (string, *httptest.Server) {
	upgrader := websocket.Upgrader{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		c, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		onConn(c)
	}))
	return "ws" + strings.TrimPrefix(srv.URL, "http"), srv
}

// TestClientDeliversBurstWithoutLoss is the regression guard for the critical
// deadlock: the engine sends several responses back-to-back on connect (session
// handshake) and on repo pick. The old per-message SetOnMessage channel lost
// messages in the registration gap and could wedge the read loop entirely.
func TestClientDeliversBurstWithoutLoss(t *testing.T) {
	const n = 12
	url, srv := startTestWSServer(func(c *websocket.Conn) {
		for i := 0; i < n; i++ {
			_ = c.WriteJSON(map[string]interface{}{"type": "response", "content": "m"})
		}
		time.Sleep(200 * time.Millisecond) // keep the conn up so all frames land
		_ = c.Close()
	})
	defer srv.Close()

	client := NewClient(url)
	if err := client.Connect(); err != nil {
		t.Fatalf("connect: %v", err)
	}
	defer client.Close()

	got := 0
	timeout := time.After(3 * time.Second)
	for got < n {
		select {
		case <-client.Messages():
			got++
		case err := <-client.Errs():
			t.Fatalf("unexpected disconnect after %d/%d messages: %v", got, n, err)
		case <-timeout:
			t.Fatalf("received only %d/%d messages before timeout — message loss / deadlock", got, n)
		}
	}
}

// TestClientPropagatesDisconnect guards the "UI shows connected while silently
// dropping messages" bug: a dropped connection must surface on Errs().
func TestClientPropagatesDisconnect(t *testing.T) {
	url, srv := startTestWSServer(func(c *websocket.Conn) {
		_ = c.Close()
	})
	defer srv.Close()

	client := NewClient(url)
	if err := client.Connect(); err != nil {
		t.Fatalf("connect: %v", err)
	}
	defer client.Close()

	select {
	case err := <-client.Errs():
		if err == nil {
			t.Fatal("expected a non-nil disconnect error")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("disconnect was never propagated — UI would stay 'connected'")
	}
}

// Task 4: the REPL opts into progress streaming so the engine emits intermediate
// frames. The wire frame must carry stream:true (plus the legacy fields), while
// a plain client that omits it stays one-shot (engine-side backward compat).
func TestSendMessageOptsIntoStreaming(t *testing.T) {
	got := make(chan map[string]interface{}, 1)
	url, srv := startTestWSServer(func(c *websocket.Conn) {
		var m map[string]interface{}
		_ = c.ReadJSON(&m)
		got <- m
	})
	defer srv.Close()

	client := NewClient(url)
	if err := client.Connect(); err != nil {
		t.Fatalf("connect: %v", err)
	}
	defer client.Close()

	if err := client.SendMessage("hello", "s1"); err != nil {
		t.Fatalf("send: %v", err)
	}

	select {
	case m := <-got:
		if m["type"] != "message" || m["content"] != "hello" || m["session_id"] != "s1" {
			t.Fatalf("unexpected message frame: %+v", m)
		}
		if stream, _ := m["stream"].(bool); !stream {
			t.Fatalf("SendMessage must opt into streaming (stream:true): %+v", m)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("message frame never received")
	}
}
