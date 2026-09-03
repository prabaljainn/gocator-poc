import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import { Live } from './pages/Live'
import { Sessions } from './pages/Sessions'
import { SessionDetail } from './pages/SessionDetail'
import { Annotate } from './pages/Annotate'

const tab = ({ isActive }: { isActive: boolean }) =>
  `rounded px-3 py-1.5 text-sm ${isActive ? 'bg-seed-500 font-semibold text-soil-900' : 'text-soil-300 hover:bg-soil-800/60'}`

export default function App() {
  return (
    <BrowserRouter>
      <div className="mx-auto flex min-h-full max-w-7xl flex-col gap-5 p-4 sm:p-6">
        <header className="flex flex-wrap items-center gap-4">
          <h1 className="font-mono text-base font-semibold tracking-tight text-soil-50">
            gocator<span className="text-seed-400">·</span>sunflower
          </h1>
          <nav className="flex gap-1">
            <NavLink to="/" end className={tab}>Live</NavLink>
            <NavLink to="/sessions" className={tab}>Sessions</NavLink>
            <NavLink to="/annotate" className={tab}>Dataset Lab</NavLink>
          </nav>
        </header>
        <main className="flex-1">
          <Routes>
            <Route path="/" element={<Live />} />
            <Route path="/sessions" element={<Sessions />} />
            <Route path="/sessions/:id" element={<SessionDetail />} />
            <Route path="/annotate" element={<Annotate />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
