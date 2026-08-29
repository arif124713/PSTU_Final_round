import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react'
import { useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'

/* ── Card ─────────────────────────────────────────────────────────────── */
export function GlassCard({
  children,
  className = '',
  interactive = false,
}: {
  children: ReactNode
  className?: string
  interactive?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)

  function handleMove(e: React.MouseEvent<HTMLDivElement>) {
    const el = ref.current
    if (!interactive || !el) return
    const rect = el.getBoundingClientRect()
    el.style.setProperty('--mx', `${e.clientX - rect.left}px`)
    el.style.setProperty('--my', `${e.clientY - rect.top}px`)
  }

  return (
    <div
      ref={ref}
      onMouseMove={handleMove}
      className={`glass-panel glass-card ${interactive ? 'glass-card--interactive' : ''} ${className}`}
    >
      {children}
    </div>
  )
}

/* ── Button ───────────────────────────────────────────────────────────── */
type GlassButtonVariant = 'primary' | 'glass' | 'danger' | 'ghost'

const BUTTON_VARIANTS: Record<GlassButtonVariant, string> = {
  primary:
    'text-white bg-gradient-to-b from-cornflower-steel to-midnight-navy shadow-[0_10px_28px_rgba(32,41,76,0.35)] hover:shadow-[0_14px_36px_rgba(32,41,76,0.45)] hover:-translate-y-0.5',
  glass:
    'text-midnight-navy bg-white/55 backdrop-blur-md border border-white/70 shadow-[0_6px_18px_rgba(32,41,76,0.12)] hover:bg-white/75 hover:-translate-y-0.5',
  danger:
    'text-white bg-gradient-to-b from-rose-400 to-rose-600 shadow-[0_10px_28px_rgba(225,29,72,0.32)] hover:-translate-y-0.5',
  ghost: 'text-cornflower-steel hover:text-midnight-navy hover:bg-white/60',
}

export function GlassButton({
  variant = 'primary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: GlassButtonVariant }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-full px-5 py-2.5 text-[15px] font-semibold transition-all duration-300 active:scale-[0.97] disabled:pointer-events-none disabled:opacity-40 ${BUTTON_VARIANTS[variant]} ${className}`}
      {...props}
    />
  )
}

/* ── Inputs ───────────────────────────────────────────────────────────── */
export function GlassField({
  label,
  hint,
  className = '',
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label?: string; hint?: string }) {
  return (
    <label className="flex flex-col gap-1.5">
      {label && <span className="text-[13px] font-semibold text-dusk">{label}</span>}
      <input className={`glass-input ${className}`} {...props} />
      {hint && <span className="text-[12px] text-smoke">{hint}</span>}
    </label>
  )
}

export function GlassSelect({
  label,
  children,
  className = '',
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label?: string }) {
  return (
    <label className="flex flex-col gap-1.5">
      {label && <span className="text-[13px] font-semibold text-dusk">{label}</span>}
      <select className={`glass-input appearance-none ${className}`} {...props}>
        {children}
      </select>
    </label>
  )
}

export function GlassTextarea({
  label,
  className = '',
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { label?: string }) {
  return (
    <label className="flex flex-col gap-1.5">
      {label && <span className="text-[13px] font-semibold text-dusk">{label}</span>}
      <textarea className={`glass-input min-h-[84px] resize-y ${className}`} {...props} />
    </label>
  )
}

/* ── Status pill ──────────────────────────────────────────────────────── */
const STATUS_TONES: Record<string, string> = {
  active: 'text-emerald-700 bg-emerald-100/70 border-emerald-200/80',
  agreed_paid: 'text-emerald-700 bg-emerald-100/70 border-emerald-200/80',
  fully_paid: 'text-emerald-700 bg-emerald-100/70 border-emerald-200/80',
  completed: 'text-emerald-700 bg-emerald-100/70 border-emerald-200/80',
  paid: 'text-emerald-700 bg-emerald-100/70 border-emerald-200/80',
  open: 'text-sky-700 bg-sky-100/70 border-sky-200/80',
  pending: 'text-amber-700 bg-amber-100/70 border-amber-200/80',
  paused: 'text-amber-700 bg-amber-100/70 border-amber-200/80',
  agreed_debt: 'text-amber-700 bg-amber-100/70 border-amber-200/80',
  partially_paid: 'text-amber-700 bg-amber-100/70 border-amber-200/80',
  reminder_sent: 'text-sky-700 bg-sky-100/70 border-sky-200/80',
  missed: 'text-rose-700 bg-rose-100/70 border-rose-200/80',
  declined: 'text-rose-700 bg-rose-100/70 border-rose-200/80',
  cancelled: 'text-rose-700 bg-rose-100/70 border-rose-200/80',
  debt_cancelled: 'text-slate-600 bg-slate-100/70 border-slate-200/80',
  expired: 'text-slate-600 bg-slate-100/70 border-slate-200/80',
  skipped: 'text-slate-600 bg-slate-100/70 border-slate-200/80',
  refunded: 'text-slate-600 bg-slate-100/70 border-slate-200/80',
}

export function StatusPill({ value }: { value: string }) {
  const tone = STATUS_TONES[value] ?? 'text-dusk bg-white/60 border-white/70'
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.4px] backdrop-blur ${tone}`}
    >
      {value.replace(/_/g, ' ')}
    </span>
  )
}

/* ── Segmented control ────────────────────────────────────────────────── */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[]
  value: T
  onChange: (v: T) => void
}) {
  return (
    <div className="inline-flex rounded-full glass-panel p-1">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-full px-4 py-1.5 text-[13px] font-semibold transition-all ${
            value === o.value
              ? 'bg-midnight-navy text-white shadow-[0_6px_16px_rgba(32,41,76,0.3)]'
              : 'text-dusk hover:text-midnight-navy'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

/* ── Modal ────────────────────────────────────────────────────────────── */
export function GlassModal({
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
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-midnight-navy/30 px-4 py-10 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className={`glass-panel glass-card w-full ${wide ? 'max-w-xl' : 'max-w-md'} p-6`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-[22px] font-bold tracking-[-0.6px] text-midnight-navy">{title}</h2>
          <button
            onClick={onClose}
            className="-mr-1 -mt-1 rounded-full px-2 text-[22px] leading-none text-smoke transition-colors hover:text-midnight-navy"
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <div className="mt-4">{children}</div>
      </div>
    </div>
  )
}

/* ── Top navigation ───────────────────────────────────────────────────── */
const NAV_ITEMS: { label: string; to: string }[] = [
  { label: 'Dashboard', to: '/dashboard' },
  { label: 'Send', to: '/send' },
  { label: 'Scheduled', to: '/scheduled' },
  { label: 'Groups', to: '/groups' },
  { label: 'Debts', to: '/debts' },
  { label: 'History', to: '/history' },
  { label: 'Assistant', to: '/agent' },
]

export function GlassNav({ active }: { active: string }) {
  const navigate = useNavigate()
  const logout = useAuthStore((s) => s.logout)

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <nav className="glass-panel sticky top-4 z-30 mx-auto flex w-fit max-w-[95vw] flex-wrap items-center justify-center gap-1 rounded-full px-3 py-2">
      <span className="px-3 text-[15px] font-bold tracking-[-0.4px] text-midnight-navy">MoneyMove</span>
      {NAV_ITEMS.map((item) => (
        <Link
          key={item.to}
          to={item.to}
          className={`rounded-full px-3.5 py-1.5 text-[13.5px] font-semibold transition-all ${
            active === item.label
              ? 'bg-midnight-navy text-white shadow-[0_6px_16px_rgba(32,41,76,0.3)]'
              : 'text-dusk hover:bg-white/60 hover:text-midnight-navy'
          }`}
        >
          {item.label}
        </Link>
      ))}
      <button
        onClick={handleLogout}
        className="rounded-full px-3.5 py-1.5 text-[13.5px] font-semibold text-cornflower-steel transition-colors hover:bg-white/60"
      >
        Log out
      </button>
    </nav>
  )
}

/* ── Misc ─────────────────────────────────────────────────────────────── */
export function PageShell({ children }: { children: ReactNode }) {
  return <div className="min-h-screen px-4 pb-20 pt-8">{children}</div>
}

export function Money({ value, className = '' }: { value: number; className?: string }) {
  return (
    <span className={className}>
      ৳{value.toLocaleString('en-BD', { minimumFractionDigits: 2 })}
    </span>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-silver-lining/80 bg-white/40 px-6 py-10 text-center text-[15px] text-dusk">
      {children}
    </div>
  )
}
