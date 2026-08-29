import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { api, apiErrorMessage } from '../lib/api'
import { useAuthStore } from '../store/authStore'
import { Button, Card, Input } from '../components/ui'

export function Login() {
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)
  const [mobileNumber, setMobileNumber] = useState('+8801')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const { data } = await api.post('/auth/login', { mobile_number: mobileNumber, password })
      login(data.access_token, data.user)
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
        <h1 className="text-[32px] font-bold tracking-[-0.96px] text-midnight-navy">Welcome back</h1>
        <p className="mt-1 text-[16px] text-dusk">Log in to MoneyMove</p>

        <form className="mt-6 flex flex-col gap-4" onSubmit={handleSubmit}>
          <Input
            label="Mobile number"
            value={mobileNumber}
            onChange={(e) => setMobileNumber(e.target.value)}
            placeholder="+8801XXXXXXXXX"
          />
          <Input
            label="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && <p className="text-[14px] text-red-500">{error}</p>}
          <Button type="submit" disabled={loading}>
            {loading ? 'Logging in…' : 'Log in'}
          </Button>
        </form>

        <p className="mt-4 text-center text-[14px] text-dusk">
          New here?{' '}
          <Link to="/register" className="text-electric-blue">
            Create an account
          </Link>
        </p>
      </Card>
    </div>
  )
}
