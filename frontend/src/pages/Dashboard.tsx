import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, apiErrorMessage } from '../lib/api'
import { useAuthStore } from '../store/authStore'
import { TransactionAmount } from '../components/ui'
import { GlassButton, GlassCard, GlassNav, Money, PageShell } from '../components/glass'

interface TxItem {
  reference_id: string
  amount: number
  counterparty_name: string
  direction: 'sent' | 'received'
  note: string | null
  status: string
  created_at: string
}

const QUICK_LINKS: { to: string; title: string; desc: string }[] = [
  { to: '/send', title: 'Send money', desc: 'Transfer with PIN confirmation' },
  { to: '/scheduled', title: 'Scheduled', desc: 'Recurring payment reminders' },
  { to: '/groups', title: 'Group split', desc: 'Split a bill with friends' },
  { to: '/debts', title: 'Debts', desc: 'Auto-settling shares' },
]

export function Dashboard() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const updateBalance = useAuthStore((s) => s.updateBalance)
  const [transactions, setTransactions] = useState<TxItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const [meRes, historyRes] = await Promise.all([
          api.get('/users/me'),
          api.get('/transactions/history', { params: { per_page: 5 } }),
        ])
        updateBalance(meRes.data.balance)
        setTransactions(historyRes.data.transactions)
      } catch (err) {
        setError(apiErrorMessage(err))
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [updateBalance])

  return (
    <PageShell>
      <GlassNav active="Dashboard" />

      <div className="mx-auto mt-10 flex max-w-3xl flex-col gap-6">
        <GlassCard interactive className="p-7">
          <p className="text-[13px] uppercase tracking-[0.4px] text-smoke">Balance</p>
          <Money
            value={user?.balance ?? 0}
            className="mt-2 block text-[60px] font-bold leading-[0.9] tracking-[-2.4px] text-midnight-navy"
          />
          <p className="mt-2 text-[17px] text-dusk">Welcome back, {user?.full_name}</p>
          <div className="mt-6 flex flex-wrap gap-3">
            <GlassButton onClick={() => navigate('/send')}>Send money</GlassButton>
            <GlassButton variant="glass" onClick={() => navigate('/history')}>
              View history
            </GlassButton>
          </div>
        </GlassCard>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {QUICK_LINKS.map((q) => (
            <Link key={q.to} to={q.to}>
              <GlassCard interactive className="h-full p-5">
                <p className="text-[16px] font-semibold text-midnight-navy">{q.title}</p>
                <p className="mt-1 text-[13px] text-dusk">{q.desc}</p>
              </GlassCard>
            </Link>
          ))}
        </div>

        <GlassCard className="p-6">
          <h2 className="text-[22px] font-semibold tracking-[-0.6px] text-midnight-navy">Recent activity</h2>
          {loading && <p className="mt-4 text-[15px] text-dusk">Loading…</p>}
          {error && <p className="mt-4 text-[14px] text-rose-600">{error}</p>}
          {!loading && transactions.length === 0 && (
            <p className="mt-4 text-[15px] text-dusk">No transactions yet.</p>
          )}
          <div className="mt-4 flex flex-col divide-y divide-white/50">
            {transactions.map((tx) => (
              <div key={tx.reference_id} className="flex items-center justify-between py-3">
                <div>
                  <p className="text-[15px] font-medium text-midnight-navy">{tx.counterparty_name}</p>
                  <p className="text-[13px] text-dusk">{tx.note || tx.status}</p>
                </div>
                <TransactionAmount amount={tx.amount} direction={tx.direction} />
              </div>
            ))}
          </div>
        </GlassCard>
      </div>
    </PageShell>
  )
}
