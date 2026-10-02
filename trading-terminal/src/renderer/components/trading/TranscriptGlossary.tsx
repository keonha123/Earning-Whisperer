import { useState } from 'react'
import { ipc, IPC_CHANNELS } from '../../lib/ipc'
interface Glossary { version: string | number; terms: { term: string; ko: string; definition_ko?: string; why_ko?: string }[] }
export default function TranscriptGlossary() {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<Glossary | null>(null)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(false)
  async function show() {
    setOpen(!open)
    if (data || loading || open) return
    setLoading(true); setError(false)
    try {
      const response = await ipc.invoke<Glossary>(IPC_CHANNELS.TRANSCRIPT_GLOSSARY)
      if (!response || !Array.isArray(response.terms)) throw new Error('Unavailable')
      setData(response)
    } catch { setError(true) }
    finally { setLoading(false) }
  }
  return <div className="px-3.5 py-2 border-b border-border-subtle text-xs">
    <button type="button" aria-expanded={open} onClick={() => void show()}>금융 용어 해설 {open ? '닫기' : '열기'}</button>
    {open && <div className="max-h-48 overflow-y-auto space-y-2" role="region" aria-label="금융 용어 해설">
      {loading && <p>용어 불러오는 중…</p>}{error && <p>용어집을 불러올 수 없습니다. 닫은 뒤 다시 열어 주세요.</p>}
      {data?.terms.map(term => <details key={term.term}><summary>{term.term} · {term.ko}</summary><p>{term.definition_ko}</p><p>{term.why_ko}</p></details>)}
    </div>}
  </div>
}
