import { useEffect, useState } from 'react'
import { api, apiErrorMessage } from '../lib/api'
import { useAuthStore } from '../store/authStore'
import { PinPad } from '../components/PinPad'
import {
  EmptyState,
  GlassButton,
  GlassCard,
  GlassField,
  GlassModal,
  GlassNav,
  GlassSelect,
  GlassTextarea,
  Money,
  PageShell,
  StatusPill,
} from '../components/glass'

interface Receiver {
  full_name: string
  mobile_last4: string
}

interface ScheduledItem {
  id: number
  reference_id: string
  label: string
  amount: number
  frequency: string
  specific_date: string | null
  day_of_week: number | null
  day_of_month: number | null
  month_of_year: number | null
  next_payment_date: string | null
  reminder_days_before: number
  status: string
  last_paid_at: string | null
  total_paid_count: number
  receiver: Receiver
}

interface HistoryRow {
  cycle_date: string
  status: string
  transaction_id: number | null
  paid_at: string | null
  created_at: string
}

const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

function fmtDate(d: string | null) {
  return d ? new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'
}

function scheduleSummary(s: ScheduledItem) {
  if (s.frequency === 'one_time') return `One time · ${fmtDate(s.specific_date)}`
  if (s.frequency === 'weekly') return `Every ${WEEKDAYS[s.day_of_week ?? 0]}`
  if (s.frequency === 'monthly') return `Monthly · day ${s.day_of_month}`
  if (s.frequency === 'yearly') return `Yearly · ${MONTHS[(s.month_of_year ?? 1) - 1]} ${s.day_of_month}`
  return s.frequency
}

export function Scheduled() {
  const updateBalance = useAuthStore((s) => s.updateBalance)
  const [items, setItems] = useState<ScheduledItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [detailId, setDetailId] = useState<number | null>(null)
  const [payTarget, setPayTarget] = useState<ScheduledItem | null>(null)
  const [payError, setPayError] = useState<string | null>(null)
  const [paying, setPaying] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    try {
      const { data } = await api.get('/scheduled')
      setItems(data.scheduled_payments)
      setError(null)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  function flash(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(null), 3200)
  }

  async function act(id: number, path: string, method: 'post' | 'delete' = 'post') {
    try {
      if (method === 'delete') await api.delete(`/scheduled/${id}${path}`)
      else await api.post(`/scheduled/${id}${path}`)
      flash('Updated')
      load()
    } catch (err) {
      flash(apiErrorMessage(err))
    }
  }

  async function handlePay(pin: string) {
    if (!payTarget) return
    setPaying(true)
    setPayError(null)
    try {
      const { data } = await api.post(`/scheduled/${payTarget.id}/pay-now`, { pin })
      updateBalance(data.new_balance)
      setPayTarget(null)
      flash(`Paid ${payTarget.label}. Next due ${fmtDate(data.next_payment_date)}`)
      load()
    } catch (err) {
      setPayError(apiErrorMessage(err))
    } finally {
      setPaying(false)
    }
  }

  return (
    <PageShell>
      <GlassNav active="Scheduled" />

      <div className="mx-auto mt-10 flex max-w-3xl flex-col gap-5">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h1 className="text-[34px] font-bold tracking-[-1px] text-midnight-navy">Scheduled payments</h1>
            <p className="mt-1 text-[15px] text-dusk">
              Reminders only — nothing is paid until you confirm with your PIN.
            </p>
          </div>
          <GlassButton onClick={() => setShowCreate(true)}>+ New schedule</GlassButton>
        </div>

        {loading && <p className="text-[15px] text-dusk">Loading…</p>}
        {error && <p className="text-[14px] text-rose-600">{error}</p>}
        {!loading && items.length === 0 && (
          <EmptyState>No scheduled payments yet. Create one to get a nudge before every due date.</EmptyState>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          {items.map((s) => (
            <GlassCard key={s.id} interactive className="flex flex-col gap-3 p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[17px] font-semibold text-midnight-navy">{s.label}</p>
                  <p className="text-[13px] text-dusk">
                    to {s.receiver.full_name} · ****{s.receiver.mobile_last4}
                  </p>
                </div>
                <StatusPill value={s.status} />
              </div>

              <Money value={s.amount} className="text-[26px] font-bold tracking-[-0.8px] text-midnight-navy" />

              <div className="flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-dusk">
                <span>{scheduleSummary(s)}</span>
                <span>Next: {fmtDate(s.next_payment_date)}</span>
                <span>Remind {s.reminder_days_before}d before</span>
                <span>Paid {s.total_paid_count}×</span>
              </div>

              <div className="mt-1 flex flex-wrap gap-2">
                {s.status === 'active' && s.next_payment_date && (
                  <GlassButton className="px-4 py-2 text-[13px]" onClick={() => { setPayError(null); setPayTarget(s) }}>
                    Pay now
                  </GlassButton>
                )}
                {s.status === 'active' && (
                  <GlassButton variant="glass" className="px-4 py-2 text-[13px]" onClick={() => act(s.id, '/pause')}>
                    Pause
                  </GlassButton>
                )}
                {s.status === 'paused' && (
                  <GlassButton variant="glass" className="px-4 py-2 text-[13px]" onClick={() => act(s.id, '/resume')}>
                    Resume
                  </GlassButton>
                )}
                <GlassButton variant="glass" className="px-4 py-2 text-[13px]" onClick={() => setDetailId(s.id)}>
                  Details
                </GlassButton>
                {(s.status === 'active' || s.status === 'paused') && (
                  <GlassButton
                    variant="ghost"
                    className="px-4 py-2 text-[13px]"
                    onClick={() => act(s.id, '', 'delete')}
                  >
                    Cancel
                  </GlassButton>
                )}
              </div>
            </GlassCard>
          ))}
        </div>
      </div>

      {toast && (
        <div className="glass-panel fixed bottom-6 left-1/2 z-40 -translate-x-1/2 rounded-full px-5 py-2.5 text-[14px] font-semibold text-midnight-navy">
          {toast}
        </div>
      )}

      {showCreate && (
        <CreateScheduleModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false)
            flash('Schedule created')
            load()
          }}
        />
      )}

      {detailId !== null && <DetailModal id={detailId} onClose={() => setDetailId(null)} onChanged={load} />}

      {payTarget && (
        <PinPad
          title="Confirm scheduled payment"
          subtitle={`Pay ৳${payTarget.amount.toLocaleString()} to ${payTarget.receiver.full_name} for "${payTarget.label}"`}
          onSubmit={handlePay}
          onCancel={() => setPayTarget(null)}
          submitting={paying}
          error={payError}
        />
      )}
    </PageShell>
  )
}

