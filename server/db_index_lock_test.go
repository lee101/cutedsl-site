package main

import (
	"strings"
	"testing"
	"time"
)

func TestGeneratedImagePromptSearchHasTrigramIndex(t *testing.T) {
	var definition string
	if err := dbConn.conn.QueryRow(
		"SELECT indexdef FROM pg_indexes WHERE tablename = 'generated_images' AND indexname = 'idx_images_prompt_trgm'",
	).Scan(&definition); err != nil {
		t.Fatalf("prompt search index missing: %v", err)
	}
	if !strings.Contains(strings.ToLower(definition), "gin") || !strings.Contains(definition, "gin_trgm_ops") {
		t.Fatalf("prompt search index cannot accelerate substring lookup: %s", definition)
	}
}

func TestInsertGeneratedImageDoesNotHoldDBLockWhileIndexWaits(t *testing.T) {
	originalPromptSearch := promptSearch
	blockedSearch := &PromptSearchEngine{ready: true}
	promptSearch = blockedSearch
	blockedSearch.mu.Lock()

	imageID := newUUID()
	insertDone := make(chan error, 1)
	go func() {
		insertDone <- dbConn.InsertGeneratedImage(&GeneratedImage{
			ID: imageID, Prompt: "index lock regression marker", Width: 32, Height: 32,
			FilePath: "originals/index-lock-test.webp", Model: "zimage",
		})
	}()

	insertFinished := false
	defer func() {
		blockedSearch.mu.Unlock()
		if !insertFinished {
			<-insertDone
		}
		_, _ = dbConn.conn.Exec("DELETE FROM generated_images WHERE id = $1", imageID)
		promptSearch = originalPromptSearch
	}()

	deadline := time.Now().Add(2 * time.Second)
	for {
		var exists bool
		if err := dbConn.conn.QueryRow("SELECT EXISTS (SELECT 1 FROM generated_images WHERE id = $1)", imageID).Scan(&exists); err != nil {
			t.Fatal(err)
		}
		if exists {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("image insert did not reach the database")
		}
		time.Sleep(10 * time.Millisecond)
	}

	select {
	case err := <-insertDone:
		insertFinished = true
		if err != nil {
			t.Fatalf("image insert failed: %v", err)
		}
	case <-time.After(500 * time.Millisecond):
		t.Fatal("image insert blocked behind semantic indexing")
	}

	readDone := make(chan error, 1)
	go func() {
		_, err := dbConn.SearchImages("index lock regression marker", 1, 10, false)
		readDone <- err
	}()
	select {
	case err := <-readDone:
		if err != nil {
			t.Fatalf("gallery read failed while semantic indexing waited: %v", err)
		}
	case <-time.After(500 * time.Millisecond):
		t.Fatal("gallery read blocked behind semantic indexing")
	}
}
