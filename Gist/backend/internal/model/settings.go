package model

import "time"

// Setting represents a key-value setting stored in the database.
type Setting struct {
	Key       string
	Value     string
	UpdatedAt time.Time
}