/* ── Create ───────────────────────────────────────────────────────────── */
function CreateScheduleModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [receiver, setReceiver] = useState('')
  const [label, setLabel] = useState('')
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [frequency, setFrequency] = useState('monthly')
  const [specificDate, setSpecificDate] = useState('')
  const [dayOfWeek, setDayOfWeek] = useState('5')
  const [dayOfMonth, setDayOfMonth] = useState('1')
  const [monthOfYear, setMonthOfYear] = useState('1')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [reminderDays, setReminderDays] = useState('3')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const body: Record<string, unknown> = {
        receiver_identifier: receiver.trim(),
        label: label.trim(),
        amount: Number(amount),
        note: note.trim() || undefined,
        frequency,
        reminder_days_before: Number(reminderDays),
        start_date: startDate || undefined,
        end_date: endDate || undefined,
      }
      if (frequency === 'one_time') body.specific_date = specificDate || undefined
      if (frequency === 'weekly') body.day_of_week = Number(dayOfWeek)
      if (frequency === 'monthly') body.day_of_month = Number(dayOfMonth)
      if (frequency === 'yearly') {
        body.day_of_month = Number(dayOfMonth)
        body.month_of_year = Number(monthOfYear)
      }
      await api.post('/scheduled/create', body)
      onCreated()
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <GlassModal title="New scheduled payment" onClose={onClose} wide>
      <form className="flex flex-col gap-3" onSubmit={submit}>
        <GlassField
          label="Receiver (mobile or user ID)"
          value={receiver}
          onChange={(e) => setReceiver(e.target.value)}
          placeholder="+8801XXXXXXXXX"
          required
        />
        <div className="grid gap-3 sm:grid-cols-2">
          <GlassField label="Label" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="House Rent" required />
          <GlassField
            label="Amount (BDT)"
            type="number"
            min="1"
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            required
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <GlassSelect label="Frequency" value={frequency} onChange={(e) => setFrequency(e.target.value)}>
            <option value="one_time">One time</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
            <option value="yearly">Yearly</option>
          </GlassSelect>
          <GlassField
            label="Remind days before"
            type="number"
            min="0"
            max="30"
            value={reminderDays}
            onChange={(e) => setReminderDays(e.target.value)}
          />
        </div>

        {frequency === 'one_time' && (
          <GlassField
            label="Payment date"
            type="date"
            value={specificDate}
            onChange={(e) => setSpecificDate(e.target.value)}
            required
          />
        )}
        {frequency === 'weekly' && (
          <GlassSelect label="Day of week" value={dayOfWeek} onChange={(e) => setDayOfWeek(e.target.value)}>
            {WEEKDAYS.map((d, i) => (
              <option key={d} value={i}>{d}</option>
            ))}
          </GlassSelect>
        )}
        {(frequency === 'monthly' || frequency === 'yearly') && (
          <div className="grid gap-3 sm:grid-cols-2">
            {frequency === 'yearly' && (
              <GlassSelect label="Month" value={monthOfYear} onChange={(e) => setMonthOfYear(e.target.value)}>
                {MONTHS.map((m, i) => (
                  <option key={m} value={i + 1}>{m}</option>
                ))}
              </GlassSelect>
            )}
            <GlassField
              label="Day of month (1–28)"
              type="number"
              min="1"
              max="28"
              value={dayOfMonth}
              onChange={(e) => setDayOfMonth(e.target.value)}
            />
          </div>
        )}

        {frequency !== 'one_time' && (
          <div className="grid gap-3 sm:grid-cols-2">
            <GlassField label="Start date (optional)" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            <GlassField label="End date (optional)" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </div>
        )}

        <GlassTextarea label="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />

        {error && <p className="text-[13px] text-rose-600">{error}</p>}

        <div className="mt-1 flex gap-2">
          <GlassButton variant="glass" type="button" className="flex-1" onClick={onClose}>
            Cancel
          </GlassButton>
          <GlassButton type="submit" className="flex-1" disabled={busy}>
            {busy ? 'Creating…' : 'Create schedule'}
          </GlassButton>
        </div>
      </form>
    </GlassModal>
  )
}

