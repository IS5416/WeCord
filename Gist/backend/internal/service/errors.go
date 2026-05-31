package service

import (
	"errors"

	"gist/backend/internal/model"
)

var (
	ErrNotFound  = errors.New("not found")
	ErrConflict  = errors.New("conflict")
	ErrInvalid   = errors.New("invalid")
	ErrFeedFetch = errors.New("feed fetch failed")
)

// FeedConflictError is returned when a feed URL already exists.
type FeedConflictError struct {
	ExistingFeed model.Feed
}

func (e *FeedConflictError) Error() string {
	return "feed already exists"
}

func (e *FeedConflictError) Is(target error) bool {
	return target == ErrConflict
}
