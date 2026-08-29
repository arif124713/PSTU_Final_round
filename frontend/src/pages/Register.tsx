import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { api, apiErrorMessage } from '../lib/api'
import { useAuthStore } from '../store/authStore'
import { Button, Card, Input } from '../components/ui'

type Step = 'mobile' | 'otp' | 'details'

export function Register() {
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)
  const [step, setStep] = useState<Step>('mobile')
  const [mobileNumber, setMobileNumber] = useState('+8801')
  const [otp, setOtp] = useState('')
  const [tempToken, setTempToken] = useState('')
  const [fullName, setFullName] = useState('')
  const [nidNumber, setNidNumber] = useState('')
  const [password, setPassword] = useState('')
  const [pin, setPin] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function sendOtp(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await api.post('/auth/send-otp', { mobile_number: mobileNumber })
      setStep('otp')
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function verifyOtp(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const { data } = await api.post('/auth/verify-otp', { mobile_number: mobileNumber, otp_code: otp })
      setTempToken(data.temp_token)
      setStep('details')
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function completeRegistration(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const { data } = await api.post(
        '/auth/register',
        { full_name: fullName, nid_number: nidNumber, password, transaction_pin: pin },
        { headers: { Authorization: `Bearer ${tempToken}` } }
      )
      login(data.access_token, { id: data.user_id, full_name: fullName, balance: data.balance, role: 'user' })
      navigate('/dashboard')
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <h1 className="text-[32px] font-bold tracking-[-0.96px] text-midnight-navy">Create account</h1>
        <p className="mt-1 text-[16px] text-dusk">
          {step === 'mobile' && 'Enter your mobile number to get started'}
          {step === 'otp' && 'Enter the OTP we sent you (demo: 1234)'}
          {step === 'details' && 'A few more details'}
        </p>

        {step === 'mobile' && (
          <form className="mt-6 flex flex-col gap-4" onSubmit={sendOtp}>
            <Input
              label="Mobile number"
              value={mobileNumber}
              onChange={(e) => setMobileNumber(e.target.value)}
              placeholder="+8801XXXXXXXXX"
            />
            {error && <p className="text-[14px] text-red-500">{error}</p>}
            <Button type="submit" disabled={loading}>
              {loading ? 'Sending…' : 'Send OTP'}
            </Button>
          </form>
        )}

        {step === 'otp' && (
          <form className="mt-6 flex flex-col gap-4" onSubmit={verifyOtp}>
            <Input label="OTP code" value={otp} onChange={(e) => setOtp(e.target.value)} maxLength={4} />
            {error && <p className="text-[14px] text-red-500">{error}</p>}
            <Button type="submit" disabled={loading}>
              {loading ? 'Verifying…' : 'Verify'}
            </Button>
          </form>
        )}

        {step === 'details' && (
          <form className="mt-6 flex flex-col gap-4" onSubmit={completeRegistration}>
            <Input label="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
            <Input
              label="NID number (17 digits)"
              value={nidNumber}
              onChange={(e) => setNidNumber(e.target.value)}
              maxLength={17}
            />
            <Input
              label="Password (min 8 chars)"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <Input
              label="Transaction PIN (6 digits)"
              type="password"
              value={pin}
              onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 6))}
              maxLength={6}
            />
            {error && <p className="text-[14px] text-red-500">{error}</p>}
            <Button type="submit" disabled={loading}>
              {loading ? 'Creating account…' : 'Create account'}
            </Button>
          </form>
        )}

        <p className="mt-4 text-center text-[14px] text-dusk">
          Already have an account?{' '}
          <Link to="/login" className="text-electric-blue">
            Log in
          </Link>
        </p>
      </Card>
    </div>
  )
}
