/**
 * chartUtils — SVG 미니 차트 라벨 생성 유틸.
 *
 * 추출 배경 (PR #4):
 *  - DashboardPage 와 CompanyDrawer 가 동일한 시그니처/구현으로
 *    `pickXLabels`, `pickYTicks` 를 따로 갖고 있었다.
 *  - 두 함수의 유일한 차이는 Y축 round step (DashboardPage `/100`,
 *    CompanyDrawer `/10`). 이를 step 파라미터로 흡수하여 단일 구현으로 통합.
 *
 * 사용처:
 *  - DashboardPage.tsx (자산 추이 차트)
 *  - dashboard/CompanyDrawer.tsx (30일 일봉 차트)
 *  - 향후 PriceChart / 가격 시계열 컴포넌트에서도 재사용 가능.
 */

/**
 * 시계열 배열에서 균등 간격의 X축 라벨을 추출한다.
 *
 * - items.length <= maxLabels: 그대로 반환.
 * - 그 외: 첫/끝점 포함, maxLabels 개를 균등 인덱스로 샘플링.
 *
 * 제네릭으로 두어 호출처가 자체 ChartPoint / 다른 형태 객체 모두 사용 가능.
 */
export function pickXLabels<T>(items: T[], maxLabels = 5): T[] {
  if (items.length === 0) return []
  if (items.length <= maxLabels) return items
  const result: T[] = []
  for (let i = 0; i < maxLabels; i++) {
    const idx = Math.round((i * (items.length - 1)) / (maxLabels - 1))
    result.push(items[idx])
  }
  return result
}

/**
 * 가격 배열에서 4단계 Y축 라벨 (max → min) 을 추출한다.
 *
 * @param prices  가격 시계열.
 * @param count   라벨 개수 (기본 4).
 * @param step    반올림 단위. 100 = 100단위로 round, 10 = 10단위로 round.
 *                기본 1 = round 없이 정수만.
 *
 * 호출처별 step:
 *  - DashboardPage 자산 추이 (수십만 ~ 수백만 단위) → step=100
 *  - CompanyDrawer 30일 일봉 (수백 단위)         → step=10
 */
export function pickYTicks(prices: number[], count = 4, step = 1): number[] {
  if (prices.length === 0) return [0]
  const min = Math.min(...prices)
  const max = Math.max(...prices)
  const range = max - min || 1
  const slice = range / (count - 1)
  // 위에서 아래로 (max → min) 등간격.
  const ticks: number[] = []
  for (let i = 0; i < count; i++) {
    ticks.push(max - slice * i)
  }
  if (step === 1) return ticks.map((v) => Math.round(v))
  return ticks.map((v) => Math.round(v / step) * step)
}
