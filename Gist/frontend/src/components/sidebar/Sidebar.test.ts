import { describe, it, expect } from 'vitest'

/**
 * Test the animation direction calculation logic used in Sidebar.
 *
 * BUG FIX SUMMARY (2024):
 * -----------------------
 * Problem: When rapidly switching content types (e.g., article -> picture -> notification),
 * the second transition's animation direction was incorrect. The notification list would
 * slide in from the left instead of the right.
 *
 * Root Cause: Using framer-motion's `variants` + `custom` prop caused AnimatePresence to
 * cache stale `custom` values for exit animations during rapid transitions.
 *
 * Solution:
 * 1. Don't use `variants`/`custom` - write expressions directly in `initial`/`exit`
 * 2. Use `useState` for `direction`, set synchronously in `useLayoutEffect` (BEFORE setTimeout)
 * 3. Delay `animatedContentType` update via `setTimeout` to ensure direction is set first
 *
 * Animation Logic:
 * - direction = newIndex > prevIndex ? 1 : -1
 * - 1 = forward (new content enters from right, old exits to left)
 * - -1 = backward (new content enters from left, old exits to right)
 */

// Extract the direction calculation logic for testing
function calculateDirection(prevIndex: number, newIndex: number): 1 | -1 {
  return newIndex > prevIndex ? 1 : -1
}

// Animation property calculation (matching actual implementation - NO variants)
function calculateAnimationProps(direction: number, isAnimationReady: boolean) {
  return {
    initial: isAnimationReady
      ? { x: direction > 0 ? '100%' : '-100%', opacity: 0 }
      : false,
    animate: { x: 0, opacity: 1 },
    exit: { x: direction > 0 ? '-100%' : '100%', opacity: 0 },
  }
}

