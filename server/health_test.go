package main

import (
	"errors"
	"testing"
)

type healthPingerFunc func() error

func (fn healthPingerFunc) Ping() error { return fn() }

func TestHealthStatusRequiresDatabaseReadiness(t *testing.T) {
	status, body := healthStatus(healthPingerFunc(func() error {
		return errors.New("database system is in recovery mode")
	}))
	if status != 503 {
		t.Fatalf("status = %d, want 503", status)
	}
	if body["status"] != "degraded" || body["database"] != "unavailable" {
		t.Fatalf("unexpected degraded response: %#v", body)
	}

	status, body = healthStatus(healthPingerFunc(func() error { return nil }))
	if status != 200 {
		t.Fatalf("status = %d, want 200", status)
	}
	if body["status"] != "ok" || body["database"] != "ok" {
		t.Fatalf("unexpected ready response: %#v", body)
	}
}
