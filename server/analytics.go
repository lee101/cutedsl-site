package main

import (
	"bytes"
	"encoding/json"
	"log"
	"net/http"
	"testing"
	"time"
)

const thWriteKey = "thw_7fwTDwXBYrLeDq4mob3NytcXhB4BqyxU"

const thHeadSnippet = `<script>window.__thConfig={siteId:'` + thWriteKey + `'};window.th=window.th||function(){(window.th.q=window.th.q||[]).push(arguments)};</script>
<script async src="https://twohelixes.com/static/th.js"></script>
`

var (
	thCollectURL = "https://twohelixes.com/v1/collect"
	thHTTPClient = &http.Client{Timeout: 5 * time.Second}
)

type thEvent struct {
	Name      string
	UserID    string
	ClientID  string
	SessionID string
	EventID   string
	Props     map[string]interface{}
}

func thEventPayload(e thEvent) map[string]interface{} {
	clientID := e.ClientID
	if clientID == "" {
		clientID = e.UserID
	}
	ev := map[string]interface{}{
		"event":     e.Name,
		"client_id": clientID,
		"user_id":   e.UserID,
		"ts":        time.Now().UnixMilli(),
		"props":     e.Props,
	}
	if e.SessionID != "" {
		ev["session_id"] = e.SessionID
	}
	if e.EventID != "" {
		ev["event_id"] = e.EventID
	}
	return map[string]interface{}{"site_id": thWriteKey, "events": []interface{}{ev}}
}

func trackServerEvent(e thEvent) {
	if testing.Testing() || e.UserID == "" && e.ClientID == "" {
		return
	}
	body, err := json.Marshal(thEventPayload(e))
	if err != nil {
		return
	}
	go func() {
		resp, err := thHTTPClient.Post(thCollectURL, "text/plain", bytes.NewReader(body))
		if err != nil {
			log.Printf("twohelixes %s: %v", e.Name, err)
			return
		}
		resp.Body.Close()
	}()
}

func trackStripePurchase(session stripeCheckoutSession, userID, plan string, revenue float64) {
	md := session.Metadata
	trackServerEvent(thEvent{
		Name:      "purchase",
		UserID:    userID,
		ClientID:  md["th_cid"],
		SessionID: md["th_sid"],
		EventID:   "stripe:" + session.ID,
		Props: map[string]interface{}{
			"plan":           plan,
			"revenue":        revenue,
			"currency":       "USD",
			"transaction_id": session.ID,
			"surface":        md["th_surface"],
			"method":         "stripe",
		},
	})
}