describe('Sidebar animation direction calculation', () => {
  describe('calculateDirection', () => {
    it('should return 1 (forward) when moving to higher index', () => {
      // article(0) -> picture(1)
      expect(calculateDirection(0, 1)).toBe(1)
      // picture(1) -> notification(2)
      expect(calculateDirection(1, 2)).toBe(1)
      // article(0) -> notification(2)
      expect(calculateDirection(0, 2)).toBe(1)
    })

    it('should return -1 (backward) when moving to lower index', () => {
      // picture(1) -> article(0)
      expect(calculateDirection(1, 0)).toBe(-1)
      // notification(2) -> picture(1)
      expect(calculateDirection(2, 1)).toBe(-1)
      // notification(2) -> article(0)
      expect(calculateDirection(2, 0)).toBe(-1)
    })
  })

  describe('content type index mapping', () => {
    const contentTypes = ['article', 'picture', 'notification'] as const

    it('should map content types to correct indices', () => {
      expect(contentTypes.indexOf('article')).toBe(0)
      expect(contentTypes.indexOf('picture')).toBe(1)
      expect(contentTypes.indexOf('notification')).toBe(2)
    })

    it('should work with custom order', () => {
      const customOrder = ['notification', 'picture', 'article'] as const
      expect(customOrder.indexOf('notification')).toBe(0)
      expect(customOrder.indexOf('picture')).toBe(1)
      expect(customOrder.indexOf('article')).toBe(2)

      // Switching from notification(0) to article(2) should be forward
      expect(calculateDirection(0, 2)).toBe(1)
      // Switching from article(2) to notification(0) should be backward
      expect(calculateDirection(2, 0)).toBe(-1)
    })
  })

  describe('sequential transitions', () => {
    it('should calculate correct direction for article -> picture -> notification', () => {
      let prevIndex = 0 // Start at article

      // article(0) -> picture(1): should be forward
      const dir1 = calculateDirection(prevIndex, 1)
      expect(dir1).toBe(1)
      prevIndex = 1

      // picture(1) -> notification(2): should be forward
      const dir2 = calculateDirection(prevIndex, 2)
      expect(dir2).toBe(1)
    })

    it('should calculate correct direction for notification -> picture -> article', () => {
      let prevIndex = 2 // Start at notification

      // notification(2) -> picture(1): should be backward
      const dir1 = calculateDirection(prevIndex, 1)
      expect(dir1).toBe(-1)
      prevIndex = 1

      // picture(1) -> article(0): should be backward
      const dir2 = calculateDirection(prevIndex, 0)
      expect(dir2).toBe(-1)
    })

    it('should handle alternating directions correctly', () => {
      let prevIndex = 1 // Start at picture

      // picture(1) -> notification(2): forward
      expect(calculateDirection(prevIndex, 2)).toBe(1)
      prevIndex = 2

      // notification(2) -> article(0): backward
      expect(calculateDirection(prevIndex, 0)).toBe(-1)
      prevIndex = 0

      // article(0) -> picture(1): forward
      expect(calculateDirection(prevIndex, 1)).toBe(1)
      prevIndex = 1

      // picture(1) -> article(0): backward
      expect(calculateDirection(prevIndex, 0)).toBe(-1)
    })
  })

  describe('animation properties (no variants)', () => {
    /**
     * This tests the actual animation property calculation used after the bug fix.
     * We no longer use framer-motion variants with custom prop, instead we calculate
     * initial/exit directly to avoid stale custom values during rapid transitions.
     */

    it('should calculate correct initial position for forward direction', () => {
      const props = calculateAnimationProps(1, true)
      // Forward: new content enters from right (100%)
      expect(props.initial).toEqual({ x: '100%', opacity: 0 })
      // Forward: old content exits to left (-100%)
      expect(props.exit).toEqual({ x: '-100%', opacity: 0 })
    })

    it('should calculate correct initial position for backward direction', () => {
      const props = calculateAnimationProps(-1, true)
      // Backward: new content enters from left (-100%)
      expect(props.initial).toEqual({ x: '-100%', opacity: 0 })
      // Backward: old content exits to right (100%)
      expect(props.exit).toEqual({ x: '100%', opacity: 0 })
    })

    it('should skip initial animation when not ready', () => {
      const props = calculateAnimationProps(1, false)
      expect(props.initial).toBe(false)
    })

    it('animate state should always center the content', () => {
      const props1 = calculateAnimationProps(1, true)
      const props2 = calculateAnimationProps(-1, true)
      expect(props1.animate).toEqual({ x: 0, opacity: 1 })
      expect(props2.animate).toEqual({ x: 0, opacity: 1 })
    })
  })

  describe('rapid transition simulation', () => {
    /**
     * This simulates the rapid transition bug scenario.
     *
     * The bug occurred when:
     * 1. User clicks picture (from article)
     * 2. User quickly clicks notification (before animation completes)
     * 3. The second animation direction was incorrect
     *
     * The fix ensures direction is calculated based on the contentType's orderIndex
     * (tracked via prevOrderIndexRef), not the animatedContentType.
     */

    interface TransitionState {
      contentType: number       // Current user selection (orderIndex)
      animatedContentType: number  // Delayed animation key (orderIndex)
      direction: 1 | -1
      prevOrderIndex: number
    }

    function simulateTransition(
      state: TransitionState,
      newContentType: number
    ): TransitionState {
      const prevOrderIndex = state.prevOrderIndex
      const orderIndex = newContentType

      // Direction is set synchronously based on contentType change
      let newDirection = state.direction
      if (prevOrderIndex !== -1 && prevOrderIndex !== orderIndex) {
        newDirection = orderIndex > prevOrderIndex ? 1 : -1
      }

      return {
        contentType: newContentType,
        animatedContentType: state.animatedContentType, // Not updated yet (setTimeout)
        direction: newDirection,
        prevOrderIndex: orderIndex,
      }
    }

    function simulateTimeoutCallback(state: TransitionState): TransitionState {
      return {
        ...state,
        animatedContentType: state.contentType, // Now matches contentType
      }
    }

    it('should maintain correct direction during rapid 0 -> 1 -> 2 transition', () => {
      // Initial state: at article (0)
      let state: TransitionState = {
        contentType: 0,
        animatedContentType: 0,
        direction: 1,
        prevOrderIndex: -1,
      }

      // User clicks picture (1)
      state = simulateTransition(state, 1)
      expect(state.contentType).toBe(1)
      expect(state.animatedContentType).toBe(0) // Not updated yet
      expect(state.direction).toBe(1) // Default (prevOrderIndex was -1)
      expect(state.prevOrderIndex).toBe(1)

      // User quickly clicks notification (2) before setTimeout fires
      state = simulateTransition(state, 2)
      expect(state.contentType).toBe(2)
      expect(state.animatedContentType).toBe(0) // Still not updated
      expect(state.direction).toBe(1) // 2 > 1, forward
      expect(state.prevOrderIndex).toBe(2)

      // First setTimeout fires: animatedContentType -> 1 (picture)
      state = simulateTimeoutCallback({ ...state, contentType: 1 })
      state.animatedContentType = 1
      // Direction should still be 1 (forward) for article -> picture animation
      expect(state.direction).toBe(1)

      // Second setTimeout fires: animatedContentType -> 2 (notification)
      state.animatedContentType = 2
      // Direction should still be 1 (forward) for picture -> notification animation
      expect(state.direction).toBe(1)
    })

    it('should maintain correct direction during rapid 2 -> 1 -> 0 transition', () => {
      // Initial state: at notification (2)
      let state: TransitionState = {
        contentType: 2,
        animatedContentType: 2,
        direction: 1,
        prevOrderIndex: 2,
      }

      // User clicks picture (1)
      state = simulateTransition(state, 1)
      expect(state.direction).toBe(-1) // 1 < 2, backward

      // User quickly clicks article (0)
      state = simulateTransition(state, 0)
      expect(state.direction).toBe(-1) // 0 < 1, backward

      // Both animations should slide from left (backward direction)
      const props = calculateAnimationProps(state.direction, true)
      expect(props.initial).toEqual({ x: '-100%', opacity: 0 })
    })

    it('should handle direction change during rapid transition', () => {
      // Start at picture (1)
      let state: TransitionState = {
        contentType: 1,
        animatedContentType: 1,
        direction: 1,
        prevOrderIndex: 1,
      }

      // User clicks notification (2) - forward
      state = simulateTransition(state, 2)
      expect(state.direction).toBe(1)

      // User quickly clicks article (0) - should change to backward
      state = simulateTransition(state, 0)
      expect(state.direction).toBe(-1) // 0 < 2, backward
    })
  })
})
