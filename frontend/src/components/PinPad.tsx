import { useState } from 'react'
import { Button } from './ui'

export function PinPad({
  title,
  subtitle,
  onSubmit,
  onCancel,
  submitting,
  error,
}: {
  title: string
  subtitle?: string
  onSubmit: (pin: string) => void
  onCancel: () => void
  submitting?: boolean
  error?: string | null
}) {
  const [pin, setPin] = useState('')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-midnight-navy/40 px-4">
      <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-[rgba(32,41,76,0.12)_0px_9px_25px_0px]">
        <h2 className="text-[24px] font-semibold tracking-[-0.72px] text-midnight-navy">{title}</h2>
        {subtitle && <p className="mt-1 text-[16px] text-dusk">{subtitle}</p>}

        <div className="mt-6 flex justify-center gap-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className={`h-4 w-4 rounded-full border-[1.5px] border-cornflower-steel ${
                i < pin.length ? 'bg-midnight-navy' : 'bg-transparent'
              }`}
            />
          ))}
        </div>

        <input
          autoFocus
          type="password"
          inputMode="numeric"
          maxLength={6}
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 6))}
          className="mt-4 w-full rounded-xl border border-silver-lining px-4 py-3 text-center text-[18px] tracking-[8px] outline-none focus:border-electric-blue"
          placeholder="••••••"
        />

        {error && <p className="mt-2 text-[14px] text-red-500">{error}</p>}

        <div className="mt-6 flex gap-3">
          <Button variant="outlined" className="flex-1" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button
            className="flex-1"
            disabled={pin.length !== 6 || submitting}
            onClick={() => onSubmit(pin)}
          >
            {submitting ? 'Confirming…' : 'Confirm'}
          </Button>
        </div>
      </div>
    </div>
  )
}
