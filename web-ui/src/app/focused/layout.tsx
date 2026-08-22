import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Hypothesis Studio | Focused Panel",
  other: { "study-condition": "focused" },
}

/*
 * Focused Panel design system tokens — see features/focused/DESIGN.md.
 * Premium-minimal: one typeface, gray ramp, hairlines, restrained
 * semantic color. Hierarchy from weight/size/gray — never uppercase.
 */
const tokens = `
.focused {
  --bg: #fafafa;
  --panel: #ffffff;
  --ink: #101828;
  --ink-2: #475467;
  --mute: #98a2b3;
  --line: rgba(16, 24, 40, 0.08);
  --line-strong: rgba(16, 24, 40, 0.16);
  --hover: #f5f5f5;
  --green: #067647;
  --green-bg: #ecfdf3;
  --amber: #b54708;
  --amber-bg: #fffaeb;
  --red: #d92d20;
  --node: #101828;
  --on-node: #b6bfcc;
  --on-node-accent: #7cc5ab;
  --wire: #d0d5dd;
  --shadow-modal: 0 20px 50px rgba(16, 24, 40, 0.16);
  --motion-fast: 120ms;
  --motion-enter: 260ms;
  --motion-ease: cubic-bezier(0.22, 1, 0.36, 1);
  background: var(--bg);
  color: var(--ink);
  font-feature-settings: "cv11", "ss01";
}
.focused .panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  transition: border-color var(--motion-fast) ease,
    box-shadow var(--motion-fast) ease, transform var(--motion-fast) ease;
}
.focused .field {
  background: var(--panel);
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  transition: border-color 0.12s ease, box-shadow 0.12s ease;
}
.focused .field:focus {
  outline: none;
  border-color: var(--ink-2);
  box-shadow: 0 0 0 3px rgba(16, 24, 40, 0.06);
}
.focused .btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-radius: 8px;
  font-weight: 500;
  transition: opacity var(--motion-fast) ease,
    background var(--motion-fast) ease,
    border-color var(--motion-fast) ease, color var(--motion-fast) ease,
    transform var(--motion-fast) ease, box-shadow var(--motion-fast) ease;
}
.focused .btn:active:not(:disabled) {
  transform: translateY(1px) scale(0.985);
}
.focused .btn:focus-visible,
.focused .field:focus-visible {
  outline: 2px solid var(--ink-2);
  outline-offset: 1px;
}
.focused .btn-primary {
  background: var(--node);
  color: #fff;
}
.focused .btn-primary:hover:not(:disabled) { opacity: 0.85; }
.focused .btn-primary:disabled { background: rgba(16, 24, 40, 0.14); color: #fff; }
.focused .btn-outline {
  border: 1px solid var(--line-strong);
  color: var(--ink);
  background: var(--panel);
}
.focused .btn-outline:hover:not(:disabled) { background: var(--hover); }
.focused .btn-outline:disabled { color: var(--mute); }
.focused .btn-ghost {
  border: 1px solid transparent;
  color: var(--ink-2);
  background: transparent;
}
.focused .btn-ghost:hover:not(:disabled) { background: var(--hover); color: var(--ink); }
.focused .btn-ghost:disabled { color: var(--mute); }
.focused .btn-sm { height: 28px; padding: 0 10px; font-size: 12px; }
.focused .btn-md { height: 32px; padding: 0 12px; font-size: 13px; }
.focused input,
.focused textarea,
.focused select { font-family: inherit; }

@keyframes ep-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes ep-rise-in {
  from { opacity: 0; transform: translateY(8px) scale(0.992); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
@keyframes ep-slide-in {
  from { opacity: 0; transform: translateX(18px); }
  to { opacity: 1; transform: translateX(0); }
}
@keyframes ep-pop-in {
  from { opacity: 0; transform: translateY(4px) scale(0.97); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
@keyframes ep-expand-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
.focused .ep-enter,
.focused .ep-card-enter,
.focused .ep-node-enter {
  opacity: 1;
  animation: ep-rise-in var(--motion-enter) var(--motion-ease) backwards;
}
.focused .ep-fade-in {
  opacity: 1;
  animation: ep-fade-in 180ms ease backwards;
}
.focused .ep-drawer-enter {
  animation: ep-slide-in 220ms var(--motion-ease) backwards;
}
.focused .ep-modal-enter {
  animation: ep-pop-in 180ms var(--motion-ease) backwards;
}
.focused .ep-expand-enter {
  animation: ep-expand-in 180ms var(--motion-ease) backwards;
}
.focused .ep-success-state {
  color: var(--green) !important;
  background: var(--green-bg) !important;
  border-color: rgba(6, 118, 71, 0.24) !important;
  opacity: 1 !important;
}
.focused .ep-interactive-card {
  transition: transform 160ms var(--motion-ease),
    border-color 160ms ease, box-shadow 160ms ease;
}
.focused .ep-interactive-card:hover {
  transform: translateY(-1px);
  border-color: var(--line-strong);
  box-shadow: 0 8px 20px -18px rgba(16, 24, 40, 0.45);
}
@media (prefers-reduced-motion: reduce) {
  .focused .ep-enter,
  .focused .ep-card-enter,
  .focused .ep-node-enter,
  .focused .ep-fade-in,
  .focused .ep-drawer-enter,
  .focused .ep-modal-enter,
  .focused .ep-expand-enter {
    opacity: 1 !important;
    animation: none !important;
    transform: none !important;
  }
  .focused .btn,
  .focused .panel,
  .focused .field,
  .focused .ep-interactive-card {
    transition-duration: 0.01ms !important;
  }
}
`

export default function FocusedLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="focused min-h-screen">
      <style dangerouslySetInnerHTML={{ __html: tokens }} />
      {children}
    </div>
  )
}
