package main

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	_ "github.com/lib/pq"
)

// DB wraps the PostgreSQL connection
type DB struct {
	conn *sql.DB
	mu   sync.RWMutex
}

const userSelectColumns = `id, wallet_address, email, COALESCE(password_hash, ''), api_key, credits, unlimited_api, total_deposited,
	COALESCE(stripe_customer_id, ''), COALESCE(stripe_payment_method_id, ''),
	COALESCE(stripe_subscription_id, ''), COALESCE(stripe_price_id, ''),
	COALESCE(subscription_status, ''), COALESCE(subscription_plan, ''),
	COALESCE(subscription_current_period_end, '1970-01-01'::timestamptz),
	autotopup_enabled, autotopup_threshold_usd, autotopup_amount_usd,
	COALESCE(autotopup_last_at, '1970-01-01'::timestamptz),
	drip_step, drip_started_at, created_at, updated_at`

func scanUser(row interface {
	Scan(dest ...interface{}) error
}, user *User) error {
	return row.Scan(
		&user.ID, &user.WalletAddress, &user.Email, &user.PasswordHash, &user.APIKey, &user.Credits,
		&user.UnlimitedAPI, &user.TotalDeposited, &user.StripeCustomerID,
		&user.StripePaymentMethodID, &user.StripeSubscriptionID, &user.StripePriceID,
		&user.SubscriptionStatus, &user.SubscriptionPlan, &user.SubscriptionPeriodEnd,
		&user.AutotopupEnabled,
		&user.AutotopupThresholdUSD, &user.AutotopupAmountUSD, &user.AutotopupLastAt,
		&user.DripStep, &user.DripStartedAt, &user.CreatedAt, &user.UpdatedAt,
	)
}

// NewDB opens the PostgreSQL database and runs migrations
func NewDB(dsn string) (*DB, error) {
	conn, err := sql.Open("postgres", dsn)
	if err != nil {
		return nil, fmt.Errorf("open db: %w", err)
	}

	conn.SetMaxOpenConns(20)
	conn.SetMaxIdleConns(5)
	conn.SetConnMaxLifetime(5 * time.Minute)

	if err := conn.Ping(); err != nil {
		return nil, fmt.Errorf("ping db: %w", err)
	}

	db := &DB{conn: conn}
	if err := db.migrate(); err != nil {
		return nil, fmt.Errorf("migrate: %w", err)
	}

	return db, nil
}

