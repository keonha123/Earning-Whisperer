import toast from 'react-hot-toast'

/**
 * 자리만 있는 기능을 눌렀을 때의 안내 (design-system 상태 패턴: 아직 없는 기능).
 * 눌러도 아무 일이 없으면 고장으로 읽히므로 "준비 중" 임을 알린다.
 */
export function showComingSoon(feature: string): void {
  toast(`${feature}${topicParticle(feature)} 준비 중입니다.`, { id: `coming-soon-${feature}`, duration: 2500 })
}

/** 마지막 글자에 받침이 있으면 "은", 없으면 "는". 한글이 아니면 "는". */
function topicParticle(word: string): string {
  const code = word.charCodeAt(word.length - 1) - 0xac00
  if (code < 0 || code > 11171) return '는'
  return code % 28 === 0 ? '는' : '은'
}
