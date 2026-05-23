package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestStripeCheckoutEmbeddedSessionAndWebhook(t *testing.T) {
	oldStripeSvc := stripeSvc
	oldWebhookSecret := stripeWebhookSecret
	t.Cleanup(func() {
		stripeSvc = oldStripeSvc
		stripeWebhookSecret = oldWebhookSecret
	})

	sessionID := fmt.Sprintf("cs_test_%d", time.Now().UnixNano())
	customerID := "cus_local_embedded"
	paymentIntentID := "pi_local_embedded"
	checkoutEmail := fmt.Sprintf("stripe-checkout-%d@example.com", time.Now().UnixNano())
	paymentMethodID := "pm_card_visa"
	var createdSessionForm map[string]string

	stripeMock := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost && r.Method != http.MethodGet {
			t.Fatalf("unexpected Stripe method %s", r.Method)
		}
		w.Header().Set("Content-Type", "application/json")

		switch r.URL.Path {
		case "/v1/customers":
			if err := r.ParseForm(); err != nil {
				t.Fatalf("parse customer form: %v", err)
			}
			if got := r.Form.Get("email"); got != checkoutEmail {
				t.Fatalf("customer email = %q, want %q", got, checkoutEmail)
			}
			if r.Form.Get("metadata[wallet_address]") == "" {
				t.Fatalf("customer missing wallet metadata: %v", r.Form)
			}
			_, _ = w.Write([]byte(`{"id":"` + customerID + `"}`))
		case "/v1/checkout/sessions":
			if err := r.ParseForm(); err != nil {
				t.Fatalf("parse checkout form: %v", err)
			}
			createdSessionForm = map[string]string{}
			for k, v := range r.Form {
				if len(v) > 0 {
					createdSessionForm[k] = v[0]
				}
			}
			if got := r.Form.Get("ui_mode"); got != "embedded_page" {
				t.Fatalf("ui_mode = %q, want embedded_page", got)
			}
			if got := r.Form.Get("return_url"); !strings.Contains(got, "{CHECKOUT_SESSION_ID}") {
				t.Fatalf("return_url missing checkout placeholder: %q", got)
			}
			if got := r.Form.Get("success_url"); got != "" {
				t.Fatalf("embedded checkout should not send success_url, got %q", got)
			}
			if got := r.Form.Get("cancel_url"); got != "" {
				t.Fatalf("embedded checkout should not send cancel_url, got %q", got)
			}
			if got := r.Form.Get("payment_intent_data[setup_future_usage]"); got != "off_session" {
				t.Fatalf("setup_future_usage = %q, want off_session", got)
			}
			if got := r.Form.Get("line_items[0][price_data][unit_amount]"); got != "2500" {
				t.Fatalf("unit amount = %q, want 2500", got)
			}
			_, _ = w.Write([]byte(`{"id":"` + sessionID + `","customer":"` + customerID + `","client_secret":"` + sessionID + `_secret_local","amount_total":2500}`))
		case "/v1/payment_intents/" + paymentIntentID:
			_, _ = w.Write([]byte(`{"id":"` + paymentIntentID + `","status":"succeeded","payment_method":"` + paymentMethodID + `"}`))
		default:
			t.Fatalf("unexpected Stripe path %s", r.URL.Path)
		}
	}))
	defer stripeMock.Close()

	stripeSvc = &stripeService{
		secretKey: "sk_test_local",
		baseURL:   stripeMock.URL,
		client:    stripeMock.Client(),
	}
	stripeWebhookSecret = ""
	t.Setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_local")

	wallet := fmt.Sprintf("StripeWallet_%d", time.Now().UnixNano())
	status, body := doPost(t, "/api/auth/wallet", map[string]string{"wallet_address": wallet})
	if status != 200 {
		t.Fatalf("register wallet: status %d body %v", status, body)
	}
	user, err := dbConn.GetUserByWallet(wallet)
	if err != nil {
		t.Fatalf("get user: %v", err)
	}

	status, body = doPost(t, "/api/stripe-checkout", map[string]interface{}{
		"wallet_address": wallet,
		"amount_usd":     25,
		"return_url":     "http://localhost:3000/?payment=success&session_id={CHECKOUT_SESSION_ID}#credits",
	})
	if status != 400 {
		t.Fatalf("checkout without email status %d body %v", status, body)
	}

	status, body = doPost(t, "/api/auth/email", map[string]string{
		"wallet_address": wallet,
		"email":          checkoutEmail,
		"password":       "stripe-checkout-123",
	})
	if status != 200 {
		t.Fatalf("save checkout email: status %d body %v", status, body)
	}
	user, err = dbConn.GetUserByWallet(wallet)
	if err != nil {
		t.Fatalf("get user after email: %v", err)
	}

	status, body = doPost(t, "/api/stripe-checkout", map[string]interface{}{
		"wallet_address": wallet,
		"amount_usd":     25,
		"return_url":     "http://localhost:3000/?payment=success&session_id={CHECKOUT_SESSION_ID}#credits",
	})
	if status != 200 {
		t.Fatalf("checkout status %d body %v", status, body)
	}
	if body["ui_mode"] != "embedded_page" {
		t.Fatalf("ui_mode response = %v", body["ui_mode"])
	}
	if body["client_secret"] != sessionID+"_secret_local" {
		t.Fatalf("client_secret = %v", body["client_secret"])
	}
	if body["publishable_key"] != "pk_test_local" {
		t.Fatalf("publishable_key = %v", body["publishable_key"])
	}
	if createdSessionForm["metadata[user_id]"] != user.ID {
		t.Fatalf("session metadata user_id = %q, want %q", createdSessionForm["metadata[user_id]"], user.ID)
	}

	cutePriceMu.Lock()
	oldCutePrice := cutePriceUSD
	cutePriceUSD = 0.01
	cutePriceMu.Unlock()
	t.Cleanup(func() {
		cutePriceMu.Lock()
		cutePriceUSD = oldCutePrice
		cutePriceMu.Unlock()
	})

	event := map[string]interface{}{
		"id":   "evt_local_checkout",
		"type": "checkout.session.completed",
		"data": map[string]interface{}{
			"object": map[string]interface{}{
				"id":             sessionID,
				"customer":       customerID,
				"payment_intent": paymentIntentID,
				"payment_status": "paid",
				"amount_total":   2500,
				"metadata": map[string]string{
					"user_id":        user.ID,
					"wallet_address": wallet,
					"amount_usd":     "25.00",
					"type":           "credits_purchase",
				},
			},
		},
	}
	status, body = doPost(t, "/api/stripe-webhook", event)
	if status != 200 {
		raw, _ := json.Marshal(body)
		t.Fatalf("webhook status %d body %s", status, raw)
	}

	status, body = doGet(t, "/api/balance?wallet="+wallet)
	if status != 200 {
		t.Fatalf("balance status %d body %v", status, body)
	}
	credits, err := strconv.ParseFloat(fmt.Sprint(body["credits"]), 64)
	if err != nil {
		t.Fatalf("credits parse: %v body=%v", err, body)
	}
	if credits < 2499 || credits > 2501 {
		t.Fatalf("credits = %f, want about 2500", credits)
	}
	if body["has_payment_method"] != true {
		t.Fatalf("expected saved Stripe payment method, body=%v", body)
	}

	status, body = doPost(t, "/api/stripe-webhook", event)
	if status != 200 {
		t.Fatalf("second webhook status %d body %v", status, body)
	}
	status, body = doGet(t, "/api/balance?wallet="+wallet)
	if status != 200 {
		t.Fatalf("second balance status %d body %v", status, body)
	}
	creditsAfterReplay, _ := strconv.ParseFloat(fmt.Sprint(body["credits"]), 64)
	if creditsAfterReplay != credits {
		t.Fatalf("webhook replay changed credits: before=%f after=%f", credits, creditsAfterReplay)
	}
}

