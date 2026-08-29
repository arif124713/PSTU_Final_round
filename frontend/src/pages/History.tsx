import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, apiErrorMessage } from '../lib/api'
import { Card, NavPill, TransactionAmount } from '../components/ui'

interface TxItem {
  reference_id: string
  amount: number
  counterparty_name: string
  direction: 'sent' | 'received'
  note: string | null
  status: string
  created_at: string
}

export function History() {
  const [transactions, setTransactions] = useState<TxItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .get('/transactions/history', { params: { per_page: 50 } })
      .then((res) => setTransactions(res.data.transactions))
      .catch((err) => setError(apiErrorMessage(err)))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="min-h-screen px-4 pb-16 pt-8">
      <NavPill>
        <span className="text-[16px] font-semibold text-midnight-navy">MoneyMove</span>
        <Link to="/dashboard" className="text-[16px] font-semibold text-midnight-navy">
          Dashboard
        </Link>
        <Link to="/send" className="text-[16px] font-semibold text-midnight-navy">
          Send
        </Link>
        <Link to="/history" className="text-[16px] font-semibold text-electric-blue">
          History
        </Link>
        <Link to="/agent" className="text-[16px] font-semibold text-midnight-navy">
          Assistant
        </Link>
      </NavPill>

      <div className="mx-auto mt-12 max-w-2xl">
        <Card>
          <h1 className="text-[32px] font-bold tracking-[-0.96px] text-midnight-navy">Transaction history</h1>
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
                  <p className="text-[14px] text-dusk">
                    {new Date(tx.created_at).toLocaleString()} · {tx.note || tx.status}
                  </p>
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
