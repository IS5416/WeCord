import { describe, it, expect } from 'vitest'
import { isVideoThumbnail } from './media-utils'

describe('media-utils', () => {
  describe('isVideoThumbnail', () => {
    it('should return true for Twitter video thumbnails', () => {
      expect(isVideoThumbnail('https://pbs.twimg.com/ext_tw_video_thumb/123/pu/img/abc.jpg')).toBe(true)
      expect(isVideoThumbnail('https://pbs.twimg.com/amplify_video_thumb/123/img/abc.jpg')).toBe(true)
    })

    it('should return false for regular images', () => {
      expect(isVideoThumbnail('https://example.com/image.jpg')).toBe(false)
      expect(isVideoThumbnail('https://pbs.twimg.com/media/abc.jpg')).toBe(false)
    })

    it('should return false for undefined or empty url', () => {
      expect(isVideoThumbnail(undefined)).toBe(false)
      expect(isVideoThumbnail('')).toBe(false)
    })
  })
})