func (db *DB) migrate() error {
	schema := `
	CREATE TABLE IF NOT EXISTS users (
		id TEXT PRIMARY KEY,
		wallet_address TEXT UNIQUE NOT NULL,
		email TEXT DEFAULT '',
		api_key TEXT UNIQUE NOT NULL,
		password_hash TEXT DEFAULT '',
		credits DOUBLE PRECISION DEFAULT 0,
		unlimited_api BOOLEAN DEFAULT FALSE,
		total_deposited DOUBLE PRECISION DEFAULT 0,
		drip_step INTEGER DEFAULT 0,
		drip_started_at TIMESTAMPTZ DEFAULT '1970-01-01',
		created_at TIMESTAMPTZ DEFAULT NOW(),
		updated_at TIMESTAMPTZ DEFAULT NOW()
	);

	CREATE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email != '';

	CREATE INDEX IF NOT EXISTS idx_users_api_key ON users(api_key);

	CREATE INDEX IF NOT EXISTS idx_users_wallet ON users(wallet_address);

	CREATE TABLE IF NOT EXISTS billing_events (
		id TEXT PRIMARY KEY,
		user_id TEXT NOT NULL REFERENCES users(id),
		event_type TEXT NOT NULL,
		amount DOUBLE PRECISION NOT NULL,
		cute_amount DOUBLE PRECISION DEFAULT 0,
		usd_amount DOUBLE PRECISION DEFAULT 0,
		description TEXT,
		credits_after DOUBLE PRECISION DEFAULT 0,
		created_at TIMESTAMPTZ DEFAULT NOW()
	);

	CREATE INDEX IF NOT EXISTS idx_billing_user ON billing_events(user_id);
	CREATE INDEX IF NOT EXISTS idx_billing_type ON billing_events(event_type);

	CREATE TABLE IF NOT EXISTS crypto_checkout_intents (
		id TEXT PRIMARY KEY,
		user_id TEXT NOT NULL REFERENCES users(id),
		wallet_address TEXT NOT NULL,
		method TEXT NOT NULL,
		deposit_index BIGINT NOT NULL,
		deposit_pubkey TEXT NOT NULL,
		recipient_pubkey TEXT NOT NULL,
		mint TEXT DEFAULT '',
		amount_ui TEXT NOT NULL,
		amount_lamports BIGINT NOT NULL,
		usd_amount DOUBLE PRECISION NOT NULL,
		cute_amount DOUBLE PRECISION DEFAULT 0,
		status TEXT DEFAULT 'pending',
		tx_sig TEXT DEFAULT '',
		expires_at TIMESTAMPTZ NOT NULL,
		honor_until TIMESTAMPTZ NOT NULL,
		swept BOOLEAN DEFAULT FALSE,
		created_at TIMESTAMPTZ DEFAULT NOW()
	);

	CREATE INDEX IF NOT EXISTS idx_checkout_status ON crypto_checkout_intents(status);
	CREATE INDEX IF NOT EXISTS idx_checkout_user ON crypto_checkout_intents(user_id);
	CREATE INDEX IF NOT EXISTS idx_checkout_deposit ON crypto_checkout_intents(deposit_pubkey);

	CREATE TABLE IF NOT EXISTS deposit_index_counter (
		id INTEGER PRIMARY KEY CHECK (id = 1),
		next_index BIGINT DEFAULT 1
	);

	INSERT INTO deposit_index_counter (id, next_index) VALUES (1, 1) ON CONFLICT DO NOTHING;

	CREATE TABLE IF NOT EXISTS generated_images (
		id TEXT PRIMARY KEY,
		prompt TEXT NOT NULL,
		width INTEGER NOT NULL DEFAULT 1024,
		height INTEGER NOT NULL DEFAULT 1024,
		file_path TEXT NOT NULL,
		thumb_path TEXT DEFAULT '',
		med_path TEXT DEFAULT '',
		file_size BIGINT DEFAULT 0,
		model TEXT DEFAULT 'zimage',
		seed BIGINT DEFAULT 0,
		steps INTEGER DEFAULT 9,
		created_at TIMESTAMPTZ DEFAULT NOW()
	);

	CREATE INDEX IF NOT EXISTS idx_images_created ON generated_images(created_at DESC);
	CREATE INDEX IF NOT EXISTS idx_images_model ON generated_images(model);

	-- NSFW detection
	ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS is_nsfw BOOLEAN DEFAULT NULL;
	CREATE INDEX IF NOT EXISTS idx_images_nsfw ON generated_images(is_nsfw) WHERE is_nsfw IS NOT NULL;

	-- Latent storage reference
	ALTER TABLE generated_images ADD COLUMN IF NOT EXISTS latent_path TEXT DEFAULT '';

	ALTER TABLE users ADD COLUMN IF NOT EXISTS unlimited_api BOOLEAN DEFAULT FALSE;
	ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT DEFAULT '';

	ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT DEFAULT '';
	ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_payment_method_id TEXT DEFAULT '';
	ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT DEFAULT '';
	ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_price_id TEXT DEFAULT '';
	ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_status TEXT DEFAULT '';
	ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_plan TEXT DEFAULT '';
	ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_current_period_end TIMESTAMPTZ DEFAULT NULL;
	ALTER TABLE users ADD COLUMN IF NOT EXISTS autotopup_enabled BOOLEAN DEFAULT FALSE;
	ALTER TABLE users ADD COLUMN IF NOT EXISTS autotopup_threshold_usd DOUBLE PRECISION DEFAULT 5;
	ALTER TABLE users ADD COLUMN IF NOT EXISTS autotopup_amount_usd DOUBLE PRECISION DEFAULT 25;
	ALTER TABLE users ADD COLUMN IF NOT EXISTS autotopup_last_at TIMESTAMPTZ DEFAULT NULL;
	CREATE INDEX IF NOT EXISTS idx_users_stripe_customer ON users(stripe_customer_id) WHERE stripe_customer_id != '';
	CREATE INDEX IF NOT EXISTS idx_users_stripe_subscription ON users(stripe_subscription_id) WHERE stripe_subscription_id != '';

	CREATE TABLE IF NOT EXISTS password_reset_tokens (
		token_hash TEXT PRIMARY KEY,
		user_id TEXT NOT NULL REFERENCES users(id),
		expires_at TIMESTAMPTZ NOT NULL,
		used_at TIMESTAMPTZ DEFAULT NULL,
		created_at TIMESTAMPTZ DEFAULT NOW()
	);

	CREATE INDEX IF NOT EXISTS idx_password_reset_user ON password_reset_tokens(user_id, created_at DESC);

	CREATE TABLE IF NOT EXISTS stripe_checkout_sessions (
		session_id TEXT PRIMARY KEY,
		user_id TEXT NOT NULL REFERENCES users(id),
		stripe_customer_id TEXT DEFAULT '',
		payment_intent_id TEXT DEFAULT '',
		usd_amount DOUBLE PRECISION NOT NULL,
		cute_amount DOUBLE PRECISION NOT NULL,
		credited BOOLEAN DEFAULT FALSE,
		created_at TIMESTAMPTZ DEFAULT NOW()
	);

	CREATE INDEX IF NOT EXISTS idx_stripe_checkout_user ON stripe_checkout_sessions(user_id);
	CREATE INDEX IF NOT EXISTS idx_stripe_checkout_pi ON stripe_checkout_sessions(payment_intent_id);

	CREATE TABLE IF NOT EXISTS autotopup_charges (
		id TEXT PRIMARY KEY,
		user_id TEXT NOT NULL REFERENCES users(id),
		usd_amount DOUBLE PRECISION NOT NULL,
		cute_amount DOUBLE PRECISION NOT NULL,
		stripe_payment_intent_id TEXT DEFAULT '',
		status TEXT NOT NULL,
		error TEXT DEFAULT '',
		created_at TIMESTAMPTZ DEFAULT NOW()
	);

	CREATE INDEX IF NOT EXISTS idx_autotopup_user_created ON autotopup_charges(user_id, created_at DESC);

	-- Full-text search via pg_trgm (fast ILIKE with GIN index)
	CREATE EXTENSION IF NOT EXISTS pg_trgm;
	CREATE INDEX IF NOT EXISTS idx_images_prompt_trgm ON generated_images USING GIN (prompt gin_trgm_ops);
	`

	_, err := db.conn.Exec(schema)
	return err
}

