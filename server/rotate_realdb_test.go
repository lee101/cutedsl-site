package main

import (
	"os"
	"strings"
	"testing"
)

// TestRotateAPIKey_RealUser exercises POST /api/auth/rotate-api-key against the
// REAL production database for a specific account. It is gated behind
// REAL_DB_TEST=1 so it never runs in normal CI (it permanently rotates the key).
//
// Run with:
//
//	REAL_DB_TEST=1 \
//	REAL_DATABASE_URL='postgres://cutedsl:...@localhost:5432/cutedsl?sslmode=disable' \
//	ROTATE_TEST_EMAIL='leepenkman@gmail.com' \
//	go test ./server -run TestRotateAPIKey_RealUser -v
func TestRotateAPIKey_RealUser(t *testing.T) {
	if os.Getenv("REAL_DB_TEST") != "1" {
		t.Skip("set REAL_DB_TEST=1 to run the real-database rotation test")
	}

	realDSN := os.Getenv("REAL_DATABASE_URL")
	if realDSN == "" {
		t.Fatal("REAL_DATABASE_URL is required")
	}
	email := os.Getenv("ROTATE_TEST_EMAIL")
	if email == "" {
		email = "leepenkman@gmail.com"
	}

	// Point the shared handler at the real DB for the duration of this test.
	realDB, err := NewDB(realDSN)
	if err != nil {
		t.Fatalf("connect real db: %v", err)
	}
	prev := dbConn
	dbConn = realDB
	t.Cleanup(func() {
		dbConn = prev
		realDB.Close()
	})

	user, err := dbConn.GetUserByEmail(email)
	if err != nil {
		t.Fatalf("lookup %s: %v", email, err)
	}
	oldKey := user.APIKey
	wallet := user.WalletAddress
	t.Logf("user=%s wallet=%s oldKey=%s", email, wallet, oldKey)

	// 1) Wrong key is rejected.
	status, body := doPost(t, "/api/auth/rotate-api-key", map[string]interface{}{
		"wallet_address": wallet,
		"api_key":        "cutedsl_not-the-real-key",
	})
	if status != 403 {
		t.Fatalf("wrong-key rotate: expected 403, got %d (%v)", status, body)
	}
	t.Logf("wrong-key correctly rejected with 403")

	// Confirm the wrong attempt did not change the stored key.
	if reread, err := dbConn.GetUserByEmail(email); err != nil || reread.APIKey != oldKey {
		t.Fatalf("key changed after a rejected rotate (err=%v)", err)
	}

	// 2) Correct key rotates successfully.
	status, body = doPost(t, "/api/auth/rotate-api-key", map[string]interface{}{
		"wallet_address": wallet,
		"api_key":        oldKey,
	})
	if status != 200 {
		t.Fatalf("rotate: expected 200, got %d (%v)", status, body)
	}
	newKey, _ := body["api_key"].(string)
	if newKey == "" || !strings.HasPrefix(newKey, "cutedsl_") {
		t.Fatalf("rotate returned bad key: %v", body["api_key"])
	}
	if newKey == oldKey {
		t.Fatalf("rotate returned the same key")
	}
	t.Logf("ROTATED OK: newKey=%s", newKey)

	// 3) New key is authoritative; old key no longer resolves.
	if u, err := dbConn.GetUserByAPIKey(newKey); err != nil || u.ID != user.ID {
		t.Fatalf("new key does not resolve to the user (err=%v)", err)
	}
	if _, err := dbConn.GetUserByAPIKey(oldKey); err == nil {
		t.Fatalf("old key still resolves after rotation")
	}
	t.Logf("verified: new key resolves to %s, old key invalidated", email)
}
