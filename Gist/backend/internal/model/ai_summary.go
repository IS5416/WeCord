package model

import "time"

type AISummary struct {
	ID            int64
	EntryID       int64
	IsReadability bool
	Language      string
	Summary       string
	CreatedAt     time.Time
}