// GetOrCreateUser finds or creates a user by wallet address
func (db *DB) GetOrCreateUser(walletAddress string) (*User, bool, error) {
	db.mu.Lock()
	defer db.mu.Unlock()

	var user User
	err := scanUser(db.conn.QueryRow("SELECT "+userSelectColumns+" FROM users WHERE wallet_address = $1", walletAddress), &user)

	if err == sql.ErrNoRows {
		user = User{
			ID:                    newUUID(),
			WalletAddress:         walletAddress,
			APIKey:                "cutedsl_" + newUUID()[:24],
			Credits:               0,
			AutotopupThresholdUSD: 5,
			AutotopupAmountUSD:    25,
			CreatedAt:             time.Now(),
			UpdatedAt:             time.Now(),
		}
		_, err = db.conn.Exec(
			"INSERT INTO users (id, wallet_address, email, api_key, credits, total_deposited, drip_step, drip_started_at, created_at, updated_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
			user.ID, user.WalletAddress, user.Email, user.APIKey, user.Credits, user.TotalDeposited, user.DripStep, user.DripStartedAt, user.CreatedAt, user.UpdatedAt,
		)
		if err != nil {
			return nil, false, fmt.Errorf("create user: %w", err)
		}
		return &user, true, nil
	}
	if err != nil {
		return nil, false, fmt.Errorf("query user: %w", err)
	}

	return &user, false, nil
}

func emailWalletAddress(email string) string {
	sum := sha256.Sum256([]byte(strings.ToLower(strings.TrimSpace(email))))
	return "email:" + hex.EncodeToString(sum[:])[:40]
}

// GetUserByEmail returns a user by email.
func (db *DB) GetUserByEmail(email string) (*User, error) {
	email = strings.ToLower(strings.TrimSpace(email))
	if email == "" {
		return nil, fmt.Errorf("email required")
	}

	db.mu.RLock()
	defer db.mu.RUnlock()

	var user User
	err := scanUser(db.conn.QueryRow("SELECT "+userSelectColumns+" FROM users WHERE lower(email) = lower($1)", email), &user)
	if err != nil {
		return nil, err
	}
	return &user, nil
}

// GetOrCreateUserByEmail finds or creates a user keyed by email.
func (db *DB) GetOrCreateUserByEmail(email string) (*User, bool, error) {
	return db.GetOrCreateUserByEmailWithPassword(email, "")
}

// GetOrCreateUserByEmailWithPassword finds or creates a user keyed by email and optionally stores a password hash.
func (db *DB) GetOrCreateUserByEmailWithPassword(email, passwordHash string) (*User, bool, error) {
	email = strings.ToLower(strings.TrimSpace(email))
	if email == "" {
		return nil, false, fmt.Errorf("email required")
	}

	db.mu.Lock()
	defer db.mu.Unlock()

	var user User
	err := scanUser(db.conn.QueryRow("SELECT "+userSelectColumns+" FROM users WHERE lower(email) = lower($1)", email), &user)
	if err == nil {
		return &user, false, nil
	}
	if err != sql.ErrNoRows {
		return nil, false, fmt.Errorf("query email user: %w", err)
	}
	user = User{
		ID:                    newUUID(),
		WalletAddress:         emailWalletAddress(email),
		Email:                 email,
		PasswordHash:          passwordHash,
		APIKey:                "cutedsl_" + newUUID()[:24],
		Credits:               0,
		AutotopupThresholdUSD: 5,
		AutotopupAmountUSD:    25,
		CreatedAt:             time.Now(),
		UpdatedAt:             time.Now(),
	}
	_, err = db.conn.Exec(
		"INSERT INTO users (id, wallet_address, email, password_hash, api_key, credits, total_deposited, drip_step, drip_started_at, created_at, updated_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
		user.ID, user.WalletAddress, user.Email, user.PasswordHash, user.APIKey, user.Credits, user.TotalDeposited, user.DripStep, user.DripStartedAt, user.CreatedAt, user.UpdatedAt,
	)
	if err != nil {
		return nil, false, fmt.Errorf("create email user: %w", err)
	}
	return &user, true, nil
}

// SetUserPasswordHash updates a user's password hash.
func (db *DB) SetUserPasswordHash(userID, passwordHash string) error {
	db.mu.Lock()
	defer db.mu.Unlock()

	_, err := db.conn.Exec("UPDATE users SET password_hash = $1, updated_at = NOW() WHERE id = $2", passwordHash, userID)
	return err
}

// CreatePasswordResetToken records a password reset token by hash.
func (db *DB) CreatePasswordResetToken(userID, tokenHash string, expiresAt time.Time) error {
	db.mu.Lock()
	defer db.mu.Unlock()

	_, err := db.conn.Exec(
		`INSERT INTO password_reset_tokens (token_hash, user_id, expires_at, created_at)
		 VALUES ($1, $2, $3, NOW())`,
		tokenHash, userID, expiresAt,
	)
	return err
}

// ConsumePasswordResetToken marks a valid reset token used and returns its user.
func (db *DB) ConsumePasswordResetToken(tokenHash string) (*User, error) {
	db.mu.Lock()
	defer db.mu.Unlock()

	tx, err := db.conn.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	var userID string
	err = tx.QueryRow(
		`UPDATE password_reset_tokens
		 SET used_at = NOW()
		 WHERE token_hash = $1 AND used_at IS NULL AND expires_at > NOW()
		 RETURNING user_id`,
		tokenHash,
	).Scan(&userID)
	if err != nil {
		return nil, err
	}

	var user User
	if err := scanUser(tx.QueryRow("SELECT "+userSelectColumns+" FROM users WHERE id = $1", userID), &user); err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return &user, nil
}

