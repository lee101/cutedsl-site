package main

import "time"

// CryptoPaymentMethod is the payment method type
type CryptoPaymentMethod string

const (
	CryptoPayCUTE CryptoPaymentMethod = "cute"
	CryptoPaySOL  CryptoPaymentMethod = "sol"
)

// CryptoCheckoutStatus is the checkout status type
type CryptoCheckoutStatus string

const (
	CryptoStatusPending CryptoCheckoutStatus = "pending"
	CryptoStatusPaid    CryptoCheckoutStatus = "paid"
	CryptoStatusExpired CryptoCheckoutStatus = "expired"
	CryptoStatusFailed  CryptoCheckoutStatus = "failed"
)

// User represents a platform user identified by their Solana wallet
type User struct {
	ID             string    `json:"id"`
	WalletAddress  string    `json:"wallet_address"`
	Email          string    `json:"email,omitempty"`
	APIKey         string    `json:"api_key"`
	Credits        float64   `json:"credits"` // Balance in $CUTE
	TotalDeposited float64   `json:"total_deposited"`
	DripStep       int       `json:"drip_step"`        // Last sent drip email step (0 = none)
	DripStartedAt  time.Time `json:"drip_started_at"`  // When drip campaign started
	CreatedAt      time.Time `json:"created_at"`
	UpdatedAt      time.Time `json:"updated_at"`
}

// BillingEvent records credit additions and deductions
type BillingEvent struct {
	ID           string    `json:"id"`
	UserID       string    `json:"user_id"`
	EventType    string    `json:"event_type"` // deposit, zimage, chronos2, tts, stt, lora_training
	Amount       float64   `json:"amount"`     // positive = credit, negative = debit
	CuteAmount   float64   `json:"cute_amount"`
	USDAmount    float64   `json:"usd_amount"`
	Description  string    `json:"description"`
	CreditsAfter float64   `json:"credits_after"`
	CreatedAt    time.Time `json:"created_at"`
}

// CryptoCheckoutIntent represents a pending deposit of $CUTE
type CryptoCheckoutIntent struct {
	ID              string               `json:"id"`
	UserID          string               `json:"user_id"`
	WalletAddress   string               `json:"wallet_address"`
	Method          CryptoPaymentMethod  `json:"method"`
	DepositIndex    int64                `json:"deposit_index"`
	DepositPubkey   string               `json:"deposit_pubkey"`
	RecipientPubkey string               `json:"recipient_pubkey"`
	Mint            string               `json:"mint"`
	AmountUI        string               `json:"amount_ui"`
	AmountLamports  uint64               `json:"amount_lamports"`
	USDAmount       float64              `json:"usd_amount"`
	CuteAmount      float64              `json:"cute_amount"`
	Status          CryptoCheckoutStatus `json:"status"`
	TxSig           string               `json:"tx_sig"`
	ExpiresAt       time.Time            `json:"expires_at"`
	HonorUntil      time.Time            `json:"honor_until"`
	Swept           bool                 `json:"swept"`
	CreatedAt       time.Time            `json:"created_at"`
}

// CryptoCheckoutRequest is the API request for creating a deposit
type CryptoCheckoutRequest struct {
	WalletAddress string              `json:"wallet_address"`
	Method        CryptoPaymentMethod `json:"method"`
	Amount        float64             `json:"amount"` // USD amount to deposit
}

// CryptoCheckoutResponse is the API response for a created deposit
type CryptoCheckoutResponse struct {
	IntentID       string  `json:"intent_id"`
	SolanaPayURL   string  `json:"solana_pay_url"`
	DepositAddress string  `json:"deposit_address"`
	ExpiresAt      string  `json:"expires_at"`
	AmountUI       string  `json:"amount_ui"`
	CuteAmount     float64 `json:"cute_amount"`
	USDAmount      float64 `json:"usd_amount"`
	Method         string  `json:"method"`
	TokenMint      string  `json:"token_mint"`
	CutePrice      float64 `json:"cute_price_usd"`
	BuyTokenURL    string  `json:"buy_token_url"`
}

