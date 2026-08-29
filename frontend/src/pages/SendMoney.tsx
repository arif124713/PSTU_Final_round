import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, apiErrorMessage } from '../lib/api'
import { useAuthStore } from '../store/authStore'
import { Button, Card, Input } from '../components/ui'
import { PinPad } from '../components/PinPad'

type Stage = 'form' | 'confirm' | 'pin' | 'success'

interface Receiver {
  id: number
  full_name: string
  mobile_last4: string
}

const UNUSUAL_AMOUNT_THRESHOLD = 10000

export function SendMoney() {
  const navigate = useNavigate()
  const updateBalance = useAuthStore((s) => s.updateBalance)

  const [stage, setStage] = useState<Stage>('form')
  const [receiverIdentifier, setReceiverIdentifier] = useState('')
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [receiver, setReceiver] = useState<Receiver | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [idempotencyKey] = useState(() => crypto.randomUUID())
  const [result, setResult] = useState<{ reference_id: string; new_balance: number } | null>(null)

  async function handleValidate(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const { data } = await api.post('/transactions/validate-receiver', {
        receiver_identifier: receiverIdentifier,
      })
      setReceiver(data.receiver)
      setStage('confirm')
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function handlePinSubmit(pin: string) {
    setError(null)
    setLoading(true)
    try {
      const amountNum = Number(amount)
      const { data } = await api.post('/transactions/send', {
        idempotency_key: idempotencyKey,
        receiver_identifier: receiverIdentifier,
        amount: amountNum,
        pin,
        note: note || undefined,
        extra_confirmed: amountNum > UNUSUAL_AMOUNT_THRESHOLD,
      })
      updateBalance(data.new_balance)
      setResult({ reference_id: data.reference_id, new_balance: data.new_balance })
      setStage('success')
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  if (stage === 'success' && result) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <Card className="w-full max-w-sm text-center">
          <h1 className="text-[32px] font-bold tracking-[-0.96px] text-midnight-navy">Sent!</h1>
          <p className="mt-2 text-[18px] text-dusk">
            ৳{Number(amount).toLocaleString('en-BD', { minimumFractionDigits: 2 })} sent to {receiver?.full_name}
          </p>
          <p className="mt-1 text-[14px] text-smoke">Ref: {result.reference_id}</p>
          <Button className="mt-6 w-full" onClick={() => navigate('/dashboard')}>
            Back to dashboard
          </Button>
        </Card>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <h1 className="text-[32px] font-bold tracking-[-0.96px] text-midnight-navy">Send money</h1>

        {stage === 'form' && (
          <form className="mt-6 flex flex-col gap-4" onSubmit={handleValidate}>
            <Input
              label="Receiver mobile number or user ID"
              value={receiverIdentifier}
              onChange={(e) => setReceiverIdentifier(e.target.value)}
              placeholder="+8801XXXXXXXXX"
            />
            <Input
              label="Amount (BDT)"
              type="number"
              min="1"
              step="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
            <Input label="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
            {error && <p className="text-[14px] text-red-500">{error}</p>}
            <Button type="submit" disabled={loading || !amount}>
              {loading ? 'Checking…' : 'Continue'}
            </Button>
          </form>
        )}

        {stage === 'confirm' && receiver && (
          <div className="mt-6 flex flex-col gap-4">
            <p className="text-[18px] text-dusk">
              Sending <span className="font-semibold text-midnight-navy">৳{Number(amount).toLocaleString()}</span> to{' '}
              <span className="font-semibold text-midnight-navy">{receiver.full_name}</span> · ****{receiver.mobile_last4}
            </p>
            {Number(amount) > UNUSUAL_AMOUNT_THRESHOLD && (
              <p className="text-[14px] text-cornflower-steel">
                This is a large transfer — you'll confirm it once more with your PIN.
              </p>
            )}
            {error && <p className="text-[14px] text-red-500">{error}</p>}
            <div className="flex gap-3">
              <Button variant="outlined" className="flex-1" onClick={() => setStage('form')}>
                Back
              </Button>
              <Button className="flex-1" onClick={() => setStage('pin')}>
                Continue
              </Button>
            </div>
          </div>
        )}
      </Card>

      {stage === 'pin' && receiver && (
        <PinPad
          title="Enter your PIN"
          subtitle={`Confirm sending ৳${Number(amount).toLocaleString()} to ${receiver.full_name}`}
          onSubmit={handlePinSubmit}
          onCancel={() => setStage('confirm')}
          submitting={loading}
          error={error}
        />
      )}
    </div>
  )
}
