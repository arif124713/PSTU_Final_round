import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, apiErrorMessage } from '../lib/api'
import { useAuthStore } from '../store/authStore'
import { Button, Card, NavPill, TransactionAmount } from '../components/ui'

interface TxItem {
  reference_id: string
  amount: number
  counterparty_name: string
  direction: 'sent' | 'received'
  note: string | null
  status: string
  created_at: string
}

export function Dashboard() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const updateBalance = useAuthStore((s) => s.updateBalance)
  const logout = useAuthStore((s) => s.logout)
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <div className="min-h-screen px-4 pb-16 pt-8">
      <NavPill>
        <span className="text-[16px] font-semibold text-midnight-navy">MoneyMove</span>
        <Link to="/dashboard" className="text-[16px] font-semibold text-electric-blue">
          Dashboard
        </Link>
        <Link to="/send" className="text-[16px] font-semibold text-midnight-navy">
          Send
        </Link>
        <Link to="/history" className="text-[16px] font-semibold text-midnight-navy">
          History
        </Link>
        <Link to="/agent" className="text-[16px] font-semibold text-midnight-navy">
          Assistant
        </Link>
        <button onClick={handleLogout} className="text-[16px] font-semibold text-cornflower-steel">
          Log out
        </button>
      </NavPill>

      <div className="mx-auto mt-12 flex max-w-2xl flex-col gap-6">
        <Card>
          <p className="text-[14px] uppercase tracking-[0.4px] text-smoke">Balance</p>
          <p className="mt-2 text-[64px] font-bold leading-[0.85] tracking-[-2.56px] text-midnight-navy">
            ৳{(user?.balance ?? 0).toLocaleString('en-BD', { minimumFractionDigits: 2 })}
          </p>
          <p className="mt-2 text-[18px] text-dusk">Welcome back, {user?.full_name}</p>
          <div className="mt-6 flex gap-3">
            <Button onClick={() => navigate('/send')}>Send money</Button>
            <Button variant="outlined" onClick={() => navigate('/history')}>
              View history
            </Button>
          </div>
        </Card>

        <Card>
          <h2 className="text-[24px] font-semibold tracking-[-0.72px] text-midnight-navy">Recent activity</h2>
          {loading && <p className="mt-4 text-[16px] text-dusk">Loading…</p>}
          {error && <p className="mt-4 text-[14px] text-red-500">{error}</p>}
          {!loading && transactions.length === 0 && (
            <p className="mt-4 text-[16px] text-dusk">No transactions yet.</p>
          )}
          <div className="mt-4 flex flex-col divide-y divide-silver-lining">
            {transactions.map((tx) => (
              <div key={tx.reference_id} className="flex items-center justify-between py-3">
                <div>
                  <p className="text-[16px] font-medium text-midnight-navy">{tx.counterparty_name}</p>
                  <p className="text-[14px] text-dusk">{tx.note || tx.status}</p>
                </div>
                <TransactionAmount amount={tx.amount} direction={tx.direction} />
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