/* ── Detail ───────────────────────────────────────────────────────────── */
function DetailModal({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const [detail, setDetail] = useState<(ScheduledItem & { history: HistoryRow[] }) | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [label, setLabel] = useState('')
  const [amount, setAmount] = useState('')
  const [reminderDays, setReminderDays] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  async function load() {
    try {
      const { data } = await api.get(`/scheduled/${id}`)
      setDetail(data)
      setLabel(data.label)
      setAmount(String(data.amount))
      setReminderDays(String(data.reminder_days_before))
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  useEffect(() => {
    load()
  }, [id])

  async function saveEdit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      await api.put(`/scheduled/${id}`, {
        label: label.trim(),
        amount: Number(amount),
        reminder_days_before: Number(reminderDays),
        note: note.trim() || undefined,
      })
      setEditing(false)
      await load()
      onChanged()
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <GlassModal title={detail?.label ?? 'Schedule'} onClose={onClose} wide>
      {error && <p className="text-[13px] text-rose-600">{error}</p>}
      {!detail && !error && <p className="text-[14px] text-dusk">Loading…</p>}

      {detail && !editing && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <Money value={detail.amount} className="text-[28px] font-bold tracking-[-0.8px] text-midnight-navy" />
            <StatusPill value={detail.status} />
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-[13px] text-dusk">
            <span>Receiver</span>
            <span className="text-midnight-navy">{detail.receiver.full_name} · ****{detail.receiver.mobile_last4}</span>
            <span>Schedule</span>
            <span className="text-midnight-navy">{scheduleSummary(detail)}</span>
            <span>Next payment</span>
            <span className="text-midnight-navy">{fmtDate(detail.next_payment_date)}</span>
            <span>Last paid</span>
            <span className="text-midnight-navy">{detail.last_paid_at ? new Date(detail.last_paid_at).toLocaleString() : '—'}</span>
            <span>Total paid</span>
            <span className="text-midnight-navy">{detail.total_paid_count}×</span>
          </div>

          <GlassButton variant="glass" className="self-start px-4 py-2 text-[13px]" onClick={() => setEditing(true)}>
            Edit label / amount
          </GlassButton>

          <div>
            <p className="mb-2 text-[13px] font-semibold text-dusk">Cycle history</p>
            {detail.history.length === 0 && <p className="text-[13px] text-smoke">No cycles logged yet.</p>}
            <div className="flex max-h-64 flex-col gap-1 overflow-y-auto">
              {detail.history.map((h, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between rounded-xl bg-white/45 px-3 py-2 text-[13px]"
                >
                  <span className="text-midnight-navy">{fmtDate(h.cycle_date)}</span>
                  <StatusPill value={h.status} />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {detail && editing && (
        <form className="flex flex-col gap-3" onSubmit={saveEdit}>
          <GlassField label="Label" value={label} onChange={(e) => setLabel(e.target.value)} />
          <GlassField label="Amount (BDT)" type="number" min="1" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} />
          <GlassField label="Remind days before" type="number" min="0" max="30" value={reminderDays} onChange={(e) => setReminderDays(e.target.value)} />
          <GlassField label="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
          <p className="text-[12px] text-smoke">Frequency and receiver can't be changed — cancel and recreate for that.</p>
          <div className="flex gap-2">
            <GlassButton variant="glass" type="button" className="flex-1" onClick={() => setEditing(false)}>
              Back
            </GlassButton>
            <GlassButton type="submit" className="flex-1" disabled={busy}>
              {busy ? 'Saving…' : 'Save changes'}
            </GlassButton>
          </div>
        </form>
      )}
    </GlassModal>
  )
}
