"use client"

import {
  useCallback,
  useEffect,
  useId,
  useState,
  useRef,
  type ButtonHTMLAttributes,
  type LabelHTMLAttributes,
  type ReactNode,
} from "react"
import { createPortal } from "react-dom"
import { Crown, User } from "lucide-react"

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
  variant?: "primary" | "outline" | "ghost"
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
type EvidenceTooltipPosition = {
  left: number
  top: number
  above: boolean
}

export function EvidenceHighlight({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  const tooltipId = useId()
  const markRef = useRef<HTMLElement>(null)
  const [position, setPosition] = useState<EvidenceTooltipPosition | null>(null)

  const showTooltip = useCallback((pointer?: { x: number; y: number }) => {
    const mark = markRef.current
    if (!mark) return
    const rect = mark.getBoundingClientRect()
    let scrollParent = mark.parentElement
    while (scrollParent && scrollParent !== document.body) {
      const overflowY = getComputedStyle(scrollParent).overflowY
      if (overflowY === "auto" || overflowY === "scroll") break
      scrollParent = scrollParent.parentElement
    }
    const scrollTop =
      scrollParent && scrollParent !== document.body
        ? scrollParent.getBoundingClientRect().top
        : 0
    const anchorX = pointer?.x ?? rect.left + rect.width / 2
    const anchorTop = pointer?.y ?? rect.top
    const anchorBottom = pointer?.y ?? rect.bottom
    const above = anchorTop - scrollTop >= 48
    const edge = Math.min(128, window.innerWidth / 2)
    setPosition({
      left: Math.min(Math.max(anchorX, edge), window.innerWidth - edge),
      top: above ? anchorTop - 8 : anchorBottom + 8,
      above,
    })
  }, [])

  useEffect(() => {
    if (!position) return
    const handleViewportChange = () => {
      if (document.activeElement === markRef.current) {
        window.requestAnimationFrame(() => showTooltip())
      } else {
        setPosition(null)
      }
    }
    window.addEventListener("scroll", handleViewportChange, true)
    window.addEventListener("resize", handleViewportChange)
    return () => {
      window.removeEventListener("scroll", handleViewportChange, true)
      window.removeEventListener("resize", handleViewportChange)
    }
  }, [position, showTooltip])

  return (
    <>
      <mark
        ref={markRef}
        tabIndex={0}
        aria-describedby={position ? tooltipId : undefined}
        onPointerEnter={(event) =>
          showTooltip({ x: event.clientX, y: event.clientY })
        }
        onPointerLeave={() => setPosition(null)}
        onFocus={() => showTooltip()}
        onBlur={() => setPosition(null)}
        className="rounded-[3px] bg-[var(--amber-bg)] px-0.5 text-[var(--ink)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ink-2)]"
        style={{ boxShadow: "inset 0 -2px 0 #f2c979" }}
      >
        {children}
      </mark>
      {position &&
        createPortal(
          <span
            id={tooltipId}
            role="tooltip"
            className="pointer-events-none fixed z-[100] w-max max-w-[min(240px,calc(100vw-16px))] rounded bg-[var(--ink)] px-2 py-1 text-center text-[11px] font-medium leading-tight text-white shadow-sm"
            style={{
              left: position.left,
              top: position.top,
              transform: position.above
                ? "translate(-50%, -100%)"
                : "translate(-50%, 0)",
            }}
          >
            {label}
          </span>,
          document.querySelector<HTMLElement>(".focused") ?? document.body,
        )}
    </>
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
            className="shrink-0 text-[13px] text-[var(--mute)] hover:text-[var(--ink)]"
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

export function IdentityChip({
  color,
  name,
  selected = false,
  lead = false,
  onClick,
}: {
  color: string
  name: string
  selected?: boolean
  lead?: boolean
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={lead ? "Lead Perspective" : undefined}
      className={`flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[12px] font-medium transition-colors ${
        onClick ? "hover:bg-[var(--hover)]" : "cursor-default"
      }`}
      style={
        selected ? { background: "var(--node)", color: "#fff" } : { color }
      }
    >
      {lead ? (
        <Crown
          size={12}
          strokeWidth={2}
          className="-rotate-12 shrink-0"
          aria-label="Lead"
          style={{ color: selected ? "#fff" : color }}
        />
      ) : (
        <User
          size={12}
          strokeWidth={2}
          className="shrink-0"
          aria-hidden="true"
          style={{ color: selected ? "#fff" : color }}
        />
      )}
      {name}
    </button>
  )
}

export function ListRow({
  disabled = false,
  onClick,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  disabled?: boolean
  onClick?: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      {...rest}
      className="flex w-full items-center gap-2.5 rounded-lg border border-transparent px-2.5 py-2 text-left transition-colors not-disabled:hover:border-[var(--line-strong)] not-disabled:hover:bg-[var(--hover)] disabled:cursor-default"
    >
      {children}
    </button>
  )
}

type CheckRowProps = LabelHTMLAttributes<HTMLLabelElement> & {
  checked: boolean
  onToggle: () => void
  disabled?: boolean
}

export function CheckRow({
  checked,
  onToggle,
  children,
  disabled = false,
  ...rest
}: CheckRowProps) {
  return (
    <label
      {...rest}
      className={`flex items-start gap-2.5 py-1 text-[13px] leading-snug ${
        disabled
          ? "cursor-default text-[var(--mute)]"
          : "cursor-pointer text-[var(--ink-2)]"
      }`}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={onToggle}
        className="mt-0.5 size-3.5 shrink-0 accent-[var(--node)]"
      />
      {children}
    </label>
  )
}

