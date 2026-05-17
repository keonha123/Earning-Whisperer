import { useEffect, useRef } from 'react'
import { createChart, IChartApi, ISeriesApi, LineData, SeriesMarker, Time } from 'lightweight-charts'
import { SignalFeedItem } from '../../store/useTradingStore'

interface EmaChartProps {
  signalHistory: SignalFeedItem[]
}

export default function EmaChart({ signalHistory }: EmaChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Line'> | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const chart = createChart(container, {
      layout: {
        background: { color: '#0a0c0f' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e2738' },
        horzLines: { color: '#1e2738' },
      },
      width: container.clientWidth,
      height: container.clientHeight,
    })

    const lineSeries = chart.addLineSeries({
      color: '#3b82f6',
      lineWidth: 2,
    })

    chartRef.current = chart
    seriesRef.current = lineSeries

    const observer = new ResizeObserver(() => {
      if (container && chartRef.current) {
        chartRef.current.applyOptions({
          width: container.clientWidth,
          height: container.clientHeight,
        })
      }
    })
    observer.observe(container)

    return () => {
      observer.disconnect()
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [])

  useEffect(() => {
    const series = seriesRef.current
    if (!series) return

    if (signalHistory.length === 0) {
      series.setData([])
      series.setMarkers([])
      return
    }

    const sorted = [...signalHistory].reverse()

    const timeCount: Record<number, number> = {}
    const lineData: LineData[] = sorted.map((item) => {
      const base = item.receivedAt
      const count = timeCount[base] ?? 0
      timeCount[base] = count + 1
      const time = (base + count / 1000) as Time
      return { time, value: item.ai_score }
    })

    series.setData(lineData)

    const timeCountForMarkers: Record<number, number> = {}
    const markers: SeriesMarker<Time>[] = sorted
      .filter((item) => item.status === 'EXECUTED')
      .map((item) => {
        const base = item.receivedAt
        const count = timeCountForMarkers[base] ?? 0
        timeCountForMarkers[base] = count + 1
        const time = (base + count / 1000) as Time
        return {
          time,
          position: item.action === 'BUY' ? 'belowBar' : 'aboveBar',
          color: item.action === 'BUY' ? '#22c55e' : '#ef4444',
          shape: item.action === 'BUY' ? 'arrowUp' : 'arrowDown',
          text: item.action,
        } as SeriesMarker<Time>
      })

    series.setMarkers(markers)
  }, [signalHistory])

  return (
    <div className="relative w-full h-full">
      <div ref={containerRef} className="w-full h-full" />
      {signalHistory.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-text-disabled text-sm pointer-events-none">
          신호 수신 시 차트가 표시됩니다
        </div>
      )}
    </div>
  )
}