// GetUserByWallet returns a user by wallet address
func (db *DB) GetUserByWallet(walletAddress string) (*User, error) {
	db.mu.RLock()
	defer db.mu.RUnlock()

	var user User
	err := scanUser(db.conn.QueryRow("SELECT "+userSelectColumns+" FROM users WHERE wallet_address = $1", walletAddress), &user)
	if err != nil {
		return nil, err
	}
	return &user, nil
}

// GetUserByAPIKey returns a user by their API key
func (db *DB) GetUserByAPIKey(apiKey string) (*User, error) {
	db.mu.RLock()
	defer db.mu.RUnlock()

	var user User
	err := scanUser(db.conn.QueryRow("SELECT "+userSelectColumns+" FROM users WHERE api_key = $1", apiKey), &user)
	if err != nil {
		return nil, err
	}
	return &user, nil
}

// GetUserByID returns a user by ID.
func (db *DB) GetUserByID(userID string) (*User, error) {
	db.mu.RLock()
	defer db.mu.RUnlock()

	var user User
	err := scanUser(db.conn.QueryRow("SELECT "+userSelectColumns+" FROM users WHERE id = $1", userID), &user)
	if err != nil {
		return nil, err
	}
	return &user, nil
}

// AddUserCredits adds credits to a user's balance
func (db *DB) AddUserCredits(userID string, amount float64) (float64, error) {
	db.mu.Lock()
	defer db.mu.Unlock()

	var newBalance float64
	err := db.conn.QueryRow(
		"UPDATE users SET credits = credits + $1, total_deposited = total_deposited + $2, updated_at = $3 WHERE id = $4 RETURNING credits",
		amount, amount, time.Now(), userID,
	).Scan(&newBalance)
	if err != nil {
		return 0, fmt.Errorf("add credits: %w", err)
	}
	return newBalance, nil
}

// AddPurchasedCredits adds purchased credits and increases lifetime deposits.
func (db *DB) AddPurchasedCredits(userID string, cuteAmount float64) (float64, error) {
	return db.AddUserCredits(userID, cuteAmount)
}

// SetStripeCustomerID stores a Stripe customer ID for a user.
func (db *DB) SetStripeCustomerID(userID, customerID string) error {
	db.mu.Lock()
	defer db.mu.Unlock()

	_, err := db.conn.Exec(
		"UPDATE users SET stripe_customer_id = $1, updated_at = NOW() WHERE id = $2",
		customerID, userID,
	)
	return err
}

// SetStripePaymentMethodID stores the default Stripe payment method for auto-top-up.
func (db *DB) SetStripePaymentMethodID(userID, paymentMethodID string) error {
	db.mu.Lock()
	defer db.mu.Unlock()

	_, err := db.conn.Exec(
		"UPDATE users SET stripe_payment_method_id = $1, updated_at = NOW() WHERE id = $2",
		paymentMethodID, userID,
	)
	return err
}

// UpdateStripeSubscription stores subscription state and mirrors active access
// to unlimited_api for the service billing path.
func (db *DB) UpdateStripeSubscription(userID, customerID, subscriptionID, priceID, status, plan string, periodEnd time.Time) error {
	db.mu.Lock()
	defer db.mu.Unlock()

	active := stripeSubscriptionIsActive(status)
	_, err := db.conn.Exec(
		`UPDATE users
		 SET stripe_customer_id = COALESCE(NULLIF($1, ''), stripe_customer_id),
		     stripe_subscription_id = $2,
		     stripe_price_id = $3,
		     subscription_status = $4,
		     subscription_plan = $5,
		     subscription_current_period_end = $6,
		     unlimited_api = $7,
		     updated_at = NOW()
		 WHERE id = $8`,
		customerID, subscriptionID, priceID, status, plan, periodEnd, active, userID,
	)
	return err
}

// UpdateStripeSubscriptionBySubscriptionID updates subscription state from
// asynchronous Stripe subscription webhooks.
func (db *DB) UpdateStripeSubscriptionBySubscriptionID(subscriptionID, customerID, priceID, status, plan string, periodEnd time.Time) error {
	db.mu.Lock()
	defer db.mu.Unlock()

	active := stripeSubscriptionIsActive(status)
	_, err := db.conn.Exec(
		`UPDATE users
		 SET stripe_customer_id = COALESCE(NULLIF($1, ''), stripe_customer_id),
		     stripe_price_id = $2,
		     subscription_status = $3,
		     subscription_plan = $4,
		     subscription_current_period_end = $5,
		     unlimited_api = $6,
		     updated_at = NOW()
		 WHERE stripe_subscription_id = $7 OR (stripe_customer_id = $1 AND $1 != '')`,
		customerID, priceID, status, plan, periodEnd, active, subscriptionID,
	)
	return err
}

// UpdateAutotopupSettings updates Stripe auto-top-up preferences.
func (db *DB) UpdateAutotopupSettings(userID string, enabled bool, thresholdUSD, amountUSD float64) error {
	db.mu.Lock()
	defer db.mu.Unlock()

	_, err := db.conn.Exec(
		`UPDATE users
		 SET autotopup_enabled = $1,
		     autotopup_threshold_usd = $2,
		     autotopup_amount_usd = $3,
		     updated_at = NOW()
		 WHERE id = $4`,
		enabled, thresholdUSD, amountUSD, userID,
	)
	return err
}

// SetAutotopupLastAt records the last successful auto-top-up time.
func (db *DB) SetAutotopupLastAt(userID string) error {
	db.mu.Lock()
	defer db.mu.Unlock()

	_, err := db.conn.Exec("UPDATE users SET autotopup_last_at = NOW(), updated_at = NOW() WHERE id = $1", userID)
	return err
}

