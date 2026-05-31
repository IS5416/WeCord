package model

import "time"

// AIListTranslation stores cached title and summary translations for list view.
type AIListTranslation struct {
	ID        int64
	EntryID   int64
	Language  string
	Title     string
	Summary   string
	CreatedAt time.Time
}