func TestStripeSubscriptionCheckoutActivatesUnlimitedAPI(t *testing.T) {
	oldStripeSvc := stripeSvc
	oldWebhookSecret := stripeWebhookSecret
	t.Cleanup(func() {
		stripeSvc = oldStripeSvc
		stripeWebhookSecret = oldWebhookSecret
	})

	sessionID := fmt.Sprintf("cs_sub_%d", time.Now().UnixNano())
	customerID := "cus_local_subscription"
	subscriptionID := "sub_local_subscription"
	priceID := "price_1TZQWbQda7Fr1LvlkbnwaYpg"
	var checkoutPrice string

	stripeMock := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/v1/customers":
			_, _ = w.Write([]byte(`{"id":"` + customerID + `"}`))
		case "/v1/checkout/sessions":
			if err := r.ParseForm(); err != nil {
				t.Fatalf("parse checkout form: %v", err)
			}
			if got := r.Form.Get("mode"); got != "subscription" {
				t.Fatalf("mode = %q, want subscription", got)
			}
			if got := r.Form.Get("ui_mode"); got != "embedded_page" {
				t.Fatalf("ui_mode = %q, want embedded_page", got)
			}
			checkoutPrice = r.Form.Get("line_items[0][price]")
			_, _ = w.Write([]byte(`{"id":"` + sessionID + `","mode":"subscription","customer":"` + customerID + `","subscription":"` + subscriptionID + `","client_secret":"` + sessionID + `_secret_sub"}`))
		case "/v1/subscriptions/" + subscriptionID:
			_, _ = w.Write([]byte(`{"id":"` + subscriptionID + `","customer":"` + customerID + `","status":"active","current_period_end":1893456000,"items":{"data":[{"price":{"id":"` + priceID + `"}}]},"metadata":{"plan":"monthly"}}`))
		default:
			t.Fatalf("unexpected Stripe path %s", r.URL.Path)
		}
	}))
	defer stripeMock.Close()

	stripeSvc = &stripeService{
		secretKey: "sk_test_local",
		baseURL:   stripeMock.URL,
		client:    stripeMock.Client(),
	}
	stripeWebhookSecret = ""
	t.Setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_local")
	t.Setenv("STRIPE_MONTHLY_PRICE_ID", priceID)

	wallet := fmt.Sprintf("StripeSubWallet_%d", time.Now().UnixNano())
	status, body := doPost(t, "/api/auth/wallet", map[string]string{"wallet_address": wallet})
	if status != 200 {
		t.Fatalf("register wallet: status %d body %v", status, body)
	}
	user, err := dbConn.GetUserByWallet(wallet)
	if err != nil {
		t.Fatalf("get user: %v", err)
	}

	status, body = doPost(t, "/api/stripe-checkout", map[string]interface{}{
		"wallet_address": wallet,
		"type":           "subscription",
		"plan":           "monthly",
		"return_url":     "http://localhost:3000/account?payment=success&session_id={CHECKOUT_SESSION_ID}",
	})
	if status != 200 {
		t.Fatalf("subscription checkout status %d body %v", status, body)
	}
	if body["type"] != "subscription" {
		t.Fatalf("response type = %v", body["type"])
	}
	if checkoutPrice != priceID {
		t.Fatalf("checkout price = %q, want %q", checkoutPrice, priceID)
	}

	event := map[string]interface{}{
		"id":   "evt_local_subscription_checkout",
		"type": "checkout.session.completed",
		"data": map[string]interface{}{
			"object": map[string]interface{}{
				"id":             sessionID,
				"mode":           "subscription",
				"customer":       customerID,
				"subscription":   subscriptionID,
				"payment_status": "paid",
				"metadata": map[string]string{
					"user_id":        user.ID,
					"wallet_address": wallet,
					"type":           "subscription",
					"plan":           "monthly",
					"price_id":       priceID,
				},
			},
		},
	}
	status, body = doPost(t, "/api/stripe-webhook", event)
	if status != 200 {
		t.Fatalf("subscription webhook status %d body %v", status, body)
	}

	status, body = doGet(t, "/api/balance?wallet="+wallet)
	if status != 200 {
		t.Fatalf("balance status %d body %v", status, body)
	}
	if body["unlimited_api"] != true {
		t.Fatalf("expected unlimited_api after subscription, body=%v", body)
	}
	if body["subscription_plan"] != "monthly" {
		t.Fatalf("subscription_plan = %v", body["subscription_plan"])
	}

	deletedEvent := map[string]interface{}{
		"id":   "evt_local_subscription_deleted",
		"type": "customer.subscription.deleted",
		"data": map[string]interface{}{
			"object": map[string]interface{}{
				"id":                   subscriptionID,
				"customer":             customerID,
				"status":               "canceled",
				"current_period_end":   1893456000,
				"items":                map[string]interface{}{"data": []interface{}{map[string]interface{}{"price": map[string]interface{}{"id": priceID}}}},
				"cancel_at_period_end": false,
			},
		},
	}
	status, body = doPost(t, "/api/stripe-webhook", deletedEvent)
	if status != 200 {
		t.Fatalf("subscription deleted webhook status %d body %v", status, body)
	}
	status, body = doGet(t, "/api/balance?wallet="+wallet)
	if status != 200 {
		t.Fatalf("balance after delete status %d body %v", status, body)
	}
	if body["unlimited_api"] != false {
		t.Fatalf("expected unlimited_api false after cancellation, body=%v", body)
	}
}
