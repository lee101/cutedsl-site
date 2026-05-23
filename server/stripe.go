package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/valyala/fasthttp"
)

type stripeService struct {
	secretKey string
	baseURL   string
	client    *http.Client
}

type stripeCheckoutSession struct {
	ID            string            `json:"id"`
	Customer      string            `json:"customer"`
	PaymentIntent string            `json:"payment_intent"`
	Subscription  string            `json:"subscription"`
	Mode          string            `json:"mode"`
	PaymentStatus string            `json:"payment_status"`
	AmountTotal   int64             `json:"amount_total"`
	URL           string            `json:"url"`
	ClientSecret  string            `json:"client_secret"`
	Metadata      map[string]string `json:"metadata"`
}

type stripePaymentIntent struct {
	ID            string `json:"id"`
	Status        string `json:"status"`
	PaymentMethod string `json:"payment_method"`
}

type stripePaymentMethod struct {
	ID   string `json:"id"`
	Card *struct {
		Brand    string `json:"brand"`
		Last4    string `json:"last4"`
		ExpMonth int    `json:"exp_month"`
		ExpYear  int    `json:"exp_year"`
	} `json:"card"`
}

type stripeWebhookEvent struct {
	ID   string `json:"id"`
	Type string `json:"type"`
	Data struct {
		Object json.RawMessage `json:"object"`
	} `json:"data"`
}

type stripeSubscription struct {
	ID                string `json:"id"`
	Customer          string `json:"customer"`
	Status            string `json:"status"`
	CurrentPeriodEnd  int64  `json:"current_period_end"`
	CancelAtPeriodEnd bool   `json:"cancel_at_period_end"`
	LatestInvoice     string `json:"latest_invoice"`
	Items             struct {
		Data []struct {
			Price struct {
				ID string `json:"id"`
			} `json:"price"`
		} `json:"data"`
	} `json:"items"`
	Metadata map[string]string `json:"metadata"`
}

var (
	stripeSvc           *stripeService
	stripeWebhookSecret string
	autoTopupInFlight   sync.Map
)

func stripeCheckoutUIMode() string {
	return getEnv("STRIPE_CHECKOUT_UI_MODE", "embedded_page")
}