// LastAutotopupCharge returns the latest auto-top-up charge for debounce checks.
func (db *DB) LastAutotopupCharge(userID string) (status string, createdAt time.Time, ok bool, err error) {
	db.mu.RLock()
	defer db.mu.RUnlock()

	err = db.conn.QueryRow(
		`SELECT status, created_at FROM autotopup_charges WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1`,
		userID,
	).Scan(&status, &createdAt)
	if err == sql.ErrNoRows {
		return "", time.Time{}, false, nil
	}
	if err != nil {
		return "", time.Time{}, false, err
	}
	return status, createdAt, true, nil
}

// LogAutotopupCharge records a Stripe auto-top-up attempt.
func (db *DB) LogAutotopupCharge(userID string, usdAmount, cuteAmount float64, paymentIntentID, status, errMsg string) error {
	db.mu.Lock()
	defer db.mu.Unlock()

	_, err := db.conn.Exec(
		`INSERT INTO autotopup_charges (id, user_id, usd_amount, cute_amount, stripe_payment_intent_id, status, error, created_at)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())`,
		newUUID(), userID, usdAmount, cuteAmount, paymentIntentID, status, errMsg,
	)
	return err
}

// CreditStripeCheckout idempotently credits a completed Stripe Checkout session.
func (db *DB) CreditStripeCheckout(userID, stripeCustomerID, sessionID, paymentIntentID string, usdAmount, cuteAmount float64) (bool, float64, error) {
	db.mu.Lock()
	defer db.mu.Unlock()

	tx, err := db.conn.Begin()
	if err != nil {
		return false, 0, err
	}
	defer tx.Rollback()

	var inserted string
	err = tx.QueryRow(
		`INSERT INTO stripe_checkout_sessions
		 (session_id, user_id, stripe_customer_id, payment_intent_id, usd_amount, cute_amount, credited, created_at)
		 VALUES ($1, $2, $3, $4, $5, $6, TRUE, NOW())
		 ON CONFLICT (session_id) DO NOTHING
		 RETURNING session_id`,
		sessionID, userID, stripeCustomerID, paymentIntentID, usdAmount, cuteAmount,
	).Scan(&inserted)
	if err == sql.ErrNoRows {
		if err := tx.Commit(); err != nil {
			return false, 0, err
		}
		return false, 0, nil
	}
	if err != nil {
		return false, 0, err
	}

	var newBalance float64
	err = tx.QueryRow(
		"UPDATE users SET credits = credits + $1, total_deposited = total_deposited + $1, updated_at = NOW(), stripe_customer_id = COALESCE(NULLIF($2, ''), stripe_customer_id) WHERE id = $3 RETURNING credits",
		cuteAmount, stripeCustomerID, userID,
	).Scan(&newBalance)
	if err != nil {
		return false, 0, err
	}

	_, err = tx.Exec(
		`INSERT INTO billing_events (id, user_id, event_type, amount, cute_amount, usd_amount, description, credits_after, created_at)
		 VALUES ($1, $2, 'stripe_deposit', $3, $3, $4, $5, $6, NOW())`,
		newUUID(), userID, cuteAmount, usdAmount,
		fmt.Sprintf("Stripe credit purchase ($%.2f)", usdAmount), newBalance,
	)
	if err != nil {
		return false, 0, err
	}

	if err := tx.Commit(); err != nil {
		return false, 0, err
	}
	return true, newBalance, nil
}

// DeductUserCredits deducts credits from a user's balance
func (db *DB) DeductUserCredits(userID string, amount float64) (float64, error) {
	db.mu.Lock()
	defer db.mu.Unlock()

	var current float64
	err := db.conn.QueryRow("SELECT credits FROM users WHERE id = $1", userID).Scan(&current)
	if err != nil {
		return 0, fmt.Errorf("check balance: %w", err)
	}
	if current < amount {
		return current, fmt.Errorf("insufficient credits: have %.2f, need %.2f", current, amount)
	}

	var newBalance float64
	err = db.conn.QueryRow(
		"UPDATE users SET credits = credits - $1, updated_at = $2 WHERE id = $3 RETURNING credits",
		amount, time.Now(), userID,
	).Scan(&newBalance)
	if err != nil {
		return 0, fmt.Errorf("deduct credits: %w", err)
	}
	return newBalance, nil
}

