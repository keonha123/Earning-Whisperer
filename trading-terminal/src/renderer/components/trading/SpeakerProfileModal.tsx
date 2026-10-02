import { useEffect, useState } from 'react'
import Modal from '../common/Modal'
import type { SpeakerProfile, SpeakerCallStats } from '../../types/speakerProfile'
import { EMPTY_SPEAKER_STATS } from '../../types/speakerProfile'

interface SpeakerProfileModalProps {
  open: boolean
  onClose: () => void
  profiles: readonly SpeakerProfile[]
  /** matchKey → 이번 콜 집계. 없는 키는 발언 0건으로 본다. */
  stats: ReadonlyMap<string, SpeakerCallStats>
  /** 열릴 때 먼저 보여줄 사람의 matchKey (사용자가 클릭한 화자). */
  initialSpeakerKey?: string | null
  /** 지금 발언 중인 사람의 matchKey. 탭의 발화 중 표시에만 쓴다. */
  activeSpeakerKey?: string | null
  /** 콜 진행 중 여부. 발언이 없는 사유를 "아직" 과 "발췌에 없음" 으로 갈라 말한다. */
  isLive: boolean
}

/**
 * SpeakerProfileModal — 콜 참가자 명부.
 *
 * 좌측 참가자 탭 + 우측 상세. 상세에 뜨는 값은 두 종류뿐이다:
 *  - 트랜스크립트에 적힌 사실 (이름 · 직책 · 소속 · 경영진/애널리스트)
 *  - 이번 회차에 실제로 도착한 데이터로 계산한 집계 (발언량 · 팩트체크 판정)
 *
 * 화법 성향이나 과거 가이던스 달성률처럼 원문에서 확인할 수 없는 항목은 표시하지 않는다.
 */
