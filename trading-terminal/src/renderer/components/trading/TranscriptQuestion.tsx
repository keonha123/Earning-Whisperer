import { useState } from 'react'
import type { TranscriptLine } from '../../types/transcript'
import { ipc, IPC_CHANNELS } from '../../lib/ipc'
interface Answer {
  available: boolean; answer_ko: string | null; refused: boolean; refusal_reason: string | null
  warnings: string[]
  evidence: { title?: string; snippet?: string; source?: string; published_at?: string; source_url?: string; url?: string }[]
  citations: { evidence_index: number; quote: string }[]
}
export default function TranscriptQuestion({ line }: { line: TranscriptLine }) {
  const [open, setOpen] = useState(false)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  async function ask() {
    if (!question.trim() || pending) return
    setPending(true); setError(''); setAnswer(null)
    try {
      const result = await ipc.invoke<Answer>(IPC_CHANNELS.TRANSCRIPT_ASK, {
        ticker: line.ticker, call_id: line.callId, segment_sequences: [line.sequence], question: question.trim(),
      })
      if (!result) throw new Error('Unavailable')
      setAnswer(result)
    } catch { setError('답변 서비스를 사용할 수 없습니다. 원문을 확인하고 다시 시도해 주세요.') }
    finally { setPending(false) }
  }
  return <div className="text-xs text-text-secondary">
    <button type="button" className="text-accent-300 underline" onClick={() => setOpen(!open)}>이 발언에 질문하기</button>
    {open && <div className="space-y-2 py-2">
      <label>발언에 대한 질문<input aria-label="발언에 대한 질문" className="w-full bg-surface-2 p-2" maxLength={2000} value={question} onChange={e => setQuestion(e.target.value)} /></label>
      <button type="button" disabled={pending || !question.trim()} onClick={() => void ask()}>{pending ? '근거 확인 중…' : '질문 보내기'}</button>
      <div role="status">{error}</div>
      {answer && <div aria-live="polite" className="space-y-2">
        <p>{answer.refused ? explainStatus(answer.refusal_reason) : answer.answer_ko ?? '답변을 만들지 못했습니다. 아래 근거를 확인해 주세요.'}</p>
        {answer.warnings?.map((warning, i) => <p key={i}>{explainStatus(warning)}</p>)}
        {answer.evidence?.map((evidence, i) => <details key={i} open><summary>근거 {i + 1}: {evidence.title ?? '출처'}</summary><p>{evidence.snippet}</p><p>{evidence.source} {evidence.published_at}</p>{safeUrl(evidence.url ?? evidence.source_url) && <a href={safeUrl(evidence.url ?? evidence.source_url)} target="_blank" rel="noreferrer">출처 보기</a>}
          {answer.citations?.filter(c => c.evidence_index === i).map((c, j) => <blockquote key={j}>{c.quote}</blockquote>)}
        </details>)}
      </div>}
    </div>}
  </div>
}

function safeUrl(value: string | undefined): string | undefined {
  if (!value) return undefined
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined } catch { return undefined }
}

function explainStatus(code: string | null): string {
  const messages: Record<string, string> = {
    investment_advice: '매수·매도 추천은 답변 범위에 포함되지 않습니다.',
    out_of_scope: '선택한 발언과 관련된 질문을 입력해 주세요.',
    insufficient: '확인할 근거가 충분하지 않습니다.',
    insufficient_reason_not_provided: '이 발언에 연결된 실제 근거 부족 판정 기록이 없습니다.',
    model_unavailable: '현재 답변 모델을 사용할 수 없습니다.',
    qa_unavailable_missing_api_key: '답변 서비스 설정이 준비되지 않았습니다.',
    timeout: '답변 시간이 초과되었습니다. 확보된 근거를 확인해 주세요.',
    qa_timeout: '답변 시간이 초과되었습니다. 확보된 근거를 확인해 주세요.',
    evidence_retrieval_timeout: '근거 조회 시간이 초과되었습니다.',
    evidence_retrieval_unavailable: '근거 저장소에 연결할 수 없습니다.',
    evidence_excluded_by_ticker_date_or_relevance: '종목·시점·관련성이 맞지 않는 근거는 제외했습니다.',
    invalid_or_unsupported_response: '근거로 확인되지 않은 답변은 표시하지 않았습니다.',
    qa_answer_not_verified: '답변의 근거 인용을 검증하지 못했습니다.',
  }
  return messages[code ?? ''] ?? '답변을 확인할 수 없습니다. 확보된 근거와 원문을 확인해 주세요.'
}