// ServiceUsageRequest is the API request for using an AI service
type ServiceUsageRequest struct {
	WalletAddress string `json:"wallet_address"`
	Service       string `json:"service"` // zimage, chronos2, tts, stt, gemma4, caption
	// Common fields
	Prompt   string `json:"prompt,omitempty"`
	ImageURL string `json:"image_url,omitempty"`
	Text     string `json:"text,omitempty"`
	AudioURL string `json:"audio_url,omitempty"`
	// zimage fields
	Width    int     `json:"width,omitempty"`
	Height   int     `json:"height,omitempty"`
	NumSteps int     `json:"num_steps,omitempty"`
	Guidance float64 `json:"guidance,omitempty"`
	Seed     int     `json:"seed,omitempty"`
	// chronos2 fields
	Values           []float64 `json:"values,omitempty"`
	PredictionLength int       `json:"prediction_length,omitempty"`
	QuantileLevels   []float64 `json:"quantile_levels,omitempty"`
	// tts fields
	Voice string  `json:"voice,omitempty"`
	Speed float64 `json:"speed,omitempty"`
	// gemma4 fields
	Messages    []map[string]interface{} `json:"messages,omitempty"`
	MaxTokens   int                      `json:"max_tokens,omitempty"`
	Temperature float64                  `json:"temperature,omitempty"`
	// lora_training fields
	Model         string      `json:"model,omitempty"`         // "zimage" or "chronos2"
	DatasetName   string      `json:"dataset_name,omitempty"`
	TrainValues   [][]float64 `json:"train_values,omitempty"`  // for chronos2 training
	LoRAR         int         `json:"lora_r,omitempty"`
	LoRAAlpha     int         `json:"lora_alpha,omitempty"`
	LearningRate  float64     `json:"learning_rate,omitempty"`
	TrainSteps    int         `json:"train_steps,omitempty"`
	TrainBatch    int         `json:"train_batch,omitempty"`
}

// ServicePricing holds the current pricing for a service
type ServicePricing struct {
	Service      string  `json:"service"`
	PriceUSD     float64 `json:"price_usd"`
	PriceCute    float64 `json:"price_cute"`
	CutePrice    float64 `json:"cute_price_usd"`
	Unit         string  `json:"unit"` // "per generation", "per forecast", etc.
}

// GeneratedImage represents an AI-generated image in the gallery
type GeneratedImage struct {
	ID         string    `json:"id"`
	Prompt     string    `json:"prompt"`
	Width      int       `json:"width"`
	Height     int       `json:"height"`
	FilePath   string    `json:"file_path"`   // relative path under images/
	ThumbPath  string    `json:"thumb_path"`  // thumbnail path
	MedPath    string    `json:"med_path"`    // medium size path
	FileSize   int64     `json:"file_size"`   // bytes
	Model      string    `json:"model"`       // zimage, flux, etc.
	Seed       int64     `json:"seed"`
	Steps      int       `json:"steps"`
	IsNSFW     *bool     `json:"is_nsfw"`     // nil = not yet classified
	LatentPath string    `json:"latent_path"` // path to saved latent tensor
	CreatedAt  time.Time `json:"created_at"`
}

// ImageSearchResult is returned from the search API
type ImageSearchResult struct {
	Images     []GeneratedImage `json:"images"`
	Total      int              `json:"total"`
	Page       int              `json:"page"`
	PerPage    int              `json:"per_page"`
	Query      string           `json:"query,omitempty"`
}

// WalletBalanceResponse is returned when checking balance
type WalletBalanceResponse struct {
	WalletAddress  string  `json:"wallet_address"`
	Credits        float64 `json:"credits"`      // $CUTE balance
	CreditsUSD     float64 `json:"credits_usd"`  // USD equivalent
	CutePrice      float64 `json:"cute_price_usd"`
	TotalDeposited float64 `json:"total_deposited"`
}
