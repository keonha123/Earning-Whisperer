import { useState, useEffect } from 'react'

/** DEV 전용: STT 라인 노출 주기 (ms). */
const STT_INTERVAL_MS = 20000
/** DEV 전용: 첫 신규 라인 노출 전 초기 딜레이 (ms). */
const INITIAL_DELAY_MS = 10000

/**
 * useEarningsDemoPlayback — DEV 전용 어닝콜 시연 재생 엔진.
 *
 * preLoadedSteps 개수만큼 즉시 표시된 상태로 시작.
 * INITIAL_DELAY_MS 후 다음 라인부터 STT_INTERVAL_MS 간격으로 증가.
 * 마지막 라인 도달 시 freeze (루프 없음).
 *
 * - prod 빌드: 인터벌 실행 없음. sttStep = 0, loopKey = 0 고정 반환.
 * - DEV: preLoadedSteps-1 에서 시작, 딜레이 후 인터벌 시작.
 */
export function useEarningsDemoPlayback(
  totalSteps: number,
  preLoadedSteps = 0,
): {
  sttStep: number
  loopKey: number
} {
  const initStep = import.meta.env.DEV && preLoadedSteps > 0 ? preLoadedSteps - 1 : 0
  const [state, setState] = useState({ step: initStep, loopKey: 0 })

  useEffect(() => {
    if (!import.meta.env.DEV || totalSteps === 0) return

    let intervalId: ReturnType<typeof setInterval>

    const delayId = setTimeout(() => {
      intervalId = setInterval(() => {
        setState(({ step, loopKey }) => {
          if (step >= totalSteps - 1) return { step, loopKey }
          return { step: step + 1, loopKey }
        })
      }, STT_INTERVAL_MS)
    }, INITIAL_DELAY_MS)

    return () => {
      clearTimeout(delayId)
      clearInterval(intervalId)
    }
  }, [totalSteps])

  return { sttStep: state.step, loopKey: state.loopKey }
}
