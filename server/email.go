package main

import (
	"crypto/rand"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"net/smtp"
	"os"
	"strings"
	"time"
)

// DripEmail defines one step in the drip campaign
type DripEmail struct {
	ID          int    `json:"id"`
	DelayDays   int    `json:"delay_days"`
	Subject     string `json:"subject"`
	Template    string `json:"template"`
	Description string `json:"description"`
}

// DripConfig is the full drip campaign configuration
type DripConfig struct {
	Campaign    string      `json:"campaign"`
	Description string      `json:"description"`
	FromEmail   string      `json:"from_email"`
	FromName    string      `json:"from_name"`
	BaseURL     string      `json:"base_url"`
	Emails      []DripEmail `json:"emails"`
}

var dripConfig *DripConfig

// initEmail loads drip config and starts the drip scheduler
func initEmail() {
	// Load drip config
	data, err := os.ReadFile("emails/drip_config.json")
	if err != nil {
		// Try from parent dir (when running from server/)
		data, err = os.ReadFile("../emails/drip_config.json")
		if err != nil {
			log.Printf("Warning: drip_config.json not found, email drip disabled")
			return
		}
	}

	dripConfig = &DripConfig{}
	if err := json.Unmarshal(data, dripConfig); err != nil {
		log.Printf("Warning: failed to parse drip_config.json: %v", err)
		dripConfig = nil
		return
	}

	log.Printf("Email drip campaign loaded: %d emails over %d days",
		len(dripConfig.Emails), dripConfig.Emails[len(dripConfig.Emails)-1].DelayDays)

	// Start drip scheduler (check every 15 minutes)
	go dripSchedulerLoop()
	// Start credits-expired checker (check every hour)
	go creditsExpiredLoop()
}

// sendEmail sends an HTML email via AWS SES SMTP
func sendEmail(toEmail, subject, htmlBody string) error {
	region := os.Getenv("AWS_REGION")
	if region == "" {
		region = "us-east-1"
	}
	smtpUser := os.Getenv("AWS_SMTP_USERNAME")
	smtpPass := os.Getenv("AWS_SMTP_PASSWORD")
	if smtpUser == "" || smtpPass == "" {
		return fmt.Errorf("AWS_SMTP_USERNAME and AWS_SMTP_PASSWORD required")
	}

	smtpHost := fmt.Sprintf("email-smtp.%s.amazonaws.com", region)
	smtpAddr := smtpHost + ":587"

	fromEmail := getEnv("SES_FROM_EMAIL", "lee@cutedsl.com")
	fromName := getEnv("SES_FROM_NAME", "CuteDSL")
	from := fmt.Sprintf("%s <%s>", fromName, fromEmail)

	// Plain text fallback
	plainText := "View this email in your browser at https://cutedsl.com"

	boundary := "----=_Part_" + hex.EncodeToString(func() []byte { b := make([]byte, 8); rand.Read(b); return b }())
	msg := fmt.Sprintf("From: %s\r\nTo: %s\r\nSubject: %s\r\nMIME-Version: 1.0\r\nContent-Type: multipart/alternative; boundary=\"%s\"\r\nList-Unsubscribe: <https://cutedsl.com/unsubscribe?email=%s>\r\n\r\n--%s\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n%s\r\n--%s\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n%s\r\n--%s--\r\n",
		from, toEmail, subject, boundary, toEmail, boundary, plainText, boundary, htmlBody, boundary)

	auth := smtp.PlainAuth("", smtpUser, smtpPass, smtpHost)

	// Try TLS direct on :465 first, fallback to STARTTLS on :587
	tlsConfig := &tls.Config{ServerName: smtpHost}
	conn, err := tls.Dial("tcp", smtpHost+":465", tlsConfig)
	if err != nil {
		log.Printf("TLS direct failed, trying STARTTLS on :587: %v", err)
		err = smtp.SendMail(smtpAddr, auth, fromEmail, []string{toEmail}, []byte(msg))
		if err != nil {
			return fmt.Errorf("SMTP send failed: %w", err)
		}
		return nil
	}

	c, err := smtp.NewClient(conn, smtpHost)
	if err != nil {
		conn.Close()
		return fmt.Errorf("SMTP client error: %w", err)
	}
	defer c.Close()

	if err = c.Auth(auth); err != nil {
		return fmt.Errorf("SMTP auth failed: %w", err)
	}
	if err = c.Mail(fromEmail); err != nil {
		return fmt.Errorf("SMTP MAIL FROM failed: %w", err)
	}
	if err = c.Rcpt(toEmail); err != nil {
		return fmt.Errorf("SMTP RCPT TO failed: %w", err)
	}
	w, err := c.Data()
	if err != nil {
		return fmt.Errorf("SMTP DATA failed: %w", err)
	}
	if _, err = w.Write([]byte(msg)); err != nil {
		return fmt.Errorf("SMTP write failed: %w", err)
	}
	if err = w.Close(); err != nil {
		return fmt.Errorf("SMTP close failed: %w", err)
	}
	c.Quit()

	return nil
}

