import { useEffect, useState } from 'react'
import { api, apiErrorMessage } from '../lib/api'
import { PinPad } from '../components/PinPad'
import {
  EmptyState,
  GlassButton,
  GlassCard,
  GlassField,
  GlassModal,
  GlassNav,
  GlassTextarea,
  Money,
  PageShell,
  Segmented,
  StatusPill,
} from '../components/glass'

interface CreatorGroup {
  id: number
  reference_id: string
  title: string
  total_amount: number
  per_person_amount: number
  collected_amount: number
  status: string
  member_count: number
  members_paid: number
  members_pending: number
  members_debt: number
  expires_at: string
  created_at: string
}

interface MemberGroup {
  id: number
  reference_id: string
  title: string
  creator_name: string
  amount_owed: number
  my_status: string
  expires_at: string
}

interface MemberBrief {
  member_id: number
  full_name: string
  mobile_last4: string
  status: string
  amount_owed: number
}

interface GroupDetail {
  id: number
  reference_id: string
  title: string
  creator_name: string
  total_amount: number
  per_person_amount: number
  collected_amount: number
  member_count: number
  creator_included: boolean
  status: string
  note: string | null
  expires_at: string
  created_at: string
  members: MemberBrief[]
  is_creator: boolean
}

function fmtDateTime(d: string) {
  return new Date(d).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function ProgressBar({ value, total }: { value: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((value / total) * 100)) : 0
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-white/50">
      <div
        className="h-full rounded-full bg-gradient-to-r from-electric-blue to-cornflower-steel transition-all"
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

export function GroupPayments() {
  const [tab, setTab] = useState<'creator' | 'member'>('creator')
  const [asCreator, setAsCreator] = useState<CreatorGroup[]>([])
  const [asMember, setAsMember] = useState<MemberGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [detailId, setDetailId] = useState<number | null>(null)
  const [agreeTarget, setAgreeTarget] = useState<MemberGroup | null>(null)
  const [agreeErr, setAgreeErr] = useState<string | null>(null)
  const [agreeing, setAgreeing] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  function flash(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(null), 3200)
  }

  async function load() {
    setLoading(true)
    try {
      const { data } = await api.get('/group-payments')
      setAsCreator(data.as_creator)
      setAsMember(data.as_member)
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

  async function respondDecline(g: MemberGroup) {
    try {
      await api.post(`/group-payments/${g.id}/respond`, { action: 'decline' })
      flash('Declined')
      load()
    } catch (err) {
      flash(apiErrorMessage(err))
    }
  }

  async function handleAgree(pin: string) {
    if (!agreeTarget) return
    setAgreeing(true)
    setAgreeErr(null)
    try {
      const { data } = await api.post(`/group-payments/${agreeTarget.id}/respond`, { action: 'agree', pin })
      setAgreeTarget(null)
      flash(data.detail ?? 'Agreed')
      load()
    } catch (err) {
      setAgreeErr(apiErrorMessage(err))
    } finally {
      setAgreeing(false)
    }
  }

  return (
    <PageShell>
      <GlassNav active="Groups" />

      <div className="mx-auto mt-10 flex max-w-3xl flex-col gap-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[34px] font-bold tracking-[-1px] text-midnight-navy">Group payments</h1>
            <p className="mt-1 text-[15px] text-dusk">Split a bill equally and collect everyone's share.</p>
          </div>
          <GlassButton onClick={() => setShowCreate(true)}>+ New split</GlassButton>
        </div>

        <Segmented
          value={tab}
          onChange={setTab}
          options={[
            { value: 'creator', label: `Created by me (${asCreator.length})` },
            { value: 'member', label: `I'm a member (${asMember.length})` },
          ]}
        />

        {loading && <p className="text-[15px] text-dusk">Loading…</p>}
        {error && <p className="text-[14px] text-rose-600">{error}</p>}

        {tab === 'creator' && !loading && (
          <div className="flex flex-col gap-4">
            {asCreator.length === 0 && <EmptyState>You haven't created any group payments.</EmptyState>}
            {asCreator.map((g) => (
              <GlassCard key={g.id} interactive className="flex flex-col gap-3 p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[17px] font-semibold text-midnight-navy">{g.title}</p>
                    <p className="text-[13px] text-dusk">
                      {g.member_count} members · ৳{g.per_person_amount.toLocaleString()} each
                    </p>
                  </div>
                  <StatusPill value={g.status} />
                </div>

                <div className="flex items-center gap-3">
                  <Money value={g.collected_amount} className="text-[15px] font-semibold text-midnight-navy" />
                  <ProgressBar value={g.collected_amount} total={g.total_amount} />
                  <Money value={g.total_amount} className="text-[13px] text-dusk" />
                </div>

                <div className="flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-dusk">
                  <span className="text-emerald-600">{g.members_paid} paid</span>
                  <span className="text-amber-600">{g.members_debt} on debt</span>
                  <span>{g.members_pending} pending</span>
                  <span>Expires {fmtDateTime(g.expires_at)}</span>
                </div>

                <div className="mt-1 flex flex-wrap gap-2">
                  <GlassButton variant="glass" className="px-4 py-2 text-[13px]" onClick={() => setDetailId(g.id)}>
                    Manage
                  </GlassButton>
                </div>
              </GlassCard>
            ))}
          </div>
        )}

        {tab === 'member' && !loading && (
          <div className="flex flex-col gap-4">
            {asMember.length === 0 && <EmptyState>No group payment invites right now.</EmptyState>}
            {asMember.map((g) => (
              <GlassCard key={g.id} interactive className="flex flex-col gap-3 p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[17px] font-semibold text-midnight-navy">{g.title}</p>
                    <p className="text-[13px] text-dusk">from {g.creator_name}</p>
                  </div>
                  <StatusPill value={g.my_status} />
                </div>

                <Money value={g.amount_owed} className="text-[24px] font-bold tracking-[-0.8px] text-midnight-navy" />
                <p className="text-[13px] text-dusk">Expires {fmtDateTime(g.expires_at)}</p>

                <div className="mt-1 flex flex-wrap gap-2">
                  {g.my_status === 'pending' && (
                    <>
                      <GlassButton
                        className="px-4 py-2 text-[13px]"
                        onClick={() => { setAgreeErr(null); setAgreeTarget(g) }}
                      >
                        Agree &amp; pay
                      </GlassButton>
                      <GlassButton variant="ghost" className="px-4 py-2 text-[13px]" onClick={() => respondDecline(g)}>
                        Decline
                      </GlassButton>
                    </>
                  )}
                  <GlassButton variant="glass" className="px-4 py-2 text-[13px]" onClick={() => setDetailId(g.id)}>
                    Details
                  </GlassButton>
                </div>
              </GlassCard>
            ))}
          </div>
        )}
      </div>

      {toast && (
        <div className="glass-panel fixed bottom-6 left-1/2 z-40 -translate-x-1/2 rounded-full px-5 py-2.5 text-center text-[14px] font-semibold text-midnight-navy">
          {toast}
        </div>
      )}

      {showCreate && (
        <CreateGroupModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false)
            flash('Group payment created')
            load()
          }}
        />
      )}

      {detailId !== null && (
        <GroupDetailModal
          id={detailId}
          onClose={() => setDetailId(null)}
          onChanged={() => {
            load()
          }}
          flash={flash}
        />
      )}

      {agreeTarget && (
        <PinPad
          title="Agree to group payment"
          subtitle={`Your PIN authorises ৳${agreeTarget.amount_owed.toLocaleString()} for "${agreeTarget.title}" — paid now, or auto-deducted later if your balance is short.`}
          onSubmit={handleAgree}
          onCancel={() => setAgreeTarget(null)}
          submitting={agreeing}
          error={agreeErr}
        />
      )}
    </PageShell>
  )
}

/* ── Create ───────────────────────────────────────────────────────────── */
function CreateGroupModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [title, setTitle] = useState('')
  const [total, setTotal] = useState('')
  const [members, setMembers] = useState('')
  const [creatorIncluded, setCreatorIncluded] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [idempotencyKey] = useState(() => crypto.randomUUID())

  const parsedMembers = members
    .split(/[\n,]+/)
    .map((m) => m.trim())
    .filter(Boolean)

  const perPerson =
    Number(total) > 0 && parsedMembers.length > 0
      ? Number(total) / (creatorIncluded ? parsedMembers.length + 1 : parsedMembers.length)
      : 0

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post('/group-payments/create', {
        title: title.trim(),
        total_amount: Number(total),
        members: parsedMembers,
        creator_included: creatorIncluded,
        note: note.trim() || undefined,
        idempotency_key: idempotencyKey,
      })
      onCreated()
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <GlassModal title="New group payment" onClose={onClose} wide>
      <form className="flex flex-col gap-3" onSubmit={submit}>
        <GlassField label="Title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Dinner at Radisson" required />
        <GlassField
          label="Total bill (BDT)"
          type="number"
          min="1"
          step="0.01"
          value={total}
          onChange={(e) => setTotal(e.target.value)}
          required
        />
        <GlassTextarea
          label="Members — one mobile number or user ID per line"
          value={members}
          onChange={(e) => setMembers(e.target.value)}
          placeholder={'+8801XXXXXXXXX\n+8801YYYYYYYYY'}
        />
        <label className="flex items-center gap-2 text-[13px] text-dusk">
          <input
            type="checkbox"
            checked={creatorIncluded}
            onChange={(e) => setCreatorIncluded(e.target.checked)}
            className="h-4 w-4 rounded border-silver-lining"
          />
          Include my own share in the split
        </label>
        <GlassTextarea label="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />

        {perPerson > 0 && (
          <p className="text-[13px] text-dusk">
            {parsedMembers.length} member(s) · <span className="font-semibold text-midnight-navy">৳{perPerson.toLocaleString('en-BD', { maximumFractionDigits: 2 })}</span> each
          </p>
        )}
        {error && <p className="text-[13px] text-rose-600">{error}</p>}

        <div className="mt-1 flex gap-2">
          <GlassButton variant="glass" type="button" className="flex-1" onClick={onClose}>
            Cancel
          </GlassButton>
          <GlassButton type="submit" className="flex-1" disabled={busy || parsedMembers.length === 0}>
            {busy ? 'Creating…' : 'Send invites'}
          </GlassButton>
        </div>
      </form>
    </GlassModal>
  )
}

