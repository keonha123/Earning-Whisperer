import { useState } from 'react'
import Modal from '../common/Modal'
import type { SpeakerProfile } from '../../fixtures/speakerProfile.dev-mock'

interface SpeakerProfileModalProps {
  open: boolean
  onClose: () => void
  profiles: readonly SpeakerProfile[]
  /** 현재 발화 중인 화자의 matchKey (STT speaker 기준). 없으면 첫 번째 선택. */
  activeSpeakerKey?: string | null
}

/**
 * SpeakerProfileModal — 발화자 메타데이터 모달.
 *
 * 좌측 발화자 탭 + 우측 프로필 상세. Modal 컴포넌트 재사용.
 * activeSpeakerKey 로 현재 발화 중인 화자를 자동 선택한다.
 */
export default function SpeakerProfileModal({
  open,
  onClose,
  profiles,
  activeSpeakerKey,
}: SpeakerProfileModalProps) {
  const defaultIdx = activeSpeakerKey
    ? Math.max(0, profiles.findIndex((p) => p.matchKey === activeSpeakerKey.toLowerCase()))
    : 0

  const [selectedIdx, setSelectedIdx] = useState(defaultIdx)

  // activeSpeakerKey 변경 시 자동 탭 이동
  const resolvedIdx = activeSpeakerKey
    ? Math.max(0, profiles.findIndex((p) => p.matchKey === activeSpeakerKey.toLowerCase()))
    : selectedIdx

  const profile = profiles[resolvedIdx] ?? profiles[0]
  if (!profile) return null

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
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-6 h-6 flex items-center justify-center rounded text-text-tertiary
                       hover:text-text-primary hover:bg-surface-2 transition-colors duration-100"
            aria-label="닫기"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M2 2l8 8M10 2l-8 8" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* 바디: 탭 + 상세 */}
        <div className="flex flex-1 min-h-0 overflow-hidden">
          {/* 좌측 탭 */}
          <div className="w-[180px] shrink-0 border-r border-border-subtle flex flex-col overflow-y-auto bg-surface-1">
            {profiles.map((p, i) => {
              const isActive = i === resolvedIdx
              const isSpeaking = activeSpeakerKey
                ? p.matchKey === activeSpeakerKey.toLowerCase()
                : false
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => setSelectedIdx(i)}
                  className={
                    'text-left px-3.5 py-3 border-b border-border-subtle transition-colors duration-100 flex flex-col gap-0.5 ' +
                    (isActive
                      ? 'bg-surface-2 border-l-2 border-l-[#a78bfa]'
                      : 'hover:bg-surface-2')
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
                      <span className="w-1.5 h-1.5 rounded-full bg-buy shrink-0" title="발화 중" />
                    )}
                  </div>
                  <span className="text-[10px] text-text-tertiary leading-snug truncate">
                    {p.title}
                  </span>
                </button>
              )
            })}
          </div>

          {/* 우측 상세 */}
          <div className="flex-1 min-w-0 overflow-y-auto p-5 flex flex-col gap-4">
            {/* 이름 + 직책 */}
            <div className="flex flex-col gap-1">
              <span className="text-[15px] font-bold text-text-primary">{profile.name}</span>
              <span className="text-[12px] text-text-secondary">{profile.title}</span>
              <span className="text-[11px] text-text-tertiary">{profile.tenure}</span>
            </div>

            {/* 성향 요약 */}
            <div className="p-3 rounded bg-surface-1 border border-border-subtle">
              <div className="text-[10px] font-semibold text-text-tertiary uppercase tracking-[0.1em] mb-1.5">
                발화 성향
              </div>
              <div className="text-[12px] text-text-secondary leading-relaxed">
                {profile.style}
              </div>
              <div className="flex flex-wrap gap-1.5 mt-2.5">
                {profile.traits.map((t) => (
                  <span
                    key={t}
                    className="px-2 py-px rounded text-[10px] text-text-secondary
                               bg-surface-2 border border-border-subtle"
                  >
                    {t}
                  </span>
                ))}
              </div>
            </div>

            {/* 가이던스 정확도 (경영진만) */}
            {profile.guidanceAccuracy > 0 && (
              <div className="flex flex-col gap-1.5">
                <div className="text-[10px] font-semibold text-text-tertiary uppercase tracking-[0.1em]">
                  가이던스 달성률
                </div>
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-[4px] rounded-full bg-surface-2">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${profile.guidanceAccuracy}%`,
                        background: profile.guidanceAccuracy >= 85 ? '#10b981' : '#f59e0b',
                      }}
                    />
                  </div>
                  <span
                    className="num text-[12px] font-bold"
                    style={{ color: profile.guidanceAccuracy >= 85 ? '#10b981' : '#f59e0b' }}
                  >
                    {profile.guidanceAccuracy}%
                  </span>
                </div>
              </div>
            )}

            {/* 발언 이력 */}
            {profile.history.length > 0 && (
              <div className="flex flex-col gap-2">
                <div className="text-[10px] font-semibold text-text-tertiary uppercase tracking-[0.1em]">
                  주요 발언 이력
                </div>
                {profile.history.map((h, i) => (
                  <div key={i} className="flex gap-2.5 items-start">
                    <span className="num text-[10px] text-text-disabled shrink-0 pt-px w-12">
                      {h.date}
                    </span>
                    <span className="text-[11px] text-text-secondary leading-snug italic">
                      {h.quote}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* 유의사항 */}
            {profile.watchpoints.length > 0 && (
              <div className="flex flex-col gap-2">
                <div className="text-[10px] font-semibold text-text-tertiary uppercase tracking-[0.1em]">
                  투자자 유의사항
                </div>
                {profile.watchpoints.map((w, i) => (
                  <div key={i} className="flex gap-2 items-start">
                    <span className="text-[10px] text-[#f59e0b] shrink-0 pt-px">▶</span>
                    <span className="text-[11px] text-text-secondary leading-snug">{w}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

      </div>
    </Modal>
  )
}
