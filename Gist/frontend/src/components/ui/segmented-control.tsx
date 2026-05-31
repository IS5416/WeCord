import * as React from 'react'
import { motion } from 'motion/react'
import { cn } from '@/lib/utils'

interface SegmentedControlProps<T extends string> {
  value: T
  onValueChange: (value: T) => void
  options: { value: T; label: React.ReactNode }[]
  className?: string
}

export function SegmentedControl<T extends string>({
  value,
  onValueChange,
  options,
  className,
}: SegmentedControlProps<T>) {
  const id = React.useId()

  return (
    <div
      role="tablist"
      className={cn(
        'flex h-8 items-center rounded-lg border border-border bg-muted/30 p-1',
        className
      )}
    >
      {options.map((option) => {
        const isActive = value === option.value
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            onClick={() => onValueChange(option.value)}
            className={cn(
              'relative flex h-6 items-center gap-1.5 rounded-md px-3 text-sm font-medium transition-colors',
              isActive ? 'text-foreground' : 'text-muted-foreground hover:text-foreground'
            )}
            data-state={isActive ? 'active' : 'inactive'}
          >
            <span className="z-[1] flex items-center gap-1.5">{option.label}</span>
            {isActive && (
              <motion.span
                layoutId={id}
                className="absolute inset-0 z-0 rounded-md bg-background shadow-sm"
                transition={{
                  type: 'spring',
                  duration: 0.4,
                  bounce: 0,
                }}
              />
            )}
          </button>
        )
      })}
    </div>
  )
}
