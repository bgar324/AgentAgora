"use client"

import {
  useCallback,
  useEffect,
  useId,
  useState,
  useRef,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react"
import { Check, ChevronDown } from "lucide-react"

/** Design-system primitives — the only sanctioned building blocks for
 * Focused Panel surfaces. See ./DESIGN.md. */

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={`inline-block size-3 animate-spin rounded-full border-2 border-current border-t-transparent align-[-1px] ${className}`}
    />
  )
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "outline" | "ghost" | "danger"
  size?: "sm" | "md"
}

export function Button({
  variant = "outline",
  size = "sm",
  className = "",
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      {...props}
      className={`btn btn-${variant} btn-${size} ${className}`}
    />
  )
}

export function SectionLabel({
  htmlFor,
  children,
}: {
  htmlFor?: string
  children: ReactNode
}) {
  if (htmlFor) {
    return (
      <label
        htmlFor={htmlFor}
        className="mb-1.5 block text-[12px] font-medium text-[var(--mute)]"
      >
        {children}
      </label>
    )
  }
  return (
    <div className="text-[12px] font-medium text-[var(--mute)]">
      {children}
    </div>
  )
}



export function EmptyLine({ children }: { children: ReactNode }) {
  return <p className="text-[13px] text-[var(--mute)]">{children}</p>
}

const FOCUSABLE = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",")

const DIALOG_STACK: symbol[] = []


export function useDialogSurface<T extends HTMLElement>(onClose: () => void) {
  const surfaceRef = useRef<T>(null)
  const closeRef = useRef(onClose)
  const [stackId] = useState(() => Symbol("dialog-surface"))
  useEffect(() => {
    closeRef.current = onClose
  }, [onClose])

  useEffect(() => {
    const surface = surfaceRef.current
    if (!surface) return
    DIALOG_STACK.push(stackId)
    const previousFocus =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"

    const focusable = () =>
      [...surface.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
        (element) => element.getClientRects().length > 0,
      )
    const initial =
      surface.querySelector<HTMLElement>("[data-autofocus]") ??
      focusable()[0] ??
      surface
    initial.focus()

    const onKeyDown = (event: KeyboardEvent) => {
      if (DIALOG_STACK.at(-1) !== stackId) return
      if (event.key === "Escape") {
        event.preventDefault()
        event.stopPropagation()
        closeRef.current()
        return
      }
      if (event.key !== "Tab") return
      const items = focusable()
      if (!items.length) {
        event.preventDefault()
        surface.focus()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener("keydown", onKeyDown, true)
    return () => {
      document.removeEventListener("keydown", onKeyDown, true)
      const stackIndex = DIALOG_STACK.lastIndexOf(stackId)
      if (stackIndex >= 0) DIALOG_STACK.splice(stackIndex, 1)
      document.body.style.overflow = previousOverflow
      previousFocus?.focus()
    }
  }, [stackId])

  return surfaceRef
}


export function ModalShell({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
}) {
  const titleId = useId()
  const surfaceRef = useDialogSurface<HTMLDivElement>(onClose)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        aria-hidden="true"
        className="ep-fade-in absolute inset-0 bg-[rgba(16,24,40,0.4)]"
        onClick={onClose}
      />
      <div
        ref={surfaceRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`ep-modal-enter panel relative flex max-h-[86vh] flex-col overflow-hidden rounded-[12px] ${
          wide ? "w-[min(760px,92vw)]" : "w-[min(640px,92vw)]"
        }`}
        style={{ boxShadow: "var(--shadow-modal)" }}
      >
        <div className="flex min-h-12 shrink-0 items-center gap-4 border-b border-[var(--line)] px-5 py-3">
          <div
            id={titleId}
            className="flex-1 text-[16px] font-semibold leading-snug tracking-[-0.01em]"
          >
            {title}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={`Close ${title}`}
            className="flex size-7 shrink-0 items-center justify-center rounded-lg text-[13px] text-[var(--mute)] transition-colors hover:bg-[var(--hover)] hover:text-[var(--ink)]"
          >
            ✕
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
          {children}
        </div>
      </div>
    </div>
  )
}

const TURN_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8]

