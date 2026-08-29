import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
import { Login } from './pages/Login'
import { Register } from './pages/Register'
import { Dashboard } from './pages/Dashboard'
import { SendMoney } from './pages/SendMoney'
import { History } from './pages/History'
import { AgentChat } from './pages/AgentChat'
import { Scheduled } from './pages/Scheduled'
import { GroupPayments } from './pages/GroupPayments'
import { Debts } from './pages/Debts'

function RequireAuth({ children }: { children: React.ReactElement }) {
  const token = useAuthStore((s) => s.accessToken)
  if (!token) return <Navigate to="/login" replace />
  return children
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route
        path="/dashboard"
        element={
          <RequireAuth>
            <Dashboard />
          </RequireAuth>
        }
      />
      <Route
        path="/send"
        element={
          <RequireAuth>
            <SendMoney />
          </RequireAuth>
        }
      />
      <Route
        path="/history"
        element={
          <RequireAuth>
            <History />
          </RequireAuth>
        }
      />
      <Route
        path="/agent"
        element={
          <RequireAuth>
            <AgentChat />
          </RequireAuth>
        }
      />
      <Route
        path="/scheduled"
        element={
          <RequireAuth>
            <Scheduled />
          </RequireAuth>
        }
      />
      <Route
        path="/groups"
        element={
          <RequireAuth>
            <GroupPayments />
          </RequireAuth>
        }
      />
      <Route
        path="/debts"
        element={
          <RequireAuth>
            <Debts />
          </RequireAuth>
        }
      />
    </Routes>
  )
}

export default App