func initStripe() {
	secret := strings.TrimSpace(os.Getenv("STRIPE_SECRET_KEY"))
	stripeWebhookSecret = strings.TrimSpace(os.Getenv("STRIPE_WEBHOOK_SECRET"))
	if secret == "" {
		log.Printf("Stripe not configured")
		return
	}
	baseURL := strings.TrimRight(strings.TrimSpace(os.Getenv("STRIPE_API_BASE_URL")), "/")
	if baseURL == "" {
		baseURL = "https://api.stripe.com"
	}
	stripeSvc = &stripeService{
		secretKey: secret,
		baseURL:   baseURL,
		client: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
	log.Printf("Stripe configured")
}

func (s *stripeService) createCustomer(email, wallet string) (string, error) {
	vals := url.Values{}
	if email != "" {
		vals.Set("email", email)
	}
	vals.Set("metadata[wallet_address]", wallet)

	var resp struct {
		ID string `json:"id"`
	}
	if err := s.post("/v1/customers", vals, nil, &resp); err != nil {
		return "", err
	}
	return resp.ID, nil
}

func (s *stripeService) createCheckoutSession(customerID, returnURL string, amountUSDCents int64, metadata map[string]string) (*stripeCheckoutSession, error) {
	vals := url.Values{
		"customer":               {customerID},
		"mode":                   {"payment"},
		"ui_mode":                {stripeCheckoutUIMode()},
		"return_url":             {returnURL},
		"redirect_on_completion": {"if_required"},
		"payment_method_types[]": {"card"},
		"payment_intent_data[setup_future_usage]": {"off_session"},
		"line_items[0][price_data][currency]":     {"usd"},
		"line_items[0][price_data][unit_amount]":  {fmt.Sprintf("%d", amountUSDCents)},
		"line_items[0][quantity]":                 {"1"},
	}
	if productID := strings.TrimSpace(getEnv("STRIPE_CREDITS_PRODUCT_ID", "prod_UYXp470kYWktY7")); productID != "" {
		vals.Set("line_items[0][price_data][product]", productID)
	} else {
		vals.Set("line_items[0][price_data][product_data][name]", "CuteDSL credits")
	}
	for k, v := range metadata {
		vals.Set(fmt.Sprintf("metadata[%s]", k), v)
		vals.Set(fmt.Sprintf("payment_intent_data[metadata][%s]", k), v)
	}

	var resp stripeCheckoutSession
	if err := s.post("/v1/checkout/sessions", vals, nil, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

func (s *stripeService) createSubscriptionCheckoutSession(customerID, returnURL, priceID string, metadata map[string]string) (*stripeCheckoutSession, error) {
	vals := url.Values{
		"customer":                {customerID},
		"mode":                    {"subscription"},
		"ui_mode":                 {stripeCheckoutUIMode()},
		"return_url":              {returnURL},
		"redirect_on_completion":  {"if_required"},
		"line_items[0][price]":    {priceID},
		"line_items[0][quantity]": {"1"},
	}
	for k, v := range metadata {
		vals.Set(fmt.Sprintf("metadata[%s]", k), v)
		vals.Set(fmt.Sprintf("subscription_data[metadata][%s]", k), v)
	}

	var resp stripeCheckoutSession
	if err := s.post("/v1/checkout/sessions", vals, nil, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

func (s *stripeService) retrieveSubscription(id string) (*stripeSubscription, error) {
	var resp stripeSubscription
	path := "/v1/subscriptions/" + url.PathEscape(id) + "?expand[]=items.data.price"
	if err := s.get(path, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

func (s *stripeService) retrievePaymentIntent(id string) (*stripePaymentIntent, error) {
	var resp stripePaymentIntent
	if err := s.get("/v1/payment_intents/"+url.PathEscape(id), &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

func (s *stripeService) listPaymentMethods(customerID string) ([]stripePaymentMethod, error) {
	var resp struct {
		Data []stripePaymentMethod `json:"data"`
	}
	path := "/v1/payment_methods?" + url.Values{"customer": {customerID}, "type": {"card"}}.Encode()
	if err := s.get(path, &resp); err != nil {
		return nil, err
	}
	return resp.Data, nil
}

func (s *stripeService) chargeOffSession(customerID, paymentMethodID string, amountUSDCents int64, idempotencyKey string, metadata map[string]string) (*stripePaymentIntent, error) {
	vals := url.Values{
		"amount":                   {fmt.Sprintf("%d", amountUSDCents)},
		"currency":                 {"usd"},
		"customer":                 {customerID},
		"payment_method":           {paymentMethodID},
		"confirm":                  {"true"},
		"off_session":              {"true"},
		"error_on_requires_action": {"true"},
		"description":              {"CuteDSL automatic credit top-up"},
	}
	for k, v := range metadata {
		vals.Set(fmt.Sprintf("metadata[%s]", k), v)
	}
	headers := map[string]string{}
	if idempotencyKey != "" {
		headers["Idempotency-Key"] = idempotencyKey
	}

	var resp stripePaymentIntent
	if err := s.post("/v1/payment_intents", vals, headers, &resp); err != nil {
		return nil, err
	}
	if resp.Status != "succeeded" {
		return &resp, fmt.Errorf("payment not succeeded: %s", resp.Status)
	}
	return &resp, nil
}

func (s *stripeService) post(path string, vals url.Values, headers map[string]string, out interface{}) error {
	return s.request(http.MethodPost, path, vals, headers, out)
}

func (s *stripeService) get(path string, out interface{}) error {
	return s.request(http.MethodGet, path, nil, nil, out)
}

func (s *stripeService) request(method, path string, vals url.Values, headers map[string]string, out interface{}) error {
	var body io.Reader
	if vals != nil {
		body = strings.NewReader(vals.Encode())
	}
	req, err := http.NewRequest(method, s.baseURL+path, body)
	if err != nil {
		return err
	}
	req.SetBasicAuth(s.secretKey, "")
	if vals != nil {
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}

	resp, err := s.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 400 {
		return fmt.Errorf("stripe %d: %s", resp.StatusCode, string(data))
	}
	if out == nil {
		return nil
	}
	return json.Unmarshal(data, out)
}

type stripeCheckoutRequest struct {
	WalletAddress string  `json:"wallet_address"`
	AmountUSD     float64 `json:"amount_usd"`
	Amount        float64 `json:"amount"`
	Type          string  `json:"type"`
	Plan          string  `json:"plan"`
	PriceID       string  `json:"price_id"`
	ReturnURL     string  `json:"return_url"`
	SuccessURL    string  `json:"success_url"`
	CancelURL     string  `json:"cancel_url"`
}

func stripeMonthlyPriceID() string {
	return strings.TrimPrefix(strings.TrimSpace(getEnv("STRIPE_MONTHLY_PRICE_ID", "price_1TZQWbQda7Fr1LvlkbnwaYpg")), "/")
}

func stripeAnnualPriceID() string {
	return strings.TrimPrefix(strings.TrimSpace(getEnv("STRIPE_ANNUAL_PRICE_ID", "price_1TZQXvQda7Fr1Lvl2iOtzUx2")), "/")
}

func stripePlanPriceID(plan string) (string, string) {
	switch strings.ToLower(strings.TrimSpace(plan)) {
	case "annual", "year", "yearly":
		return "annual", stripeAnnualPriceID()
	default:
		return "monthly", stripeMonthlyPriceID()
	}
}

func stripePlanFromPriceID(priceID string) string {
	priceID = strings.TrimPrefix(strings.TrimSpace(priceID), "/")
	switch priceID {
	case stripeAnnualPriceID():
		return "annual"
	case stripeMonthlyPriceID():
		return "monthly"
	default:
		return ""
	}
}

func stripeSubscriptionIsActive(status string) bool {
	switch status {
	case "active", "trialing":
		return true
	default:
		return false
	}
}

func handleStripeConfig(ctx *fasthttp.RequestCtx) {
	jsonResponse(ctx, 200, map[string]interface{}{
		"configured":      stripeSvc != nil,
		"publishable_key": os.Getenv("STRIPE_PUBLISHABLE_KEY"),
	})
}

func handleStripeCheckout(ctx *fasthttp.RequestCtx) {
	if stripeSvc == nil {
		jsonError(ctx, 503, "stripe payments not configured")
		return
	}

	var req stripeCheckoutRequest
	if err := json.Unmarshal(ctx.PostBody(), &req); err != nil {
		jsonError(ctx, 400, "invalid json")
		return
	}
	req.WalletAddress = strings.TrimSpace(req.WalletAddress)
	if req.WalletAddress == "" {
		jsonError(ctx, 400, "wallet_address required")
		return
	}

	user, err := dbConn.GetUserByWallet(req.WalletAddress)
	if err != nil {
		jsonError(ctx, 404, "wallet not registered")
		return
	}
	if !looksLikeEmail(user.Email) {
		jsonError(ctx, 400, "email required before stripe checkout")
		return
	}

	customerID := user.StripeCustomerID
	if customerID == "" {
		customerID, err = stripeSvc.createCustomer(user.Email, user.WalletAddress)
		if err != nil {
			log.Printf("stripe customer error: %v", err)
			jsonError(ctx, 502, "failed to create stripe customer")
			return
		}
		if err := dbConn.SetStripeCustomerID(user.ID, customerID); err != nil {
			jsonError(ctx, 500, "failed to save stripe customer")
			return
		}
	}

	origin := defaultPublicURL(ctx)
	returnURL := strings.TrimSpace(req.ReturnURL)
	if returnURL == "" {
		returnURL = strings.TrimSpace(req.SuccessURL)
	}
	if returnURL == "" {
		returnURL = origin + "/account?payment=success&session_id={CHECKOUT_SESSION_ID}"
	}

	checkoutType := strings.ToLower(strings.TrimSpace(req.Type))
	if checkoutType == "" && (req.Plan != "" || req.PriceID != "") {
		checkoutType = "subscription"
	}
	if checkoutType == "subscription" {
		plan, priceID := stripePlanPriceID(req.Plan)
		if req.PriceID != "" {
			priceID = strings.TrimPrefix(strings.TrimSpace(req.PriceID), "/")
			if p := stripePlanFromPriceID(priceID); p != "" {
				plan = p
			}
		}
		if priceID == "" {
			jsonError(ctx, 500, "stripe subscription price is not configured")
			return
		}
		metadata := map[string]string{
			"user_id":        user.ID,
			"wallet_address": user.WalletAddress,
			"type":           "subscription",
			"plan":           plan,
			"price_id":       priceID,
		}
		session, err := stripeSvc.createSubscriptionCheckoutSession(customerID, returnURL, priceID, metadata)
		if err != nil {
			log.Printf("stripe subscription checkout error: %v", err)
			jsonError(ctx, 502, "failed to create stripe subscription checkout")
			return
		}
		jsonResponse(ctx, 200, map[string]interface{}{
			"success":         true,
			"url":             session.URL,
			"session_id":      session.ID,
			"customer_id":     customerID,
			"client_secret":   session.ClientSecret,
			"publishable_key": os.Getenv("STRIPE_PUBLISHABLE_KEY"),
			"ui_mode":         stripeCheckoutUIMode(),
			"type":            "subscription",
			"plan":            plan,
			"price_id":        priceID,
		})
		return
	}

	amountUSD := req.AmountUSD
	if amountUSD == 0 {
		amountUSD = req.Amount
	}
	if amountUSD < 1 || amountUSD > 500 {
		jsonError(ctx, 400, "amount must be between $1 and $500")
		return
	}

	amountUSDCents := int64(math.Round(amountUSD * 100))
	metadata := map[string]string{
		"user_id":        user.ID,
		"wallet_address": user.WalletAddress,
		"amount_usd":     fmt.Sprintf("%.2f", float64(amountUSDCents)/100),
		"type":           "credits_purchase",
	}
	session, err := stripeSvc.createCheckoutSession(customerID, returnURL, amountUSDCents, metadata)
	if err != nil {
		log.Printf("stripe checkout error: %v", err)
		jsonError(ctx, 502, "failed to create stripe checkout")
		return
	}

	jsonResponse(ctx, 200, map[string]interface{}{
		"success":         true,
		"url":             session.URL,
		"session_id":      session.ID,
		"customer_id":     customerID,
		"amount_usd":      float64(amountUSDCents) / 100,
		"client_secret":   session.ClientSecret,
		"publishable_key": os.Getenv("STRIPE_PUBLISHABLE_KEY"),
		"ui_mode":         stripeCheckoutUIMode(),
	})
}

func handleStripeWebhook(ctx *fasthttp.RequestCtx) {
	if stripeSvc == nil {
		jsonError(ctx, 503, "stripe payments not configured")
		return
	}
	payload := ctx.PostBody()
	if stripeWebhookSecret != "" {
		sig := string(ctx.Request.Header.Peek("Stripe-Signature"))
		if err := verifyStripeWebhookSignature(payload, sig, stripeWebhookSecret, 5*time.Minute); err != nil {
			log.Printf("stripe webhook signature error: %v", err)
			jsonError(ctx, 400, "invalid stripe signature")
			return
		}
	}

	var evt stripeWebhookEvent
	if err := json.Unmarshal(payload, &evt); err != nil {
		jsonError(ctx, 400, "invalid webhook payload")
		return
	}

	switch evt.Type {
	case "checkout.session.completed":
		handleStripeCheckoutCompleted(evt.Data.Object)
	case "customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted":
		handleStripeSubscriptionUpdated(evt.Data.Object)
	default:
		log.Printf("stripe webhook ignored: %s", evt.Type)
	}

	jsonResponse(ctx, 200, map[string]bool{"received": true})
}

func handleStripeCheckoutCompleted(raw json.RawMessage) {
	var session stripeCheckoutSession
	if err := json.Unmarshal(raw, &session); err != nil {
		log.Printf("stripe webhook parse session: %v", err)
		return
	}
	if session.PaymentStatus != "paid" {
		if session.Mode != "subscription" {
			log.Printf("stripe session %s not paid: %s", session.ID, session.PaymentStatus)
			return
		}
	}

	userID := session.Metadata["user_id"]
	if userID == "" {
		log.Printf("stripe session %s missing user_id metadata", session.ID)
		return
	}
	if session.Mode == "subscription" || session.Metadata["type"] == "subscription" {
		handleStripeSubscriptionCheckoutCompleted(session, userID)
		return
	}

	usdAmount := float64(session.AmountTotal) / 100
	cutePrice := getCUTEPriceUSD()
	if cutePrice <= 0 {
		log.Printf("stripe session %s cannot credit: CUTE price unavailable", session.ID)
		return
	}
	cuteAmount := usdAmount / cutePrice
	credited, balance, err := dbConn.CreditStripeCheckout(userID, session.Customer, session.ID, session.PaymentIntent, usdAmount, cuteAmount)
	if err != nil {
		log.Printf("stripe session %s credit error: %v", session.ID, err)
		return
	}
	if credited {
		log.Printf("stripe credited user=%s session=%s cute=%.2f balance=%.2f", userID, session.ID, cuteAmount, balance)
	}

	if session.PaymentIntent != "" {
		if pi, err := stripeSvc.retrievePaymentIntent(session.PaymentIntent); err == nil && pi.PaymentMethod != "" {
			if err := dbConn.SetStripePaymentMethodID(userID, pi.PaymentMethod); err != nil {
				log.Printf("stripe payment method save error: %v", err)
			}
		}
	}
}

func handleStripeSubscriptionCheckoutCompleted(session stripeCheckoutSession, userID string) {
	subscriptionID := session.Subscription
	priceID := strings.TrimPrefix(session.Metadata["price_id"], "/")
	plan := session.Metadata["plan"]
	status := "active"
	periodEnd := time.Unix(0, 0).UTC()

	if subscriptionID != "" {
		if sub, err := stripeSvc.retrieveSubscription(subscriptionID); err == nil {
			status = sub.Status
			if status == "" {
				status = "active"
			}
			periodEnd = stripePeriodEnd(sub.CurrentPeriodEnd)
			if len(sub.Items.Data) > 0 {
				priceID = sub.Items.Data[0].Price.ID
			}
			if sub.Metadata != nil {
				if sub.Metadata["plan"] != "" {
					plan = sub.Metadata["plan"]
				}
			}
		} else {
			log.Printf("stripe subscription retrieve failed for %s: %v", subscriptionID, err)
		}
	}
	if plan == "" {
		plan = stripePlanFromPriceID(priceID)
	}
	if err := dbConn.UpdateStripeSubscription(userID, session.Customer, subscriptionID, priceID, status, plan, periodEnd); err != nil {
		log.Printf("stripe subscription save error user=%s subscription=%s: %v", userID, subscriptionID, err)
		return
	}
	log.Printf("stripe subscription updated user=%s subscription=%s status=%s plan=%s", userID, subscriptionID, status, plan)
}

func handleStripeSubscriptionUpdated(raw json.RawMessage) {
	var sub stripeSubscription
	if err := json.Unmarshal(raw, &sub); err != nil {
		log.Printf("stripe webhook parse subscription: %v", err)
		return
	}
	priceID := ""
	if len(sub.Items.Data) > 0 {
		priceID = sub.Items.Data[0].Price.ID
	}
	plan := ""
	if sub.Metadata != nil {
		plan = sub.Metadata["plan"]
	}
	if plan == "" {
		plan = stripePlanFromPriceID(priceID)
	}
	periodEnd := stripePeriodEnd(sub.CurrentPeriodEnd)
	if err := dbConn.UpdateStripeSubscriptionBySubscriptionID(sub.ID, sub.Customer, priceID, sub.Status, plan, periodEnd); err != nil {
		log.Printf("stripe subscription webhook save error subscription=%s: %v", sub.ID, err)
	}
}

func stripePeriodEnd(unixSeconds int64) time.Time {
	if unixSeconds <= 0 {
		return time.Unix(0, 0).UTC()
	}
	return time.Unix(unixSeconds, 0).UTC()
}

type autotopupRequest struct {
	WalletAddress string  `json:"wallet_address"`
	Enabled       bool    `json:"enabled"`
	ThresholdUSD  float64 `json:"threshold_usd"`
	AmountUSD     float64 `json:"amount_usd"`
}

func handleGetAutotopupSettings(ctx *fasthttp.RequestCtx) {
	wallet := string(ctx.QueryArgs().Peek("wallet"))
	if wallet == "" {
		jsonError(ctx, 400, "wallet query param required")
		return
	}
	user, err := dbConn.GetUserByWallet(wallet)
	if err != nil {
		jsonError(ctx, 404, "wallet not registered")
		return
	}
	jsonResponse(ctx, 200, autotopupSettingsResponse(user))
}

func handleSaveAutotopupSettings(ctx *fasthttp.RequestCtx) {
	var req autotopupRequest
	if err := json.Unmarshal(ctx.PostBody(), &req); err != nil {
		jsonError(ctx, 400, "invalid json")
		return
	}
	if req.WalletAddress == "" {
		jsonError(ctx, 400, "wallet_address required")
		return
	}
	user, err := dbConn.GetUserByWallet(req.WalletAddress)
	if err != nil {
		jsonError(ctx, 404, "wallet not registered")
		return
	}
	if req.ThresholdUSD == 0 {
		req.ThresholdUSD = 5
	}
	if req.AmountUSD == 0 {
		req.AmountUSD = 25
	}
	if req.Enabled {
		if stripeSvc == nil {
			jsonError(ctx, 503, "stripe payments not configured")
			return
		}
		if user.StripePaymentMethodID == "" {
			if user.StripeCustomerID != "" {
				if methods, err := stripeSvc.listPaymentMethods(user.StripeCustomerID); err == nil && len(methods) > 0 {
					user.StripePaymentMethodID = methods[0].ID
					_ = dbConn.SetStripePaymentMethodID(user.ID, user.StripePaymentMethodID)
				}
			}
			if user.StripePaymentMethodID == "" {
				jsonError(ctx, 400, "buy credits with Stripe once before enabling auto top-up")
				return
			}
		}
		if req.ThresholdUSD < 1 || req.ThresholdUSD > 100 {
			jsonError(ctx, 400, "threshold_usd must be between 1 and 100")
			return
		}
		if req.AmountUSD < 5 || req.AmountUSD > 500 {
			jsonError(ctx, 400, "amount_usd must be between 5 and 500")
			return
		}
	}

	if err := dbConn.UpdateAutotopupSettings(user.ID, req.Enabled, req.ThresholdUSD, req.AmountUSD); err != nil {
		jsonError(ctx, 500, "failed to save auto top-up settings")
		return
	}
	user.AutotopupEnabled = req.Enabled
	user.AutotopupThresholdUSD = req.ThresholdUSD
	user.AutotopupAmountUSD = req.AmountUSD
	jsonResponse(ctx, 200, autotopupSettingsResponse(user))
}

func autotopupSettingsResponse(user *User) map[string]interface{} {
	return map[string]interface{}{
		"success":                 true,
		"enabled":                 user.AutotopupEnabled,
		"threshold_usd":           user.AutotopupThresholdUSD,
		"amount_usd":              user.AutotopupAmountUSD,
		"has_payment_method":      user.StripePaymentMethodID != "",
		"stripe_customer_id":      user.StripeCustomerID,
		"autotopup_enabled":       user.AutotopupEnabled,
		"autotopup_threshold_usd": user.AutotopupThresholdUSD,
		"autotopup_amount_usd":    user.AutotopupAmountUSD,
	}
}

func maybeTriggerAutoTopup(userID string) {
	if stripeSvc == nil || userID == "" {
		return
	}
	if _, loaded := autoTopupInFlight.LoadOrStore(userID, true); loaded {
		return
	}
	go func() {
		defer autoTopupInFlight.Delete(userID)
		if err := runAutoTopup(userID); err != nil {
			log.Printf("auto top-up failed for user=%s: %v", userID, err)
		}
	}()
}

func runAutoTopup(userID string) error {
	user, err := dbConn.GetUserByID(userID)
	if err != nil {
		return err
	}
	if !user.AutotopupEnabled || user.StripeCustomerID == "" || user.StripePaymentMethodID == "" || user.AutotopupAmountUSD <= 0 {
		return nil
	}
	cutePrice := getCUTEPriceUSD()
	if cutePrice <= 0 {
		return nil
	}
	if user.Credits*cutePrice > user.AutotopupThresholdUSD {
		return nil
	}
	if !user.AutotopupLastAt.IsZero() && user.AutotopupLastAt.After(time.Now().Add(-60*time.Second)) {
		return nil
	}
	if status, last, ok, err := dbConn.LastAutotopupCharge(userID); err != nil {
		return err
	} else if ok && status == "failed" && last.After(time.Now().Add(-6*time.Hour)) {
		return nil
	}

	amountUSDCents := int64(math.Round(user.AutotopupAmountUSD * 100))
	if amountUSDCents < 50 {
		amountUSDCents = 50
	}
	amountUSD := float64(amountUSDCents) / 100
	cuteAmount := amountUSD / cutePrice
	idempotencyKey := fmt.Sprintf("cutedsl-autotopup-%s-%d", userID, time.Now().Unix()/21600)

	pi, err := stripeSvc.chargeOffSession(user.StripeCustomerID, user.StripePaymentMethodID, amountUSDCents, idempotencyKey, map[string]string{
		"user_id":        user.ID,
		"wallet_address": user.WalletAddress,
		"type":           "auto_topup",
	})
	if err != nil {
		piID := ""
		if pi != nil {
			piID = pi.ID
		}
		_ = dbConn.LogAutotopupCharge(user.ID, amountUSD, cuteAmount, piID, "failed", err.Error())
		return err
	}

	newBalance, err := dbConn.AddPurchasedCredits(user.ID, cuteAmount)
	if err != nil {
		_ = dbConn.LogAutotopupCharge(user.ID, amountUSD, cuteAmount, pi.ID, "failed", "credit failed: "+err.Error())
		return err
	}
	_ = dbConn.CreateBillingEvent(&BillingEvent{
		UserID:       user.ID,
		EventType:    "stripe_autotopup",
		Amount:       cuteAmount,
		CuteAmount:   cuteAmount,
		USDAmount:    amountUSD,
		Description:  fmt.Sprintf("Stripe auto top-up ($%.2f)", amountUSD),
		CreditsAfter: newBalance,
	})
	_ = dbConn.SetAutotopupLastAt(user.ID)
	_ = dbConn.LogAutotopupCharge(user.ID, amountUSD, cuteAmount, pi.ID, "succeeded", "")
	return nil
}

func defaultPublicURL(ctx *fasthttp.RequestCtx) string {
	if v := strings.TrimRight(os.Getenv("APP_URL"), "/"); v != "" {
		return v
	}
	if v := strings.TrimRight(os.Getenv("FRONTEND_URL"), "/"); v != "" {
		return v
	}
	scheme := "https"
	if devMode {
		scheme = "http"
	}
	return scheme + "://" + string(ctx.Host())
}

func verifyStripeWebhookSignature(payload []byte, sigHeader, secret string, tolerance time.Duration) error {
	timestamp, signatures, err := parseStripeSignatureHeader(sigHeader)
	if err != nil {
		return err
	}
	if tolerance > 0 && time.Since(timestamp) > tolerance {
		return errors.New("stripe signature timestamp too old")
	}
	signedPayload := fmt.Sprintf("%d.%s", timestamp.Unix(), payload)
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(signedPayload))
	expected := mac.Sum(nil)
	for _, sig := range signatures {
		decoded, err := hex.DecodeString(sig)
		if err == nil && subtle.ConstantTimeCompare(decoded, expected) == 1 {
			return nil
		}
	}
	return errors.New("stripe signature mismatch")
}

func parseStripeSignatureHeader(sigHeader string) (time.Time, []string, error) {
	if sigHeader == "" {
		return time.Time{}, nil, errors.New("missing Stripe-Signature")
	}
	var ts time.Time
	var signatures []string
	for _, part := range strings.Split(sigHeader, ",") {
		key, value, ok := strings.Cut(strings.TrimSpace(part), "=")
		if !ok {
			continue
		}
		if key == "t" {
			secs, err := strconv.ParseInt(value, 10, 64)
			if err != nil {
				return time.Time{}, nil, err
			}
			ts = time.Unix(secs, 0)
		}
		if key == "v1" {
			signatures = append(signatures, value)
		}
	}
	if ts.IsZero() || len(signatures) == 0 {
		return time.Time{}, nil, errors.New("incomplete stripe signature")
	}
	return ts, signatures, nil
}
