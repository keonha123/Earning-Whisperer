/**
 * 스크롤 가장자리 — 떠 있는 콜 바 아래로 지나가는 글이 바의 글자와 겹쳐 읽히지 않도록, 면의 위쪽을
 * 서서히 어둡게 덮는다 (Apple 의 scroll edge effect 와 같은 역할). 누름은 아래 내용으로 통과시킨다.
 */
export default function ScrollEdge({ height }: { height: number }) {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-x-0 top-0 z-[1]"
      style={{
        height,
        background: 'linear-gradient(180deg, rgba(18,19,22,0.92) 0%, rgba(18,19,22,0.7) 55%, rgba(18,19,22,0) 100%)',
      }}
    />
  )
}