func sendPasswordResetEmail(toEmail, resetURL string) error {
	html := fmt.Sprintf(`<!doctype html>
<html>
<body style="font-family: Arial, sans-serif; color: #0f172a; line-height: 1.5;">
  <h1 style="font-size: 22px;">Reset your CuteDSL password</h1>
  <p>Use the button below to set a new password. This link expires in 30 minutes.</p>
  <p><a href="%s" style="display:inline-block;background:#0f172a;color:#fff;text-decoration:none;padding:12px 18px;border-radius:8px;font-weight:700;">Reset password</a></p>
  <p style="font-size:12px;color:#64748b;">If you did not request this, you can ignore this email.</p>
</body>
</html>`, resetURL)
	return sendEmail(toEmail, "Reset your CuteDSL password", html)
}

// loadEmailTemplate reads an HTML template from the emails/ directory
func loadEmailTemplate(filename string) (string, error) {
	data, err := os.ReadFile("emails/" + filename)
	if err != nil {
		data, err = os.ReadFile("../emails/" + filename)
		if err != nil {
			return "", fmt.Errorf("template %s not found: %w", filename, err)
		}
	}
	return string(data), nil
}

// personalizeTemplate replaces template variables in email HTML
func personalizeTemplate(html string, user *User) string {
	walletShort := user.WalletAddress
	if len(walletShort) > 8 {
		walletShort = walletShort[:4] + "..." + walletShort[len(walletShort)-4:]
	}

	r := strings.NewReplacer(
		"{{.WalletAddress}}", user.WalletAddress,
		"{{.WalletShort}}", walletShort,
		"{{.Email}}", user.Email,
		"{{.APIKey}}", user.APIKey,
		"{{.UnsubscribeURL}}", fmt.Sprintf("https://cutedsl.com/unsubscribe?email=%s", user.Email),
	)
	return r.Replace(html)
}

// sendDripEmail sends a specific drip email to a user
func sendDripEmail(user *User, drip DripEmail) error {
	html, err := loadEmailTemplate(drip.Template)
	if err != nil {
		return fmt.Errorf("load template %s: %w", drip.Template, err)
	}

	html = personalizeTemplate(html, user)

	if err := sendEmail(user.Email, drip.Subject, html); err != nil {
		return fmt.Errorf("send drip %d to %s: %w", drip.ID, user.Email, err)
	}

	if err := dbConn.UpdateDripStep(user.ID, drip.ID); err != nil {
		return fmt.Errorf("update drip step for %s: %w", user.ID, err)
	}

	log.Printf("Sent drip email #%d (%s) to %s", drip.ID, drip.Subject, user.Email)
	return nil
}

// dripSchedulerLoop checks every 15 min for users who need drip emails
func dripSchedulerLoop() {
	time.Sleep(30 * time.Second) // Initial delay to let server start
	for {
		processDripEmails()
		time.Sleep(15 * time.Minute)
	}
}

func processDripEmails() {
	if dripConfig == nil {
		return
	}

	users, err := dbConn.ListDripEligibleUsers()
	if err != nil {
		log.Printf("Drip scheduler: error listing users: %v", err)
		return
	}

	for _, user := range users {
		daysSinceStart := time.Since(user.DripStartedAt).Hours() / 24

		// Find the next drip email for this user
		for _, drip := range dripConfig.Emails {
			if drip.ID <= user.DripStep {
				continue // Already sent
			}
			if float64(drip.DelayDays) <= daysSinceStart {
				if err := sendDripEmail(&user, drip); err != nil {
					log.Printf("Drip scheduler: %v", err)
				}
				break // One email per cycle per user
			}
			break // Not time yet
		}
	}
}

// creditsExpiredLoop checks every hour for users with depleted credits
func creditsExpiredLoop() {
	time.Sleep(2 * time.Minute) // Initial delay
	for {
		processCreditsExpired()
		time.Sleep(1 * time.Hour)
	}
}

func processCreditsExpired() {
	users, err := dbConn.ListLowCreditUsers()
	if err != nil {
		log.Printf("Credits expired check: error listing users: %v", err)
		return
	}

	for _, user := range users {
		// Only send if last billing event was a deduction (avoid spamming)
		events, err := dbConn.GetUserBillingHistory(user.ID, 1)
		if err != nil || len(events) == 0 {
			continue
		}
		lastEvent := events[0]
		// Only send if the depleting event was within the last 2 hours
		if lastEvent.Amount >= 0 || time.Since(lastEvent.CreatedAt) > 2*time.Hour {
			continue
		}

		html, err := loadEmailTemplate("credits-expired.html")
		if err != nil {
			log.Printf("Credits expired: template error: %v", err)
			continue
		}
		html = personalizeTemplate(html, &user)

		if err := sendEmail(user.Email, "Your CuteDSL Credits Have Run Out — Top Up to Keep Creating", html); err != nil {
			log.Printf("Credits expired: send error for %s: %v", user.Email, err)
		} else {
			log.Printf("Sent credits expired email to %s", user.Email)
		}
	}
}