/* ── Detail / manage ──────────────────────────────────────────────────── */
function GroupDetailModal({
  id,
  onClose,
  onChanged,
  flash,
}: {
  id: number
  onClose: () => void
  onChanged: () => void
  flash: (m: string) => void
}) {
  const [detail, setDetail] = useState<GroupDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  async function load() {
    try {
      const { data } = await api.get(`/group-payments/${id}`)
      setDetail(data)
    } catch (err) {
      setError(apiErrorMessage(err))
    }
  }

  useEffect(() => {
    load()
  }, [id])

  async function remind(memberId: number) {
    setBusy(`remind-${memberId}`)
    try {
      await api.post(`/group-payments/${id}/members/${memberId}/remind`)
      flash('Reminder sent')
    } catch (err) {
      flash(apiErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  async function cancelDebt(memberId: number) {
    const reason = window.prompt('Why are you clearing this debt? (e.g. paid me in cash)')
    if (!reason) return
    setBusy(`debt-${memberId}`)
    try {
      await api.post(`/group-payments/${id}/members/${memberId}/cancel-debt`, { reason })
      flash('Debt cleared')
      await load()
      onChanged()
    } catch (err) {
      flash(apiErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  async function cancelGroup() {
    if (!window.confirm('Cancel this group payment and refund everyone who already paid?')) return
    setBusy('cancel')
    try {
      const { data } = await api.post(`/group-payments/${id}/cancel`, {})
      flash(`Cancelled · ${data.refunded_count} refund(s)`)
      await load()
      onChanged()
    } catch (err) {
      flash(apiErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <GlassModal title={detail?.title ?? 'Group payment'} onClose={onClose} wide>
      {error && <p className="text-[13px] text-rose-600">{error}</p>}
      {!detail && !error && <p className="text-[14px] text-dusk">Loading…</p>}

      {detail && (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <StatusPill value={detail.status} />
            <span className="text-[13px] text-dusk">by {detail.creator_name}</span>
          </div>

          <div className="flex items-center gap-3">
            <Money value={detail.collected_amount} className="text-[15px] font-semibold text-midnight-navy" />
            <ProgressBar value={detail.collected_amount} total={detail.total_amount} />
            <Money value={detail.total_amount} className="text-[13px] text-dusk" />
          </div>
          {detail.note && <p className="text-[13px] text-dusk">“{detail.note}”</p>}

          <div className="flex flex-col gap-1.5">
            <p className="text-[13px] font-semibold text-dusk">Members</p>
            {detail.members.map((m) => (
              <div
                key={m.member_id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-white/45 px-3 py-2"
              >
                <div>
                  <p className="text-[14px] font-medium text-midnight-navy">
                    {m.full_name} <span className="text-dusk">· ****{m.mobile_last4}</span>
                  </p>
                  <p className="text-[12px] text-dusk">৳{m.amount_owed.toLocaleString()}</p>
                </div>
                <div className="flex items-center gap-2">
                  <StatusPill value={m.status} />
                  {detail.is_creator && m.status === 'agreed_debt' && (
                    <>
                      <GlassButton
                        variant="glass"
                        className="px-3 py-1.5 text-[12px]"
                        disabled={busy === `remind-${m.member_id}`}
                        onClick={() => remind(m.member_id)}
                      >
                        Remind
                      </GlassButton>
                      <GlassButton
                        variant="ghost"
                        className="px-3 py-1.5 text-[12px]"
                        disabled={busy === `debt-${m.member_id}`}
                        onClick={() => cancelDebt(m.member_id)}
                      >
                        Clear debt
                      </GlassButton>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>

          {detail.is_creator && detail.status === 'open' && (
            <GlassButton
              variant="danger"
              className="self-start px-4 py-2 text-[13px]"
              disabled={busy === 'cancel'}
              onClick={cancelGroup}
            >
              Cancel group &amp; refund
            </GlassButton>
          )}
        </div>
      )}
    </GlassModal>
  )
}