export function TurnSelect({
  value,
  onChange,
  disabled = false,
}: {
  value: number
  onChange: (value: number) => void
  disabled?: boolean
}) {
  const id = useId()
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(value)
  const close = useCallback(() => {
    if (menu.current?.matches(":popover-open")) menu.current.hidePopover()
  }, [])

  useEffect(() => {
    if (disabled) close()
  }, [close, disabled])

  useEffect(() => {
    if (!open) return
    const onScroll = (event: Event) => {
      if (
        event.target === window ||
        (event.target instanceof Node && event.target.contains(trigger.current))
      ) {
        close()
      }
    }
    window.addEventListener("resize", close)
    window.addEventListener("scroll", onScroll, true)
    return () => {
      window.removeEventListener("resize", close)
      window.removeEventListener("scroll", onScroll, true)
    }
  }, [close, open])

  useEffect(() => {
    const popup = menu.current
    const option = document.getElementById(`${id}-${active}`)
    if (open && popup && option) {
      popup.scrollTop = option.offsetTop - (popup.clientHeight - option.offsetHeight) / 2
    }
  }, [active, id, open])

  const prepare = () => {
    const button = trigger.current
    const popup = menu.current
    if (!button || !popup || popup.matches(":popover-open")) return
    const rect = button.getBoundingClientRect()
    const above = Math.max(0, rect.top - 14)
    const below = Math.max(0, window.innerHeight - rect.bottom - 14)
    const placeAbove = above >= 270 || above >= below
    const height = Math.min(270, placeAbove ? above : below)
    popup.style.left = `${Math.max(8, Math.min(rect.right - 128, window.innerWidth - 136))}px`
    popup.style.top = `${placeAbove ? rect.top - height - 6 : rect.bottom + 6}px`
    popup.style.maxHeight = `${height}px`
    setActive(value)
  }

  const choose = (count: number) => {
    onChange(count)
    close()
  }

  return (
    <div className="flex w-[88px] shrink-0 items-center border-l border-[var(--line)]">
      <button
        ref={trigger}
        type="button"
        role="combobox"
        aria-label="Turns"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={id}
        aria-activedescendant={open ? `${id}-${active}` : undefined}
        popoverTarget={id}
        disabled={disabled}
        onClick={prepare}
        onKeyDown={(event) => {
          const showing = menu.current?.matches(":popover-open") ?? false
          if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
            event.preventDefault()
            if (!showing) trigger.current?.click()
            if (event.key === "Home") setActive(1)
            else if (event.key === "End") setActive(8)
            else if (showing) {
              setActive((current) => Math.max(1, Math.min(8,
                current + (event.key === "ArrowDown" ? 1 : -1),
              )))
            }
          } else if (showing && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault()
            choose(active)
          } else if (showing && event.key === "Escape") {
            event.preventDefault()
            close()
          } else if (showing && event.key === "Tab") {
            choose(active)
          } else if (/^[1-8]$/.test(event.key)) {
            event.preventDefault()
            if (showing) setActive(Number(event.key))
            else onChange(Number(event.key))
          }
        }}
        className="inline-flex h-full w-full items-center justify-between gap-1 px-2.5 text-[13px] font-medium tabular-nums text-[var(--ink-2)] outline-none enabled:hover:bg-[var(--hover)] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--ink-2)] disabled:opacity-40"
      >
        <span>{`${value} ${value === 1 ? "turn" : "turns"}`}</span>
        <ChevronDown size={12} aria-hidden />
      </button>
      <div
        ref={menu}
        id={id}
        popover="auto"
        role="listbox"
        aria-label="Turns"
        onToggle={(event) => setOpen(event.currentTarget.matches(":popover-open"))}
        style={{ inset: "auto", width: 128 }}
        className="ep-expand-enter m-0 overflow-y-auto overscroll-contain rounded-lg border border-[var(--line-strong)] bg-[var(--panel)] p-1.5 text-[var(--ink)] shadow-lg"
      >
        {TURN_OPTIONS.map((count) => (
          <button
            key={count}
            id={`${id}-${count}`}
            type="button"
            role="option"
            aria-selected={value === count}
            tabIndex={-1}
            onPointerMove={() => setActive(count)}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => {
              choose(count)
              trigger.current?.focus({ preventScroll: true })
            }}
            className={`flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-[12.5px] ${
              active === count ? "bg-[var(--hover)]" : ""
            }`}
          >
            <span className="w-3 shrink-0">
              {value === count ? <Check size={12} aria-hidden /> : null}
            </span>
            {`${count} ${count === 1 ? "turn" : "turns"}`}
          </button>
        ))}
      </div>
    </div>
  )
}
