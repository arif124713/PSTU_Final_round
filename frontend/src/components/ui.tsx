import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react'

export function Button({
  variant = 'filled',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'filled' | 'outlined' }) {
  const base =
    'rounded-full px-4 py-3 text-[16px] font-semibold transition-opacity disabled:opacity-50 disabled:cursor-not-allowed'
  const styles =
    variant === 'filled'
      ? 'bg-midnight-navy text-white shadow-[rgba(32,41,76,0.1)_0px_1px_4px_0px] hover:opacity-90'
      : 'bg-transparent border-[1.5px] border-cornflower-steel text-cornflower-steel hover:bg-fog-white'
  return <button className={`${base} ${styles} ${className}`} {...props} />
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={`bg-white rounded-xl p-6 shadow-[rgba(32,41,76,0.12)_0px_9px_25px_0px] ${className}`}
    >
      {children}
    </div>
  )
}

export function Input({ label, error, className = '', ...props }: InputHTMLAttributes<HTMLInputElement> & { label?: string; error?: string }) {
  return (
    <label className="flex flex-col gap-2">
      {label && <span className="text-[14px] font-medium text-dusk">{label}</span>}
      <input
        className={`rounded-xl border border-silver-lining bg-white px-4 py-3 text-[16px] text-midnight-navy outline-none focus:border-electric-blue ${className}`}
        {...props}
      />
      {error && <span className="text-[14px] text-red-500">{error}</span>}
    </label>
  )
}

export function CategoryTag({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-fog-white px-2 py-1.5 text-[10px] font-semibold uppercase tracking-[0.4px] text-smoke">
      {label}
    </span>
  )
}

export function TransactionAmount({ amount, direction }: { amount: number; direction: 'sent' | 'received' }) {
  const sign = direction === 'sent' ? '−' : '+'
  const color = direction === 'sent' ? 'text-midnight-navy' : 'text-electric-blue'
  return (
    <span className={`text-[24px] font-semibold tracking-[-0.72px] ${color}`}>
      {sign}৳{amount.toLocaleString('en-BD', { minimumFractionDigits: 2 })}
    </span>
  )
}

export function NavPill({ children }: { children: ReactNode }) {
  return (
    <nav className="sticky top-4 z-10 mx-auto flex w-fit items-center gap-8 rounded-3xl bg-fog-white px-8 py-4 shadow-[rgba(32,41,76,0.12)_0px_6px_16px_0px,rgba(32,41,76,0.09)_0px_1px_5px_0px]">
      {children}
    </nav>
  )
}
