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

func TestWalletCanAddEmailPasswordAndLoginForStripe(t *testing.T) {
	wallet := fmt.Sprintf("WalletPassword_%d", time.Now().UnixNano())
	email := fmt.Sprintf("wallet-password-%d@example.com", time.Now().UnixNano())
	password := "wallet-card-123"

	status, body := doPost(t, "/api/auth/wallet", map[string]string{
		"wallet_address": wallet,
	})
	if status != 200 {
		t.Fatalf("wallet auth status %d body %v", status, body)
	}
	apiKey, _ := body["api_key"].(string)
	if apiKey == "" {
		t.Fatalf("expected api key: %v", body)
	}

	status, body = doPost(t, "/api/auth/email", map[string]string{
		"wallet_address": wallet,
		"email":          email,
		"password":       password,
	})
	if status != 200 {
		t.Fatalf("update email/password status %d body %v", status, body)
	}
	if body["has_password"] != true {
		t.Fatalf("expected has_password=true: %v", body)
	}

	status, body = doPost(t, "/api/auth/email-login", map[string]string{
		"email":    email,
		"password": password,
	})
	if status != 200 {
		t.Fatalf("email login status %d body %v", status, body)
	}
	user := body["user"].(map[string]interface{})
	if user["wallet_address"] != wallet {
		t.Fatalf("email login should return linked wallet %s, got %v", wallet, user["wallet_address"])
	}
	if body["api_key"] != apiKey {
		t.Fatalf("expected original api key after email login, got %v want %v", body["api_key"], apiKey)
	}

	status, body = doPost(t, "/api/auth/email-login", map[string]string{
		"email":    email,
		"password": "wrong-card-123",
	})
	if status != 401 {
		t.Fatalf("wrong linked password status %d body %v", status, body)
	}
}

func TestEmailAccountCanLinkSolanaWalletWithAPIKey(t *testing.T) {
	email := fmt.Sprintf("link-wallet-%d@example.com", time.Now().UnixNano())
	password := "link-wallet-123"
	wallet := fmt.Sprintf("LinkedWallet_%d", time.Now().UnixNano())

	status, body := doPost(t, "/api/auth/email-login", map[string]string{
		"email":    email,
		"password": password,
	})
	if status != 200 {
		t.Fatalf("email signup status %d body %v", status, body)
	}
	apiKey, _ := body["api_key"].(string)
	user := body["user"].(map[string]interface{})
	userID, _ := user["id"].(string)
	if apiKey == "" || userID == "" {
		t.Fatalf("expected email user and api key: %v", body)
	}
	if _, err := dbConn.AddPurchasedCredits(userID, 42); err != nil {
		t.Fatalf("seed email credits: %v", err)
	}

	status, body = doPost(t, "/api/auth/wallet", map[string]string{
		"wallet_address": wallet,
		"api_key":        apiKey,
	})
	if status != 200 {
		t.Fatalf("wallet link status %d body %v", status, body)
	}
	linkedUser := body["user"].(map[string]interface{})
	if linkedUser["wallet_address"] != wallet {
		t.Fatalf("expected linked wallet %s, got %v", wallet, linkedUser["wallet_address"])
	}

	status, body = doGet(t, "/api/balance?wallet="+wallet)
	if status != 200 {
		t.Fatalf("balance status %d body %v", status, body)
	}
	if body["credits"].(float64) != 42 {
		t.Fatalf("expected linked credits 42, got %v", body["credits"])
	}

	status, body = doPost(t, "/api/auth/email-login", map[string]string{
		"email":    email,
		"password": password,
	})
	if status != 200 {
		t.Fatalf("email login after link status %d body %v", status, body)
	}
	user = body["user"].(map[string]interface{})
	if user["wallet_address"] != wallet {
		t.Fatalf("email login should resolve linked wallet %s, got %v", wallet, user["wallet_address"])
	}
}
