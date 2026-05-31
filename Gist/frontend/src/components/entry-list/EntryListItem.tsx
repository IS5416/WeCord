import { forwardRef, useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { formatRelativeTime } from '@/lib/date-utils'
import { stripHtml } from '@/lib/html-utils'
import { useTranslationStore } from '@/stores/translation-store'
import { FeedIcon } from '@/components/ui/feed-icon'
import type { Entry, Feed } from '@/types/api'

const URL_PATTERN = /\bhttps?:\/\/\S+/i

interface EntryListItemProps {
  entry: Entry
  feed?: Feed
  isSelected: boolean
  onClick: () => void
  autoTranslate?: boolean
  targetLanguage?: string
  style?: React.CSSProperties
  'data-index'?: number
  'data-entry-id'?: string
}

export const EntryListItem = forwardRef<HTMLDivElement, EntryListItemProps>(
  function EntryListItem(
    {
      entry,
      feed,
      isSelected,
      onClick,
      autoTranslate,
      targetLanguage,
      style,
      'data-index': dataIndex,
      'data-entry-id': dataEntryId,
    },
    ref
  ) {
    const { t } = useTranslation()
    const publishedAt = entry.publishedAt ? formatRelativeTime(entry.publishedAt, t) : null
    const [iconError, setIconError] = useState(false)
    const showIcon = feed?.iconPath && !iconError
    const fallbackTitle = t('entry.untitled')
    const fallbackFeedName = t('entry.unknown_feed')

    const translation = useTranslationStore((state) =>
      autoTranslate && targetLanguage
        ? state.getTranslation(entry.id, targetLanguage)
        : undefined
    )

    const strippedContent = useMemo(
      () => (entry.content ? stripHtml(entry.content).slice(0, 150) : null),
      [entry.content]
    )

    const displayTitle = translation?.title ?? entry.title
    const displaySummary = translation?.summary ?? strippedContent
    const displayFeedName = feed?.title || fallbackFeedName
    const titleContainsUrl = URL_PATTERN.test(displayTitle ?? '')
    const summaryContainsUrl = URL_PATTERN.test(displaySummary ?? '')

    return (
      <div
        ref={ref}
        className={cn(
          'w-full min-w-0 overflow-hidden px-4 py-3 cursor-pointer transition-colors',
          'hover:bg-item-hover',
          isSelected && 'bg-item-active',
          !entry.read && !isSelected && 'bg-accent/5'
        )}
        style={style}
        data-index={dataIndex}
        data-entry-id={dataEntryId}
        onClick={onClick}
      >
        {/* Line 1: icon + feed name + time */}
        <div className="flex min-w-0 items-center gap-1.5 overflow-hidden text-xs text-muted-foreground">
          {showIcon ? (
            <img
              src={`/icons/${feed.iconPath}`}
              alt=""
              className="size-4 shrink-0 rounded object-contain"
              onError={() => setIconError(true)}
            />
          ) : (
            <FeedIcon className="size-4 shrink-0 text-muted-foreground/50" />
          )}
          <span className="block min-w-0 truncate">{displayFeedName}</span>
          {publishedAt && (
            <>
              <span className="shrink-0 text-muted-foreground/50">·</span>
              <span className="shrink-0 whitespace-nowrap">{publishedAt}</span>
            </>
          )}
        </div>

        {/* Line 2: title */}
        <div
          className={cn(
            'mt-1 text-sm wrap-anywhere',
            titleContainsUrl ? 'line-clamp-3' : 'line-clamp-2',
            !entry.read ? 'font-semibold' : 'font-medium text-muted-foreground'
          )}
        >
          {displayTitle || fallbackTitle}
        </div>

        {/* Line 3: summary */}
        {displaySummary && (
          <div
            className={cn(
              'mt-1 text-xs text-muted-foreground wrap-anywhere',
              summaryContainsUrl ? 'line-clamp-3' : 'line-clamp-2'
            )}
          >
            {displaySummary}
          </div>
        )}
      </div>
    )
  }
)
