import { useEffect, useState } from 'react'
import { api, apiErrorMessage } from '../lib/api'
import {
  EmptyState,
  GlassCard,
  GlassModal,
  GlassNav,
  Money,
  PageShell,
  Segmented,
  StatusPill,
} from '../components/glass'

interface Debt {
  debt_id: number
  reference_id: string
  group_title: string
  creditor_name?: string
  debtor_name?: string
  original_amount: number
  remaining_amount: number
  status: string
  created_at: string
  last_payment?: { amount: number; paid_at: string } | null
}

interface Installment {
  amount: number
  remaining_after: number
  payment_type: string
  transaction_id: number
  created_at: string
}

interface DebtHistory {
  debt_id: number
  reference_id: string
  original_amount: number
  remaining_amount: number
  status: string
  installments: Installment[]
}

function fmt(d: string) {
  return new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}

function Bar({ paid, total }: { paid: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((paid / total) * 100)) : 0
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-white/50">
      <div
        className="h-full rounded-full bg-gradient-to-r from-emerald-400 to-emerald-600 transition-all"
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

export function Debts() {
  const [tab, setTab] = useState<'owe' | 'owed'>('owe')
  const [myDebts, setMyDebts] = useState<Debt[]>([])
  const [owedToMe, setOwedToMe] = useState<Debt[]>([])
  const [totalOut, setTotalOut] = useState(0)
  const [totalIn, setTotalIn] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [historyId, setHistoryId] = useState<number | null>(null)

  async function load() {
    setLoading(true)
    try {
      const [mine, incoming] = await Promise.all([
        api.get('/debts/my-debts'),
        api.get('/debts/owed-to-me'),
      ])
      setMyDebts(mine.data.debts)
      setTotalOut(mine.data.total_outstanding)
      setOwedToMe(incoming.data.debts)
      setTotalIn(incoming.data.total_incoming)
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

  const list = tab === 'owe' ? myDebts : owedToMe

  return (
    <PageShell>
      <GlassNav active="Debts" />

      <div className="mx-auto mt-10 flex max-w-3xl flex-col gap-5">
        <div>
          <h1 className="text-[34px] font-bold tracking-[-1px] text-midnight-navy">Debts</h1>
          <p className="mt-1 text-[15px] text-dusk">
            Group-payment shares settle automatically the next time the debtor receives money.
          </p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <GlassCard interactive className="p-5">
            <p className="text-[13px] uppercase tracking-[0.4px] text-smoke">You owe</p>
            <Money value={totalOut} className="mt-1 block text-[30px] font-bold tracking-[-1px] text-midnight-navy" />
          </GlassCard>
          <GlassCard interactive className="p-5">
            <p className="text-[13px] uppercase tracking-[0.4px] text-smoke">Owed to you</p>
            <Money value={totalIn} className="mt-1 block text-[30px] font-bold tracking-[-1px] text-electric-blue" />
          </GlassCard>
        </div>

        <Segmented
          value={tab}
          onChange={setTab}
          options={[
            { value: 'owe', label: `I owe (${myDebts.length})` },
            { value: 'owed', label: `Owed to me (${owedToMe.length})` },
          ]}
        />

        {loading && <p className="text-[15px] text-dusk">Loading…</p>}
        {error && <p className="text-[14px] text-rose-600">{error}</p>}
        {!loading && list.length === 0 && (
          <EmptyState>{tab === 'owe' ? 'You have no outstanding debts.' : 'Nobody owes you right now.'}</EmptyState>
        )}

        <div className="flex flex-col gap-4">
          {list.map((d) => {
            const paid = d.original_amount - d.remaining_amount
            return (
              <GlassCard key={d.debt_id} interactive className="flex flex-col gap-3 p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[17px] font-semibold text-midnight-navy">{d.group_title}</p>
                    <p className="text-[13px] text-dusk">
                      {tab === 'owe' ? `to ${d.creditor_name}` : `from ${d.debtor_name}`} · started {fmt(d.created_at)}
                    </p>
                  </div>
                  <StatusPill value={d.status} />
                </div>

                <div className="flex items-center gap-3">
                  <Money value={paid} className="text-[14px] font-semibold text-emerald-600" />
                  <Bar paid={paid} total={d.original_amount} />
                  <Money value={d.original_amount} className="text-[13px] text-dusk" />
                </div>

                <div className="flex flex-wrap items-center justify-between gap-2 text-[13px] text-dusk">
                  <span>
                    Remaining <Money value={d.remaining_amount} className="font-semibold text-midnight-navy" />
                  </span>
                  {d.last_payment && (
                    <span>
                      Last auto-deduction ৳{d.last_payment.amount.toLocaleString()} on {fmt(d.last_payment.paid_at)}
                    </span>
                  )}
                  <button
                    className="rounded-full bg-white/55 px-3 py-1 font-semibold text-cornflower-steel transition-colors hover:bg-white/80"
                    onClick={() => setHistoryId(d.debt_id)}
                  >
                    Installments
                  </button>
                </div>
              </GlassCard>
            )
          })}
        </div>
      </div>

      {historyId !== null && <HistoryModal debtId={historyId} onClose={() => setHistoryId(null)} />}
    </PageShell>
  )
}

function HistoryModal({ debtId, onClose }: { debtId: number; onClose: () => void }) {
  const [data, setData] = useState<DebtHistory | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .get(`/debts/${debtId}/history`)
      .then((res) => setData(res.data))
      .catch((err) => setError(apiErrorMessage(err)))
  }, [debtId])

  return (
    <GlassModal title="Debt installments" onClose={onClose}>
      {error && <p className="text-[13px] text-rose-600">{error}</p>}
      {!data && !error && <p className="text-[14px] text-dusk">Loading…</p>}
      {data && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-3">
            <Money value={data.original_amount - data.remaining_amount} className="text-[15px] font-semibold text-emerald-600" />
            <Bar paid={data.original_amount - data.remaining_amount} total={data.original_amount} />
            <Money value={data.original_amount} className="text-[13px] text-dusk" />
          </div>
          <StatusPill value={data.status} />
          {data.installments.length === 0 && <p className="text-[13px] text-smoke">No installments paid yet.</p>}
          <div className="flex flex-col gap-1">
            {data.installments.map((it, i) => (
              <div key={i} className="flex items-center justify-between rounded-xl bg-white/45 px-3 py-2 text-[13px]">
                <span className="text-midnight-navy">{new Date(it.created_at).toLocaleString()}</span>
                <span className="font-semibold text-midnight-navy">
                  ৳{it.amount.toLocaleString()} <span className="font-normal text-dusk">· left ৳{it.remaining_after.toLocaleString()}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </GlassModal>
  )
}
