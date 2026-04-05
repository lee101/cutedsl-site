package main

import (
	"database/sql"
	"fmt"
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
		credits DOUBLE PRECISION DEFAULT 0,
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
	err := db.conn.QueryRow(
		"SELECT id, wallet_address, email, api_key, credits, total_deposited, drip_step, drip_started_at, created_at, updated_at FROM users WHERE wallet_address = $1",
		walletAddress,
	).Scan(&user.ID, &user.WalletAddress, &user.Email, &user.APIKey, &user.Credits, &user.TotalDeposited, &user.DripStep, &user.DripStartedAt, &user.CreatedAt, &user.UpdatedAt)

	if err == sql.ErrNoRows {
		user = User{
			ID:            newUUID(),
			WalletAddress: walletAddress,
			APIKey:        "cutedsl_" + newUUID()[:24],
			Credits:       0,
			CreatedAt:     time.Now(),
			UpdatedAt:     time.Now(),
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

// GetUserByWallet returns a user by wallet address
func (db *DB) GetUserByWallet(walletAddress string) (*User, error) {
	db.mu.RLock()
	defer db.mu.RUnlock()

	var user User
	err := db.conn.QueryRow(
		"SELECT id, wallet_address, email, api_key, credits, total_deposited, drip_step, drip_started_at, created_at, updated_at FROM users WHERE wallet_address = $1",
		walletAddress,
	).Scan(&user.ID, &user.WalletAddress, &user.Email, &user.APIKey, &user.Credits, &user.TotalDeposited, &user.DripStep, &user.DripStartedAt, &user.CreatedAt, &user.UpdatedAt)
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
	err := db.conn.QueryRow(
		"SELECT id, wallet_address, email, api_key, credits, total_deposited, drip_step, drip_started_at, created_at, updated_at FROM users WHERE api_key = $1",
		apiKey,
	).Scan(&user.ID, &user.WalletAddress, &user.Email, &user.APIKey, &user.Credits, &user.TotalDeposited, &user.DripStep, &user.DripStartedAt, &user.CreatedAt, &user.UpdatedAt)
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
		`SELECT id, wallet_address, email, api_key, credits, total_deposited, drip_step, drip_started_at, created_at, updated_at
		 FROM users WHERE email != '' AND drip_step < 20 AND drip_started_at > '1970-01-01'`,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var users []User
	for rows.Next() {
		var u User
		if err := rows.Scan(&u.ID, &u.WalletAddress, &u.Email, &u.APIKey, &u.Credits, &u.TotalDeposited, &u.DripStep, &u.DripStartedAt, &u.CreatedAt, &u.UpdatedAt); err != nil {
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
		`SELECT id, wallet_address, email, api_key, credits, total_deposited, drip_step, drip_started_at, created_at, updated_at
		 FROM users WHERE email != '' AND credits <= 0 AND total_deposited > 0`,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var users []User
	for rows.Next() {
		var u User
		if err := rows.Scan(&u.ID, &u.WalletAddress, &u.Email, &u.APIKey, &u.Credits, &u.TotalDeposited, &u.DripStep, &u.DripStartedAt, &u.CreatedAt, &u.UpdatedAt); err != nil {
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
	return err
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