export default function SpeakerProfileModal({
  open,
  onClose,
  profiles,
  stats,
  initialSpeakerKey,
  activeSpeakerKey,
  isLive,
}: SpeakerProfileModalProps) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null)

  // 열림/닫힘에 맞춰 선택을 초기화한다. 닫을 때도 비워야 다음에 열릴 때 effect 가 돌기 전
  // 한 프레임 동안 지난 사람이 그려지는 일이 없다. 열려 있는 동안에는 사용자의 탭 선택을
  // 유지한다 — 새 세그먼트마다 탭이 튀면 읽을 수가 없다.
  useEffect(() => {
    setSelectedKey(open ? (initialSpeakerKey ?? null) : null)
    // initialSpeakerKey 는 열리는 시점 값만 쓴다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  if (profiles.length === 0) return null

  const profile =
    profiles.find((p) => p.matchKey === selectedKey) ??
    profiles.find((p) => p.matchKey === initialSpeakerKey) ??
    profiles[0]
  const stat = stats.get(profile.matchKey) ?? EMPTY_SPEAKER_STATS

  const management = profiles.filter((p) => p.kind === 'MANAGEMENT')
  const analysts = profiles.filter((p) => p.kind === 'ANALYST')
  const panelId = `speaker-panel-${profile.matchKey.replace(/[^a-z0-9]+/g, '-')}`

  return (
    <Modal open={open} onClose={onClose} ariaLabel="발화자 프로필">
      <div style={{ width: 720 }} className="flex flex-col max-h-[85vh]">
        {/* 헤더 */}
        <div className="h-12 px-5 flex items-center justify-between border-b border-border-subtle shrink-0">
          <div className="flex items-center gap-2.5">
            <span
              className="w-2 h-2 rounded-sm"
              style={{ background: '#a78bfa', boxShadow: '0 0 8px rgba(167,139,250,0.5)' }}
            />
            <span className="text-[13px] font-semibold text-text-primary">발화자 프로필</span>
            <span className="num text-[11px] text-text-tertiary">
              경영진 {management.length} · 애널리스트 {analysts.length}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-6 h-6 flex items-center justify-center rounded text-text-tertiary
                       hover:text-text-primary hover:bg-surface-2 transition-colors duration-100
                       focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent-500"
            aria-label="닫기"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M2 2l8 8M10 2l-8 8" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* 바디: 탭 + 상세 */}
        <div className="flex flex-1 min-h-0 overflow-hidden">
          {/* 좌측 탭 — 경영진 먼저, 애널리스트 다음. */}
          <div
            role="tablist"
            aria-orientation="vertical"
            aria-label="콜 참가자"
            className="w-[200px] shrink-0 border-r border-border-subtle flex flex-col overflow-y-auto bg-surface-1"
          >
            {(
              [
                ['경영진', management],
                ['애널리스트', analysts],
              ] as const
            ).map(([label, group]) =>
              group.length === 0 ? null : (
                <div key={label} className="flex flex-col">
                  <div className="px-3.5 pt-3 pb-1.5 text-[9px] font-semibold text-text-tertiary uppercase tracking-[0.12em]">
                    {label}
                  </div>
                  {group.map((p) => {
                    const isActive = p.matchKey === profile.matchKey
                    const isSpeaking = p.matchKey === activeSpeakerKey
                    const spoken = (stats.get(p.matchKey) ?? EMPTY_SPEAKER_STATS).segmentCount
                    return (
                      <button
                        key={p.matchKey}
                        type="button"
                        role="tab"
                        aria-selected={isActive}
                        aria-controls={isActive ? panelId : undefined}
                        onClick={() => setSelectedKey(p.matchKey)}
                        className={
                          'text-left px-3.5 py-2.5 border-b border-border-subtle transition-colors duration-100 flex flex-col gap-0.5 ' +
                          'focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent-500 ' +
                          (isActive ? 'bg-surface-2 border-l-2 border-l-[#a78bfa]' : 'hover:bg-surface-2')
                        }
                      >
                        <div className="flex items-center gap-1.5">
                          <span
                            className={
                              'text-[11px] font-semibold leading-snug ' +
                              (isActive ? 'text-text-primary' : 'text-text-secondary')
                            }
                          >
                            {p.name}
                          </span>
                          {isSpeaking && (
                            <>
                              <span className="w-1.5 h-1.5 rounded-full bg-buy shrink-0" aria-hidden="true" />
                              <span className="sr-only">발화 중</span>
                            </>
                          )}
                        </div>
                        <span className="text-[10px] text-text-tertiary leading-snug truncate">
                          {p.affiliation || p.title}
                          {spoken > 0 && <span className="num"> · {spoken}건</span>}
                        </span>
                      </button>
                    )
                  })}
                </div>
              ),
            )}
          </div>

          {/* 우측 상세 */}
          <div
            id={panelId}
            role="tabpanel"
            className="flex-1 min-w-0 overflow-y-auto p-5 flex flex-col gap-4"
          >
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <span className="text-[15px] font-bold text-text-primary">{profile.name}</span>
                <span className="px-1.5 py-px rounded text-[10px] border border-border-subtle bg-surface-2 text-text-secondary">
                  {profile.kind === 'ANALYST' ? '애널리스트' : '경영진'}
                </span>
              </div>
              {profile.title && (
                <span className="text-[12px] text-text-secondary">{profile.title}</span>
              )}
              {profile.affiliation && (
                <span className="text-[11px] text-text-tertiary">{profile.affiliation}</span>
              )}
            </div>

            {/* 이번 콜 발언량 */}
            <div className="flex flex-col gap-2">
              <div className="text-[10px] font-semibold text-text-tertiary uppercase tracking-[0.1em]">
                이번 콜 발언
              </div>
              {stat.segmentCount === 0 ? (
                <div className="text-[12px] text-text-disabled">
                  {isLive
                    ? '아직 발언이 도착하지 않았습니다.'
                    : '재생된 발췌 구간에 이 참가자의 발언이 없습니다.'}
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-2">
                  <StatBox label="발언" value={`${stat.segmentCount}건`} />
                  <StatBox label="단어" value={stat.wordCount.toLocaleString()} />
                  {/* 구간 라벨은 "00:00 ~ 42:17" 로 길어서 2열을 통으로 쓴다. */}
                  <div className="col-span-2">
                    <StatBox
                      label="구간"
                      value={`${stat.firstTimestamp ?? '—'} ~ ${stat.lastTimestamp ?? '—'}`}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* 팩트체크 귀속 */}
            <div className="flex flex-col gap-2">
              <div className="text-[10px] font-semibold text-text-tertiary uppercase tracking-[0.1em]">
                발언 구간 팩트체크
              </div>
              {stat.supported + stat.contradicted + stat.insufficient === 0 ? (
                <div className="text-[12px] text-text-disabled">
                  이 참가자의 구간에 내려진 판정이 아직 없습니다.
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-3 gap-2">
                    <StatBox label="근거 일치" value={`${stat.supported}`} tone="buy" />
                    <StatBox label="근거 상충" value={`${stat.contradicted}`} tone="sell" />
                    <StatBox label="근거 부족" value={`${stat.insufficient}`} tone="muted" />
                  </div>
                  <p className="text-[10px] text-text-tertiary leading-relaxed">
                    판정은 3문장 묶음 단위라, 한 묶음에 두 사람의 발언이 섞이면 양쪽에 모두
                    계상됩니다. 참가자 개인의 정확도가 아니라 그 구간의 검증 결과입니다.
                  </p>
                </>
              )}
            </div>

            <p className="text-[10px] text-text-disabled leading-relaxed border-t border-border-subtle pt-3">
              이름 · 직책 · 소속은 어닝콜 원문 트랜스크립트에서 그대로 옮긴 값이고, 나머지
              수치는 이번 회차에 수신한 데이터로 계산한 것입니다.
            </p>
          </div>
        </div>
      </div>
    </Modal>
  )
}

const TONE_CLASS = {
  buy: 'text-buy',
  sell: 'text-sell',
  muted: 'text-text-tertiary',
  default: 'text-text-primary',
} as const

function StatBox({
  label,
  value,
  tone = 'default',
}: {
  label: string
  value: string
  tone?: keyof typeof TONE_CLASS
}) {
  return (
    <div className="p-2.5 rounded bg-surface-1 border border-border-subtle flex flex-col gap-1">
      <span className="text-[9px] text-text-tertiary uppercase tracking-[0.1em]">{label}</span>
      <span className={`num text-[13px] font-semibold ${TONE_CLASS[tone]}`}>{value}</span>
    </div>
  )
}
