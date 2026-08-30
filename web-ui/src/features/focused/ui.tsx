"use client"

import {
  useEffect,
  useId,
  useState,
  useRef,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react"

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
