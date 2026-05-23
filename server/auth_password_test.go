package main

import (
	"fmt"
	"testing"
	"time"
)

func TestEmailPasswordForgotResetFlowE2E(t *testing.T) {
	email := fmt.Sprintf("reset-%d@example.com", time.Now().UnixNano())
	password := "correct-horse-1"
	newPassword := "new-correct-horse-2"

	status, body := doPost(t, "/api/auth/email-login", map[string]string{
		"email":    email,
		"password": password,
	})
	if status != 200 {
		t.Fatalf("initial email login status %d body %v", status, body)
	}
	if body["api_key"] == "" {
		t.Fatalf("expected api_key on initial login: %v", body)
	}

	status, body = doPost(t, "/api/auth/email-login", map[string]string{
		"email":    email,
		"password": "wrong-password",
	})
	if status != 401 {
		t.Fatalf("wrong password status %d body %v", status, body)
	}

	status, body = doPost(t, "/api/auth/forgot-password", map[string]string{"email": email})
	if status != 200 {
		t.Fatalf("forgot password status %d body %v", status, body)
	}
	token, _ := body["reset_token"].(string)
	if token == "" {
		t.Fatalf("expected reset_token in dev/test mode: %v", body)
	}

	status, body = doPost(t, "/api/auth/reset-password", map[string]string{
		"token":    token,
		"password": newPassword,
	})
	if status != 200 {
		t.Fatalf("reset password status %d body %v", status, body)
	}
	if body["api_key"] == "" {
		t.Fatalf("expected api_key after reset: %v", body)
	}

	status, body = doPost(t, "/api/auth/reset-password", map[string]string{
		"token":    token,
		"password": "another-password",
	})
	if status != 400 {
		t.Fatalf("reused reset token status %d body %v", status, body)
	}

	status, body = doPost(t, "/api/auth/email-login", map[string]string{
		"email":    email,
		"password": password,
	})
	if status != 401 {
		t.Fatalf("old password after reset status %d body %v", status, body)
	}

	status, body = doPost(t, "/api/auth/email-login", map[string]string{
		"email":    email,
		"password": newPassword,
	})
	if status != 200 {
		t.Fatalf("new password login status %d body %v", status, body)
	}
}
