import { useEffect, useRef, useState } from 'react'
import { api, apiErrorMessage } from '../lib/api'
import { useAuthStore } from '../store/authStore'
import { Card, Input } from '../components/ui'
import { GlassNav, PageShell } from '../components/glass'
import { PinPad } from '../components/PinPad'

interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

interface PendingPin {
  draft_id: string
  summary: { receiver_name: string; amount: number }
}

export function AgentChat() {
  const updateBalance = useAuthStore((s) => s.updateBalance)
  const [sessionId] = useState(() => crypto.randomUUID())
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'assistant', content: "Hi! I'm your MoneyMove assistant. I can check your balance, send money, show your history, or summarize your spending. What would you like to do?" },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pendingPin, setPendingPin] = useState<PendingPin | null>(null)
  const [confirming, setConfirming] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, pendingPin])

  async function sendMessage(e: React.FormEvent) {
    e.preventDefault()
    if (!input.trim()) return
    const userMessage = input.trim()
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: userMessage }])
    setLoading(true)
    setError(null)
    try {
      const { data } = await api.post('/agent/chat', { message: userMessage, session_id: sessionId })
      setMessages((prev) => [...prev, { role: 'assistant', content: data.message }])
      if (data.action === 'pending_pin') {
        setPendingPin({ draft_id: data.draft_id, summary: data.summary })
      }
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function handlePinSubmit(pin: string) {
    if (!pendingPin) return
    setConfirming(true)
    setError(null)
    try {
      const { data } = await api.post('/transactions/confirm', { draft_id: pendingPin.draft_id, pin })
      updateBalance(data.new_balance)
      setMessages((prev) => [
        ...prev,
        {
          role: 'system',
          content: `Sent ৳${pendingPin.summary.amount.toLocaleString()} to ${pendingPin.summary.receiver_name}. New balance: ৳${data.new_balance.toLocaleString()}.`,
        },
      ])
      setPendingPin(null)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setConfirming(false)
    }
  }

  return (
    <PageShell>
      <GlassNav active="Assistant" />

      <div className="mx-auto mt-10 max-w-2xl">
        <Card className="flex h-[70vh] flex-col">
          <h1 className="text-[24px] font-semibold tracking-[-0.72px] text-midnight-navy">AI Assistant</h1>
          <p className="text-[14px] text-smoke">Ask me to send money, check your balance, or review your history.</p>

          <div className="mt-4 flex-1 overflow-y-auto rounded-xl bg-fog-white p-4">
            <div className="flex flex-col gap-3">
              {messages.map((m, i) => (
                <div
                  key={i}
                  className={`max-w-[80%] whitespace-pre-wrap rounded-xl px-4 py-3 text-[16px] ${
                    m.role === 'user'
                      ? 'ml-auto bg-midnight-navy text-white'
                      : m.role === 'system'
                        ? 'mx-auto bg-mist-gray text-midnight-navy text-center text-[14px]'
                        : 'bg-white text-midnight-navy shadow-[rgba(32,41,76,0.1)_0px_1px_4px_0px]'
                  }`}
                >
                  {m.content}
                </div>
              ))}
              {loading && <div className="bg-white text-dusk shadow-[rgba(32,41,76,0.1)_0px_1px_4px_0px] rounded-xl px-4 py-3 text-[16px]">Thinking…</div>}
              <div ref={bottomRef} />
            </div>
          </div>

          {error && <p className="mt-2 text-[14px] text-red-500">{error}</p>}

          <form className="mt-4 flex gap-2" onSubmit={sendMessage}>
            <Input
              className="flex-1"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="e.g. Send 2000 to Ankon"
              disabled={loading}
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="rounded-full bg-midnight-navy px-4 py-3 text-[16px] font-semibold text-white shadow-[rgba(32,41,76,0.1)_0px_1px_4px_0px] disabled:opacity-50"
            >
              Send
            </button>
          </form>
        </Card>
      </div>

      {pendingPin && (
        <PinPad
          title="Enter your PIN"
          subtitle={`Confirm sending ৳${pendingPin.summary.amount.toLocaleString()} to ${pendingPin.summary.receiver_name}`}
          onSubmit={handlePinSubmit}
          onCancel={() => setPendingPin(null)}
          submitting={confirming}
          error={error}
        />
      )}
    </PageShell>
  )
}
