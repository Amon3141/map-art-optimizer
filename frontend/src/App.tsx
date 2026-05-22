import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { MinViewportGuard } from './components/MinViewportGuard'
import { isDevelopment } from './lib/appEnv'
import { HomePage } from './pages/HomePage'
import { DebugPage } from './pages/Debug'

export default function App() {
  return (
    <BrowserRouter>
      <MinViewportGuard />
      <Routes>
        <Route path="/" element={<HomePage />} />
        {isDevelopment ? (
          <Route path="/debug" element={<DebugPage />} />
        ) : (
          <Route path="/debug" element={<Navigate to="/" replace />} />
        )}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