// CreateBillingEvent logs a billing event
func (db *DB) CreateBillingEvent(event *BillingEvent) error {
	db.mu.Lock()
	defer db.mu.Unlock()

	if event.ID == "" {
		event.ID = newUUID()
	}
	if event.CreatedAt.IsZero() {
		event.CreatedAt = time.Now()
	}

	_, err := db.conn.Exec(
		`INSERT INTO billing_events (id, user_id, event_type, amount, cute_amount, usd_amount, description, credits_after, created_at)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
		event.ID, event.UserID, event.EventType, event.Amount, event.CuteAmount, event.USDAmount,
		event.Description, event.CreditsAfter, event.CreatedAt,
	)
	return err
}

// GetUserBillingHistory returns recent billing events for a user
func (db *DB) GetUserBillingHistory(userID string, limit int) ([]BillingEvent, error) {
	db.mu.RLock()
	defer db.mu.RUnlock()

	rows, err := db.conn.Query(
		`SELECT id, user_id, event_type, amount, cute_amount, usd_amount, description, credits_after, created_at
		 FROM billing_events WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2`,
		userID, limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var events []BillingEvent
	for rows.Next() {
		var e BillingEvent
		if err := rows.Scan(&e.ID, &e.UserID, &e.EventType, &e.Amount, &e.CuteAmount, &e.USDAmount,
			&e.Description, &e.CreditsAfter, &e.CreatedAt); err != nil {
			return nil, err
		}
		events = append(events, e)
	}
	return events, nil
}

// CreateCryptoCheckoutIntent creates a new checkout intent
func (db *DB) CreateCryptoCheckoutIntent(intent *CryptoCheckoutIntent) error {
	db.mu.Lock()
	defer db.mu.Unlock()

	if intent.ID == "" {
		intent.ID = newUUID()
	}
	if intent.CreatedAt.IsZero() {
		intent.CreatedAt = time.Now()
	}

	_, err := db.conn.Exec(
		`INSERT INTO crypto_checkout_intents
		 (id, user_id, wallet_address, method, deposit_index, deposit_pubkey, recipient_pubkey, mint,
		  amount_ui, amount_lamports, usd_amount, cute_amount, status, expires_at, honor_until, created_at)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)`,
		intent.ID, intent.UserID, intent.WalletAddress, intent.Method, intent.DepositIndex,
		intent.DepositPubkey, intent.RecipientPubkey, intent.Mint, intent.AmountUI,
		intent.AmountLamports, intent.USDAmount, intent.CuteAmount, intent.Status,
		intent.ExpiresAt, intent.HonorUntil, intent.CreatedAt,
	)
	return err
}

// GetCryptoCheckoutIntent returns a checkout intent by ID
func (db *DB) GetCryptoCheckoutIntent(id string) (*CryptoCheckoutIntent, error) {
	db.mu.RLock()
	defer db.mu.RUnlock()

	var i CryptoCheckoutIntent
	err := db.conn.QueryRow(
		`SELECT id, user_id, wallet_address, method, deposit_index, deposit_pubkey, recipient_pubkey, mint,
		        amount_ui, amount_lamports, usd_amount, cute_amount, status, tx_sig, expires_at, honor_until, swept, created_at
		 FROM crypto_checkout_intents WHERE id = $1`, id,
	).Scan(&i.ID, &i.UserID, &i.WalletAddress, &i.Method, &i.DepositIndex, &i.DepositPubkey,
		&i.RecipientPubkey, &i.Mint, &i.AmountUI, &i.AmountLamports, &i.USDAmount, &i.CuteAmount,
		&i.Status, &i.TxSig, &i.ExpiresAt, &i.HonorUntil, &i.Swept, &i.CreatedAt)
	if err != nil {
		return nil, err
	}
	return &i, nil
}

// UpdateCryptoCheckoutStatus updates checkout status and tx signature
func (db *DB) UpdateCryptoCheckoutStatus(id string, status CryptoCheckoutStatus, txSig string) error {
	db.mu.Lock()
	defer db.mu.Unlock()

	_, err := db.conn.Exec(
		"UPDATE crypto_checkout_intents SET status = $1, tx_sig = $2 WHERE id = $3",
		status, txSig, id,
	)
	return err
}

// ListPendingCryptoCheckouts returns all pending checkout intents
func (db *DB) ListPendingCryptoCheckouts() ([]CryptoCheckoutIntent, error) {
	db.mu.RLock()
	defer db.mu.RUnlock()

	rows, err := db.conn.Query(
		`SELECT id, user_id, wallet_address, method, deposit_index, deposit_pubkey, recipient_pubkey, mint,
		        amount_ui, amount_lamports, usd_amount, cute_amount, status, tx_sig, expires_at, honor_until, swept, created_at
		 FROM crypto_checkout_intents WHERE status = 'pending' AND honor_until > $1`,
		time.Now(),
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var intents []CryptoCheckoutIntent
	for rows.Next() {
		var i CryptoCheckoutIntent
		if err := rows.Scan(&i.ID, &i.UserID, &i.WalletAddress, &i.Method, &i.DepositIndex, &i.DepositPubkey,
			&i.RecipientPubkey, &i.Mint, &i.AmountUI, &i.AmountLamports, &i.USDAmount, &i.CuteAmount,
			&i.Status, &i.TxSig, &i.ExpiresAt, &i.HonorUntil, &i.Swept, &i.CreatedAt); err != nil {
			return nil, err
		}
		intents = append(intents, i)
	}
	return intents, nil
}

// ListUnsweptCryptoCheckouts returns paid but unswept checkouts
func (db *DB) ListUnsweptCryptoCheckouts() ([]CryptoCheckoutIntent, error) {
	db.mu.RLock()
	defer db.mu.RUnlock()

	rows, err := db.conn.Query(
		`SELECT id, user_id, wallet_address, method, deposit_index, deposit_pubkey, recipient_pubkey, mint,
		        amount_ui, amount_lamports, usd_amount, cute_amount, status, tx_sig, expires_at, honor_until, swept, created_at
		 FROM crypto_checkout_intents WHERE status = 'paid' AND swept = FALSE`,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var intents []CryptoCheckoutIntent
	for rows.Next() {
		var i CryptoCheckoutIntent
		if err := rows.Scan(&i.ID, &i.UserID, &i.WalletAddress, &i.Method, &i.DepositIndex, &i.DepositPubkey,
			&i.RecipientPubkey, &i.Mint, &i.AmountUI, &i.AmountLamports, &i.USDAmount, &i.CuteAmount,
			&i.Status, &i.TxSig, &i.ExpiresAt, &i.HonorUntil, &i.Swept, &i.CreatedAt); err != nil {
			return nil, err
		}
		intents = append(intents, i)
	}
	return intents, nil
}

// MarkCryptoCheckoutSwept marks a checkout as swept
func (db *DB) MarkCryptoCheckoutSwept(id string) error {
	db.mu.Lock()
	defer db.mu.Unlock()

	_, err := db.conn.Exec("UPDATE crypto_checkout_intents SET swept = TRUE WHERE id = $1", id)
	return err
}

// GetNextCryptoDepositIndex atomically increments and returns the next deposit index
func (db *DB) GetNextCryptoDepositIndex() (int64, error) {
	db.mu.Lock()
	defer db.mu.Unlock()

	var idx int64
	err := db.conn.QueryRow(
		"UPDATE deposit_index_counter SET next_index = next_index + 1 WHERE id = 1 RETURNING next_index - 1",
	).Scan(&idx)
	if err != nil {
		return 0, fmt.Errorf("get deposit index: %w", err)
	}
	return idx, nil
}

// ExpirePendingCheckouts expires old pending checkouts past their honor period
func (db *DB) ExpirePendingCheckouts() (int64, error) {
	db.mu.Lock()
	defer db.mu.Unlock()

	result, err := db.conn.Exec(
		"UPDATE crypto_checkout_intents SET status = 'expired' WHERE status = 'pending' AND honor_until < $1",
		time.Now(),
	)
	if err != nil {
		return 0, err
	}
	return result.RowsAffected()
}

// UpdateUserEmail sets the user's email and starts the drip campaign
func (db *DB) UpdateUserEmail(userID, email string) error {
	db.mu.Lock()
	defer db.mu.Unlock()

	_, err := db.conn.Exec(
		"UPDATE users SET email = $1, drip_started_at = CASE WHEN email = '' THEN NOW() ELSE drip_started_at END, updated_at = NOW() WHERE id = $2",
		email, userID,
	)
	return err
}

// UpdateDripStep updates the drip step for a user
func (db *DB) UpdateDripStep(userID string, step int) error {
	db.mu.Lock()
	defer db.mu.Unlock()

	_, err := db.conn.Exec(
		"UPDATE users SET drip_step = $1, updated_at = NOW() WHERE id = $2",
		step, userID,
	)
	return err
}

// ListDripEligibleUsers returns users with email who haven't finished the drip campaign
func (db *DB) ListDripEligibleUsers() ([]User, error) {
	db.mu.RLock()
	defer db.mu.RUnlock()

	rows, err := db.conn.Query(
		`SELECT ` + userSelectColumns + `
		 FROM users WHERE email != '' AND drip_step < 20 AND drip_started_at > '1970-01-01'`,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var users []User
	for rows.Next() {
		var u User
		if err := scanUser(rows, &u); err != nil {
			return nil, err
		}
		users = append(users, u)
	}
	return users, nil
}

// ListLowCreditUsers returns users with email whose credits are zero or near-zero
func (db *DB) ListLowCreditUsers() ([]User, error) {
	db.mu.RLock()
	defer db.mu.RUnlock()

	rows, err := db.conn.Query(
		`SELECT ` + userSelectColumns + `
		 FROM users WHERE email != '' AND credits <= 0 AND total_deposited > 0`,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var users []User
	for rows.Next() {
		var u User
		if err := scanUser(rows, &u); err != nil {
			return nil, err
		}
		users = append(users, u)
	}
	return users, nil
}

// InsertGeneratedImage stores a generated image record
func (db *DB) InsertGeneratedImage(img *GeneratedImage) error {
	db.mu.Lock()
	defer db.mu.Unlock()

	if img.ID == "" {
		img.ID = newUUID()
	}
	if img.CreatedAt.IsZero() {
		img.CreatedAt = time.Now()
	}

	_, err := db.conn.Exec(
		`INSERT INTO generated_images (id, prompt, width, height, file_path, thumb_path, med_path, file_size, model, seed, steps, created_at)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
		 ON CONFLICT (id) DO NOTHING`,
		img.ID, img.Prompt, img.Width, img.Height, img.FilePath, img.ThumbPath, img.MedPath,
		img.FileSize, img.Model, img.Seed, img.Steps, img.CreatedAt,
	)
	if err == nil && promptSearch != nil && img.Prompt != "" {
		// Best-effort incremental update to the semantic index
		promptSearch.IndexIncremental(img.ID, img.Prompt)
	}
	return err
}

// StreamAllImagePrompts scans every row in generated_images and feeds (id, prompt)
// into the callback. Used by the semantic indexer at startup. Keeps memory low
// by using a streaming cursor — no LIMIT, no ORDER BY, no cache.
func (db *DB) StreamAllImagePrompts(allowNSFW bool, cb func(id, prompt string) error) error {
	nsfwFilter := ""
	if !allowNSFW {
		nsfwFilter = " AND (is_nsfw = FALSE OR is_nsfw IS NULL)"
	}
	rows, err := db.conn.Query(
		`SELECT id, prompt FROM generated_images WHERE prompt <> ''` + nsfwFilter,
	)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var id, prompt string
		if err := rows.Scan(&id, &prompt); err != nil {
			return err
		}
		if err := cb(id, prompt); err != nil {
			return err
		}
	}
	return rows.Err()
}

// GetImagesByIDs fetches generated_images rows for a set of IDs, preserving
// the order of the input slice. Used to hydrate semantic search results.
func (db *DB) GetImagesByIDs(ids []string, allowNSFW bool) ([]GeneratedImage, error) {
	if len(ids) == 0 {
		return nil, nil
	}

	// Build $1,$2,... placeholders
	placeholders := make([]byte, 0, len(ids)*4)
	args := make([]interface{}, 0, len(ids))
	for i, id := range ids {
		if i > 0 {
			placeholders = append(placeholders, ',')
		}
		placeholders = append(placeholders, '$')
		placeholders = append(placeholders, fmt.Sprintf("%d", i+1)...)
		args = append(args, id)
	}

	nsfwFilter := ""
	if !allowNSFW {
		nsfwFilter = " AND (is_nsfw = FALSE OR is_nsfw IS NULL)"
	}

	query := `SELECT id, prompt, width, height, file_path, thumb_path, med_path, file_size, model, seed, steps, is_nsfw, latent_path, created_at
			   FROM generated_images WHERE id IN (` + string(placeholders) + `)` + nsfwFilter

	rows, err := db.conn.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	byID := make(map[string]GeneratedImage, len(ids))
	for rows.Next() {
		var img GeneratedImage
		if err := rows.Scan(&img.ID, &img.Prompt, &img.Width, &img.Height, &img.FilePath,
			&img.ThumbPath, &img.MedPath, &img.FileSize, &img.Model, &img.Seed, &img.Steps,
			&img.IsNSFW, &img.LatentPath, &img.CreatedAt); err != nil {
			return nil, err
		}
		byID[img.ID] = img
	}

	// Return in original order, drop any filtered out by NSFW clause
	out := make([]GeneratedImage, 0, len(ids))
	for _, id := range ids {
		if img, ok := byID[id]; ok {
			out = append(out, img)
		}
	}
	return out, nil
}

// SearchImages searches generated images by prompt text with optional NSFW filtering
func (db *DB) SearchImages(query string, page, perPage int, allowNSFW bool) (*ImageSearchResult, error) {
	db.mu.RLock()
	defer db.mu.RUnlock()

	offset := (page - 1) * perPage

	// Build NSFW filter clause
	nsfwFilter := ""
	if !allowNSFW {
		nsfwFilter = " AND (is_nsfw = FALSE OR is_nsfw IS NULL)"
	}

	var total int
	var rows *sql.Rows
	var err error

	if query == "" {
		err = db.conn.QueryRow("SELECT COUNT(*) FROM generated_images WHERE 1=1" + nsfwFilter).Scan(&total)
		if err != nil {
			return nil, err
		}
		rows, err = db.conn.Query(
			`SELECT id, prompt, width, height, file_path, thumb_path, med_path, file_size, model, seed, steps, is_nsfw, latent_path, created_at
			 FROM generated_images WHERE 1=1`+nsfwFilter+` ORDER BY created_at DESC LIMIT $1 OFFSET $2`,
			perPage, offset,
		)
	} else {
		like := "%" + query + "%"
		err = db.conn.QueryRow("SELECT COUNT(*) FROM generated_images WHERE prompt ILIKE $1"+nsfwFilter, like).Scan(&total)
		if err != nil {
			return nil, err
		}
		rows, err = db.conn.Query(
			`SELECT id, prompt, width, height, file_path, thumb_path, med_path, file_size, model, seed, steps, is_nsfw, latent_path, created_at
			 FROM generated_images WHERE prompt ILIKE $1`+nsfwFilter+` ORDER BY created_at DESC LIMIT $2 OFFSET $3`,
			like, perPage, offset,
		)
	}
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var images []GeneratedImage
	for rows.Next() {
		var img GeneratedImage
		if err := rows.Scan(&img.ID, &img.Prompt, &img.Width, &img.Height, &img.FilePath,
			&img.ThumbPath, &img.MedPath, &img.FileSize, &img.Model, &img.Seed, &img.Steps,
			&img.IsNSFW, &img.LatentPath, &img.CreatedAt); err != nil {
			return nil, err
		}
		images = append(images, img)
	}

	return &ImageSearchResult{
		Images:  images,
		Total:   total,
		Page:    page,
		PerPage: perPage,
		Query:   query,
	}, nil
}

// UpdateImageNSFW updates the NSFW flag for an image
func (db *DB) UpdateImageNSFW(id string, isNSFW bool) error {
	db.mu.Lock()
	defer db.mu.Unlock()

	_, err := db.conn.Exec("UPDATE generated_images SET is_nsfw = $1 WHERE id = $2", isNSFW, id)
	return err
}

// ListUnclassifiedImages returns images without NSFW classification
func (db *DB) ListUnclassifiedImages(limit int) ([]GeneratedImage, error) {
	db.mu.RLock()
	defer db.mu.RUnlock()

	rows, err := db.conn.Query(
		`SELECT id, prompt, width, height, file_path, thumb_path, med_path, file_size, model, seed, steps, is_nsfw, latent_path, created_at
		 FROM generated_images WHERE is_nsfw IS NULL ORDER BY created_at DESC LIMIT $1`, limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var images []GeneratedImage
	for rows.Next() {
		var img GeneratedImage
		if err := rows.Scan(&img.ID, &img.Prompt, &img.Width, &img.Height, &img.FilePath,
			&img.ThumbPath, &img.MedPath, &img.FileSize, &img.Model, &img.Seed, &img.Steps,
			&img.IsNSFW, &img.LatentPath, &img.CreatedAt); err != nil {
			return nil, err
		}
		images = append(images, img)
	}
	return images, nil
}

// GetImageCount returns total number of generated images
func (db *DB) GetImageCount() (int, error) {
	db.mu.RLock()
	defer db.mu.RUnlock()

	var count int
	err := db.conn.QueryRow("SELECT COUNT(*) FROM generated_images").Scan(&count)
	return count, err
}

func newUUID() string {
	return uuid.New().String()
}

// Close closes the database connection
func (db *DB) Close() error {
	return db.conn.Close()
}
