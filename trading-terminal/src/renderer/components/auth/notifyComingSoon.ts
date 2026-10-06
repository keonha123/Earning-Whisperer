import toast from 'react-hot-toast'

/**
 * 자리만 있는 기능을 눌렀을 때의 안내 (design-system.md 상태 패턴 "아직 없는 기능").
 * 같은 기능을 여러 번 눌러도 토스트가 쌓이지 않게 기능 이름으로 id 를 고정한다.
 */
export function notifyComingSoon(feature: string): void {
  toast(`${feature}은(는) 준비 중입니다`, { id: `coming-soon:${feature}`, duration: 2500 })
}
