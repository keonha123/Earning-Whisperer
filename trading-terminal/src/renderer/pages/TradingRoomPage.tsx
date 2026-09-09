import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams, Navigate } from "react-router-dom";
import { useTradingStore, type SignalFeedItem } from "../store/useTradingStore";
import { useUserStore } from "../store/useUserStore";
import { usePortfolioStore } from "../store/usePortfolioStore";
import { ipc, IPC_CHANNELS } from "../lib/ipc";
import ModeSelector from "../components/common/ModeSelector";
import SignalFeed from "../components/trading/SignalFeed";
import STTScriptPanel from "../components/trading/STTScriptPanel";
import OrderBar, {
  type OrderBarSubmitPayload,
} from "../components/trading/OrderBar";
import TradingRoomHeader from "../components/trading/TradingRoomHeader";
import FactCheckPanel from "../components/trading/FactCheckPanel";
import EarningsSummaryPanel from "../components/trading/EarningsSummaryPanel";
import { showIpcErrorToast } from "../components/common/Toast";
import type { TranscriptLine } from "../types/transcript";
import type { PricePoint } from "../types/priceSeries";
import { useLiveTranscript } from "../hooks/useLiveTranscript";
import { usePrices } from "../hooks/usePrices";
import { useCompanyDetail } from "../hooks/useCompanyDetail";
import { useFactCheck } from "../hooks/useFactCheck";
import { useEarningsSummary } from "../hooks/useEarningsSummary";
import type { TranscriptSegment } from "../store/useTranscriptStore";

type SignalFilter = "ALL" | "BUY" | "SELL" | "FAILED";

const TIMEFRAMES = ["1m", "5m", "1H", "1D", "1W", "1M"] as const;
type Timeframe = (typeof TIMEFRAMES)[number];

const EMPTY_PRICES: readonly PricePoint[] = [];

export default function TradingRoomPage() {
  const { mode, setMode, signalHistory, activeSignal, setSession } =
    useTradingStore();
  const { plan, settings, setSettings } = useUserStore();
  const orderableCash = usePortfolioStore((s) => s.orderableCash);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  // ticker 우선순위:
  //  1) ?ticker= 쿼리 파라미터 (사용자가 명시적으로 고른 종목 — 항상 우선)
  //  2) activeSignal (실시간 어닝콜 신호)
  //  3) null → /market 리다이렉트
  // 신호로 진입하는 경로도 모두 ?ticker= 를 붙이므로, param 우선이 안전하다.
  const paramTicker = searchParams.get("ticker") || null;
  const ticker =
    paramTicker ?? activeSignal?.ticker ?? null;

  // 현재 보고 있는 종목에 종속된 표시(헤더 AI 점수/액션, LIVE 배지)는 이 값만 쓴다.
  // ?ticker= 가 우선하므로 activeSignal 의 종목과 화면 종목이 다를 수 있고,
  // 그때 NVDA 신호의 점수가 AAPL 페이지에 뜨면 안 된다.
  const signalForTicker =
    activeSignal && activeSignal.ticker === ticker ? activeSignal : null;

  // ── 실시간 트랜스크립트 (Contract 4.5 STOMP /topic/transcript/{ticker}) ──────
  // ticker 변경 시 자동 SUBSCRIBE/UNSUBSCRIBE. segment 는 store 에 누적된다.
  const { segments: liveSegments, endedCallIds } = useLiveTranscript(ticker);

  // ── 실시간 팩트체크 (Contract 4.6 STOMP /topic/factcheck/{ticker}) ──────────
  // 트랜스크립트와 같은 ticker 를 따라간다. 판정은 서버에서 완료되어 도착한다.
  const { claims: factCheckClaims, clear: clearFactCheck } =
    useFactCheck(ticker);

  // ── 어닝콜 종료 후 종합 판단 (Contract 4.7 STOMP /topic/evaluation/{ticker}) ──
  // 회차당 1건뿐이라 늦게 구독하면 놓친다. 여기서 ticker 와 함께 구독을 세워 둔다.
  const { summary: earningsSummary, clear: clearEarningsSummary } =
    useEarningsSummary(ticker);

  // ── 실시간 시세 (다른 화면과 동일 소스: PRICES_UPDATE ← PricePoller/STOMP) ──────
  const { prices } = usePrices();
  const livePrice = ticker ? prices[ticker] : undefined;

  // ── 가격 차트 시계열 (STOCK_GET_DETAIL.chart30d 재사용 — CompanyDrawer 와 동일 소스) ──
  // 30일 일봉 종가. 분봉(1m/5m/1H) 실시간 누적은 별도 작업(범위 외)이라 timeframe 은 아직 UI-only.
  const { data: companyDetail } = useCompanyDetail(ticker);
  const chartSeries = useMemo<readonly PricePoint[]>(() => {
    const c30 = companyDetail?.chart30d;
    if (c30 && c30.length > 0) {
      return (
        c30
          .filter((d) => Number.isFinite(d.close))
          // date 는 "YYYY-MM-DD" → X축 라벨용 "MM-DD" 로 축약 (full date 는 좁은 축에서 겹침).
          .map((d) => ({ time: d.date.slice(5), price: d.close }))
      );
    }
    return EMPTY_PRICES;
  }, [companyDetail]);

  // segment → TranscriptLine 어댑터 (STTScriptPanel 의 기존 인터페이스 보존).
  const liveTranscript = useMemo<readonly TranscriptLine[]>(
    () => liveSegments.map(toTranscriptLine),
    [liveSegments],
  );

  const transcript: readonly TranscriptLine[] = liveTranscript;

  // 활성 callId — 가장 최근 segment 의 callId. 없으면 null.
  const activeCallId =
    liveSegments.length > 0
      ? liveSegments[liveSegments.length - 1].callId
      : null;

  // LIVE 판정 (Contract 4.5 반영):
  //  - 활성 트랜스크립트 세션이 있고 (activeCallId 존재),
  //  - 그 callId 가 endedCallIds 에 포함되지 않을 때 LIVE.
  //  - fallback: 트랜스크립트 세션이 없으면 신호 기반 판정. 단 현재 종목의 신호일 때만 —
  //    다른 종목 신호로 LIVE 를 오표시하지 않는다.
  const isLive =
    activeCallId != null
      ? !endedCallIds.has(activeCallId)
      : signalForTicker != null;
  // 회사명은 종목 상세(STOCK_GET_DETAIL)에서 온다 — CompanyDrawer 와 같은 소스.
  const companyName = companyDetail?.companyName ?? null;
  // 현재가/변동률: 실시간 시세(PRICES_UPDATE) 우선, 없으면 DEV fixture 폴백.
  // 단 실시세가 있으면 변동치도 실데이터 기준만 사용 — 전일종가 결측(previousClose<=0,
  // KIS 미제공) 시엔 미표시(undefined). 실가격 + fixture 가짜변동률 혼합을 방지.
  const currentPrice =
    livePrice?.currentPrice ?? companyDetail?.currentPrice ?? null;
  const changePercent = livePrice
    ? livePrice.previousClose > 0
      ? ((livePrice.currentPrice - livePrice.previousClose) /
          livePrice.previousClose) *
        100
      : undefined
    : undefined;
  const changeAmount = livePrice
    ? livePrice.previousClose > 0
      ? livePrice.currentPrice - livePrice.previousClose
      : undefined
    : undefined;
  const priceLabel =
    currentPrice != null
      ? `$${currentPrice.toFixed(2)}`
      : "—";
  // 세션 라벨·경과 시간은 아직 실데이터 소스가 없다. 가짜 값을 띄우지 않는다.
  const sessionLabel = null;
  const elapsedLabel = null;

  // ── 어닝콜 시연 재생 제어 (Contract 7.8) ────────────────────────────────────
  const [demoStarting, setDemoStarting] = useState(false);

  // 팩트체크 대기 표시 — 발언은 떴는데 그 구간 판정이 아직 안 온 상태.
  // AI Engine 이 3문장을 모아 LLM 2패스를 돌리므로 5~15초가 걸린다. 이 표시가 없으면
  // 사용자는 시스템이 멈춘 것으로 오해한다.
  const lastCheckedSequence =
    factCheckClaims.length > 0
      ? factCheckClaims[factCheckClaims.length - 1].batchEndSequence
      : -1;
  const lastSegmentSequence =
    liveSegments.length > 0
      ? liveSegments[liveSegments.length - 1].sequence
      : -1;
  const factCheckAnalyzing =
    isLive && lastSegmentSequence > lastCheckedSequence;

  // 콜이 실제로 재생됐고(세그먼트가 있고) 끝났는데 아직 종합 판단이 안 온 상태.
  // 종목을 열어만 둔 경우와 구분하기 위해 세그먼트 존재를 함께 본다.
  const awaitingSummary = !isLive && liveSegments.length > 0;

  // ── 신호 필터 (로컬 state) ────────────────────────────────────────────────────
  const [filter, setFilter] = useState<SignalFilter>("ALL");

  const filteredSignals = useMemo(
    () => filterSignals(signalHistory, filter),
    [signalHistory, filter],
  );

  const counts = useMemo(() => countByCategory(signalHistory), [signalHistory]);

  // ── 타임프레임 (UI only — fixture 단일 시계열만 표시) ──────────────────────────
  const [timeframe, setTimeframe] = useState<Timeframe>("1D");

  // ticker 결정 시 세션 시작 — cleanup 없음 (비명시적 이동 시 세션 유지가 의도된 동작)
  useEffect(() => {
    if (!ticker) return;
    ipc
      .invoke(IPC_CHANNELS.TRADE_SESSION_START, { ticker })
      .then(() => setSession(true, ticker))
      .catch(console.error);
  }, [ticker]);

  // ticker 없으면 Market Screen으로 — 모든 hooks 이후에 체크
  if (!ticker) return <Navigate to="/market" replace />;

  /**
   * 시연 재생 시작 (Contract 7.8).
   *
   * 백엔드가 스크립트를 실제 인입 경로로 흘려보내므로, 이 화면은 평소와 똑같이
   * STOMP 로 받기만 하면 된다. 재시작 시 이전 회차의 판정이 남아 있으면 혼동되므로
   * 누적된 팩트체크를 먼저 비운다.
   */
  async function handleStartDemo() {
    if (!ticker || demoStarting) return
    setDemoStarting(true)
    try {
      const result = (await ipc.invoke(IPC_CHANNELS.DEMO_EARNINGS_START, { ticker })) as
        | { ok: true; segmentCount: number }
        | { ok: false; reason: string; message: string }
      if (result.ok) {
        clearFactCheck(ticker)
        // 이전 회차의 종합 판단이 남아 있으면 새 어닝콜이 시작됐는데도 지난 결론이
        // 계속 떠 있게 된다.
        clearEarningsSummary(ticker)
        return
      }
      // showIpcErrorToast 는 Error 를 기대한다 — 문자열을 그대로 넘기지 않는다.
      showIpcErrorToast(
        new Error(
          result.reason === 'ALREADY_RUNNING'
            ? '이미 시연이 진행 중입니다. 잠시 후 다시 시도하세요.'
            : result.message,
        ),
      )
    } catch (e) {
      showIpcErrorToast(e)
    } finally {
      setDemoStarting(false)
    }
  }

  function handleExit() {
    navigate("/market");
  }

  async function handleModeChange(newMode: typeof mode) {
    try {
      await ipc.invoke(IPC_CHANNELS.SETTINGS_UPDATE, {
        tradingMode: newMode,
        maxBuyRatio: settings.maxBuyRatio,
        maxHoldingRatio: settings.maxHoldingRatio,
        cooldownMinutes: settings.cooldownMinutes,
        // 누락 시 백엔드가 임계치를 기본값으로 덮어쓴다 — 현재 설정값을 그대로 보낸다.
        aiScoreThreshold: settings.aiScoreThreshold,
      });
      setMode(newMode);
      setSettings({ tradingMode: newMode });
    } catch (e) {
      console.error("모드 변경 실패:", e);
      showIpcErrorToast(e);
    }
  }

  const [isOrderLoading, setIsOrderLoading] = useState(false);

  async function handleOrderSubmit(payload: OrderBarSubmitPayload) {
    if (!ticker) return;
    setIsOrderLoading(true);
    try {
      await ipc.invoke(IPC_CHANNELS.KIS_PLACE_MANUAL_ORDER, {
        side: payload.side,
        ticker,
        qty: payload.qty,
        price: payload.price,
      });
    } catch (e) {
      showIpcErrorToast(e);
    } finally {
      setIsOrderLoading(false);
    }
  }

  return (
    <div className="flex flex-col h-[calc(100%+3rem)] -m-6">
      {/* ── 페이지 내부 상단 헤더 행 (LIVE + ticker + 종목정보 + 메타 + ModeSelector) */}
      <div className="px-4 flex items-center justify-between gap-3 border-b border-border-subtle bg-surface-0">
        <TradingRoomHeader
          ticker={ticker}
          companyName={companyName}
          sessionLabel={sessionLabel}
          elapsedLabel={elapsedLabel}
          isLive={isLive}
          onExit={handleExit}
          onStartDemo={handleStartDemo}
          demoStarting={demoStarting}
        />
        <div className="w-72 shrink-0">
          <ModeSelector
            currentMode={mode}
            userPlan={plan}
            onChange={handleModeChange}
            size="compact"
          />
        </div>
      </div>

      {/* ── 3-column body ───────────────────────────────────────────────────────── */}
      <div
        className="flex-1 grid gap-3 p-3 min-h-0"
        style={{ gridTemplateColumns: "35fr 40fr 25fr" }}
      >
        {/* LEFT 35% — STT 스크립트 */}
        <STTScriptPanel
          transcript={transcript}
          isLive={isLive && transcript.length > 0}
          wpm={undefined}
        />

        {/* MIDDLE 40% — 가격 차트 (상) + AI 점수 차트 (하) */}
        <section className="card p-0 flex flex-col overflow-hidden min-h-0">
          <div className="h-10 px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0">
            <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-[0.14em] inline-flex items-center gap-2">
              <span className="w-2 h-2 rounded-sm bg-accent-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
              {ticker ?? "—"} · 실시간 차트
            </span>
            <TimeframeToggle value={timeframe} onChange={setTimeframe} />
          </div>

          <div className="flex-1 flex flex-col min-h-0">
            {/* 가격 pane — 전체의 45% */}
            <div
              style={{ flex: "45 1 0%" }}
              className="flex flex-col min-h-0 overflow-hidden"
            >
              <ChartPane
                kind="price"
                priceLabel={priceLabel}
                changePercent={changePercent}
                changeAmount={changeAmount}
                volumeLabel={undefined}
                marketSession={undefined}
                series={chartSeries}
                isLive={isLive}
              />
            </div>

            {/* 팩트체크 pane — 전체의 55%. 실시간 판정이 이 화면의 핵심이다. */}
            <div
              style={{ flex: "55 1 0%" }}
              className="flex flex-col min-h-0 overflow-hidden"
            >
              <FactCheckPanel
                claims={factCheckClaims}
                analyzing={factCheckAnalyzing}
              />
            </div>
          </div>
        </section>

        {/* RIGHT 25% — 종합 판단(도착 시) + 신호 피드 */}
        {/*
          이 래퍼가 25fr 컬럼의 grid item 이다. min-w-0 / overflow-hidden 이 없으면
          긴 영문 rationale 이나 줄바꿈 불가 토큰이 컬럼을 밀어 차트 컬럼을 잡아먹는다.
          이전에는 이 자리의 section 이 그 역할을 하고 있었다.
        */}
        <div className="flex flex-col gap-3 min-h-0 min-w-0 overflow-hidden">
        {/*
          종합 판단은 어닝콜이 끝나야 도착한다. 도착 전에는 자리를 비워 두고
          신호 피드가 열을 다 쓰게 한다 — 빈 카드를 미리 띄워 둘 이유가 없다.
        */}
        {/*
          종합 판단은 회차당 1건뿐이라 놓치면 다시 받을 방법이 없다(백필 경로 없음).
          그래서 "아직 안 왔다" 와 "유실됐다" 가 화면에서 같아 보이면 안 된다.
          콜이 끝났는데 판단이 없는 동안은 대기 상태를 명시한다.
        */}
        {!earningsSummary && awaitingSummary && (
          <section className="card p-0 flex flex-col shrink-0">
            <div className="h-10 px-3.5 flex items-center border-b border-border-subtle">
              <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-[0.14em]">
                어닝콜 종합 판단
              </span>
            </div>
            <div className="px-3.5 py-3 text-[10.5px] text-text-tertiary leading-snug animate-pulse">
              어닝콜이 종료되었습니다. 전문을 종합 분석하는 중입니다...
            </div>
          </section>
        )}

        {/*
          종합 판단은 이 시연의 결론이다. 신호 피드보다 훨씬 넓게 준다 —
          3:2 로 뒀더니 회피·손절 계획·파급효과가 전부 스크롤 아래로 내려갔다.
        */}
        {earningsSummary && (
          <section className="card p-0 flex flex-col overflow-hidden min-h-0" style={{ flex: "5 1 0%" }}>
            <div className="h-10 px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0">
              <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-[0.14em] inline-flex items-center gap-2">
                <span className="w-2 h-2 rounded-sm bg-accent-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
                어닝콜 종합 판단
              </span>
            </div>
            <EarningsSummaryPanel summary={earningsSummary} />
          </section>
        )}

        <section className="card p-0 flex flex-col overflow-hidden min-h-0" style={{ flex: "2 1 0%" }}>
          <div className="h-10 px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0">
            <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-[0.14em]">
              신호 피드 ·{" "}
              <span className="num text-text-primary tracking-normal normal-case">
                {signalHistory.length}
              </span>
            </span>
            <span className="num text-[11px] text-text-tertiary">auto</span>
          </div>

          <>
            {/* 필터 칩 4개 */}
            <div className="flex gap-1 px-2.5 pt-2 pb-1 shrink-0">
              <FilterChip
                label="전체"
                count={counts.total}
                active={filter === "ALL"}
                onClick={() => setFilter("ALL")}
              />
              <FilterChip
                label="BUY"
                count={counts.buy}
                active={filter === "BUY"}
                onClick={() => setFilter("BUY")}
              />
              <FilterChip
                label="SELL"
                count={counts.sell}
                active={filter === "SELL"}
                onClick={() => setFilter("SELL")}
              />
              <FilterChip
                label="FAILED"
                count={counts.failed}
                active={filter === "FAILED"}
                onClick={() => setFilter("FAILED")}
              />
            </div>

            <div className="flex-1 overflow-y-auto min-h-0">
              <SignalFeed items={filteredSignals} />
            </div>
          </>
        </section>
        </div>
      </div>

      {/* ── 하단 80px 고정 OrderBar ─────────────────────────────────────────────── */}
      <OrderBar
        ticker={ticker}
        currentPrice={currentPrice}
        changePercent={changePercent}
        orderableCash={orderableCash}
        mode={mode}
        onSubmit={handleOrderSubmit}
        isLoading={isOrderLoading}
      />
    </div>
  );
}

/** ─────────────────────────────────────────────────────────────────────────────
 * 내부 헬퍼 컴포넌트 / 함수
 * ──────────────────────────────────────────────────────────────────────────── */

interface FilterChipProps {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}

function FilterChip({ label, count, active, onClick }: FilterChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={
        "text-[10px] px-2 py-[3px] rounded border tracking-[0.06em] transition-colors duration-100 " +
        (active
          ? "bg-surface-2 text-text-primary border-border-strong"
          : "bg-transparent text-text-tertiary border-border-subtle hover:text-text-primary")
      }
    >
      {label} <span className="num text-[10px] ml-0.5">{count}</span>
    </button>
  );
}

interface TimeframeToggleProps {
  value: Timeframe;
  onChange: (tf: Timeframe) => void;
}

function TimeframeToggle({ value, onChange }: TimeframeToggleProps) {
  return (
    <div
      role="tablist"
      aria-label="차트 타임프레임"
      className="inline-flex bg-surface-2 border border-border-subtle rounded p-px"
    >
      {TIMEFRAMES.map((tf) => {
        const active = tf === value;
        return (
          <button
            key={tf}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tf)}
            className={
              "num px-2.5 py-[3px] rounded-[3px] text-[10.5px] font-semibold tracking-[0.04em] " +
              (active
                ? "text-accent-300 bg-accent-500/[0.16] shadow-[inset_0_0_0_1px_rgba(16,185,129,0.4)]"
                : "text-text-tertiary hover:text-text-secondary")
            }
          >
            {tf}
          </button>
        );
      })}
    </div>
  );
}

interface ChartPaneProps {
  kind: "price";
  priceLabel: string;
  changePercent?: number;
  changeAmount?: number;
  volumeLabel?: string;
  marketSession?: "REGULAR" | "AFTER_HOURS" | "PRE_MARKET";
  series: readonly PricePoint[];
  isLive: boolean;
}

/**
 * ChartPane (price) — 디자인 캔버스의 mid-pane price 영역.
 *
 * SVG + fixture (PR #3 MiniLineChart 패턴 일관). lightweight-charts 미사용 —
 * 가격 차트는 단순 라인이고, 실시간 IPC 가 정의되기 전까지는 fixture 만 표시한다.
 *
 * NaN/Infinity 가드: validPoints 필터링 — 결측치가 섞이면 SVG path 가 깨진다
 * (MiniLineChart 와 동일 패턴).
 */
function ChartPane({
  priceLabel,
  changePercent,
  changeAmount,
  volumeLabel,
  marketSession,
  series,
  isLive,
}: ChartPaneProps) {
  const VIEW_W = 500;
  const VIEW_H = 130;
  const PAD_TOP = 8;
  const PAD_BOTTOM = 22;

  const { linePath, areaPath, lastX, lastY, hasData } = useMemo(() => {
    const valid = series.filter((p) => Number.isFinite(p.price));
    if (valid.length === 0) {
      return { linePath: "", areaPath: "", lastX: 0, lastY: 0, hasData: false };
    }
    const prices = valid.map((p) => p.price);
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const range = max - min || 1;
    const drawH = VIEW_H - PAD_TOP - PAD_BOTTOM;
    const stepX = valid.length > 1 ? VIEW_W / (valid.length - 1) : 0;

    const coords = valid.map((pt, i) => {
      const x = i * stepX;
      const y = PAD_TOP + ((max - pt.price) / range) * drawH;
      return { x, y };
    });
    const lp = coords
      .map(
        (c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(2)},${c.y.toFixed(2)}`,
      )
      .join(" ");
    const last = coords[coords.length - 1];
    const ap = lp + ` L${last.x.toFixed(2)},${VIEW_H} L0,${VIEW_H} Z`;
    return {
      linePath: lp,
      areaPath: ap,
      lastX: last.x,
      lastY: last.y,
      hasData: true,
    };
  }, [series]);

  // Y축 라벨 (4단계, 최고 → 최저).
  const yTicks = useMemo(() => {
    const valid = series.filter((p) => Number.isFinite(p.price));
    if (valid.length === 0) return [];
    const prices = valid.map((p) => p.price);
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const slice = (max - min) / 4;
    return [max, max - slice, max - slice * 2, max - slice * 3, min];
  }, [series]);

  // X축 라벨 (5개 균등 시간).
  const xTicks = useMemo(() => {
    if (series.length === 0) return [] as string[];
    if (series.length <= 6) return series.map((p) => p.time);
    const out: string[] = [];
    for (let i = 0; i < 6; i++) {
      const idx = Math.round((i * (series.length - 1)) / 5);
      out.push(series[idx].time);
    }
    return out;
  }, [series]);

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-surface-1 relative">
      {/* pane-hd */}
      <div className="h-[34px] px-3.5 flex items-center border-b border-border-subtle shrink-0 gap-2.5">
        <span className="num text-[13px] font-semibold text-text-primary">
          {priceLabel}
        </span>
        {changePercent != null && Number.isFinite(changePercent) && (
          <span
            className={`num text-[11px] font-semibold px-1.5 py-px rounded ${
              changePercent >= 0
                ? "bg-buy/[0.14] text-buy"
                : "bg-sell/[0.14] text-sell"
            }`}
          >
            {changePercent >= 0 ? "+" : ""}
            {changePercent.toFixed(2)}%
          </span>
        )}
        {changeAmount != null && Number.isFinite(changeAmount) && (
          <span className="num text-[11px] text-text-tertiary">
            {changeAmount >= 0 ? "+" : "-"}${Math.abs(changeAmount).toFixed(2)}
          </span>
        )}
        {volumeLabel && (
          <span className="text-[10.5px] text-text-tertiary">
            Vol {volumeLabel}
          </span>
        )}
        {marketSession && (
          <span className="num text-[10.5px] text-text-tertiary ml-auto">
            {marketSession === "AFTER_HOURS"
              ? "After Hours"
              : marketSession === "PRE_MARKET"
                ? "Pre Market"
                : "Regular"}
          </span>
        )}
      </div>

      {/* chart-wrap */}
      <div className="relative flex-1 min-h-0 px-3.5 pt-2 pb-[22px]">
        {/* Y축 */}
        <div
          className="absolute left-0.5 top-2 w-9 flex flex-col justify-between
                     num text-[8.5px] text-text-tertiary text-right pr-1"
          style={{ bottom: "22px" }}
        >
          {yTicks.map((y, i) => (
            <span key={i}>${y.toFixed(0)}</span>
          ))}
        </div>

        {/* SVG */}
        {hasData ? (
          <svg
            viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
            preserveAspectRatio="none"
            className="absolute"
            style={{
              left: 42,
              right: 14,
              top: 8,
              bottom: 22,
              width: "calc(100% - 56px)",
              height: "calc(100% - 30px)",
            }}
            role="img"
            aria-label="가격 추이 차트"
          >
            {/* grid */}
            <line
              x1="0"
              y1="15"
              x2={VIEW_W}
              y2="15"
              stroke="#1e2738"
              strokeWidth="1"
            />
            <line
              x1="0"
              y1="50"
              x2={VIEW_W}
              y2="50"
              stroke="#1e2738"
              strokeWidth="1"
            />
            <line
              x1="0"
              y1="85"
              x2={VIEW_W}
              y2="85"
              stroke="#1e2738"
              strokeWidth="1"
            />
            <line
              x1="0"
              y1="115"
              x2={VIEW_W}
              y2="115"
              stroke="#1e2738"
              strokeWidth="1"
            />

            <path d={areaPath} fill="rgba(16,185,129,0.10)" />
            <path
              d={linePath}
              fill="none"
              stroke="#10b981"
              strokeWidth="1.5"
              strokeLinejoin="round"
            />
            <circle cx={lastX} cy={lastY} r="10" fill="rgba(16,185,129,0.18)" />
            <circle
              cx={lastX}
              cy={lastY}
              r="4"
              fill="#10b981"
              stroke="#0b1017"
              strokeWidth="2"
            />
          </svg>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-text-disabled text-xs">
            {isLive ? "실시간 데이터 동기화 중" : "데이터 없음"}
          </div>
        )}

        {/* X축 */}
        <div
          className="absolute flex justify-between num text-[8.5px] text-text-tertiary"
          style={{ left: 42, right: 14, bottom: 6 }}
        >
          {xTicks.map((t, i) => (
            <span key={i}>{t}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

/** ─────────────────────────────────────────────────────────────────────────────
 * 순수 함수
 * ──────────────────────────────────────────────────────────────────────────── */

function filterSignals(
  items: SignalFeedItem[],
  filter: SignalFilter,
): SignalFeedItem[] {
  if (filter === "ALL") return items;
  if (filter === "FAILED") return items.filter((s) => s.status === "FAILED");
  return items.filter((s) => s.action === filter);
}

interface SignalCounts {
  total: number;
  buy: number;
  sell: number;
  failed: number;
}

function countByCategory(items: SignalFeedItem[]): SignalCounts {
  let buy = 0;
  let sell = 0;
  let failed = 0;
  for (const s of items) {
    if (s.action === "BUY") buy++;
    else if (s.action === "SELL") sell++;
    if (s.status === "FAILED") failed++;
  }
  return { total: items.length, buy, sell, failed };
}

/**
 * TranscriptSegment (실시간 store) → TranscriptLine (STTScriptPanel UI 모델).
 *
 *  - id: `${callId}-${sequence}` — 동일 어닝콜 내 sequence 단조 증가가 보장하는 unique key.
 *  - timestamp: startMs 를 "mm:ss" 로 포맷 (어닝콜 시작 기준 경과 시간).
 *  - speaker: 누락 시 빈 문자열 ("[mm:ss] · ·" 가 되지 않도록 fallback).
 *  - ai_score: 별도 시그널 채널 (/user/queue/signals) 에서 매핑되므로 어댑터에서는 undefined.
 */
function toTranscriptLine(seg: TranscriptSegment): TranscriptLine {
  return {
    id: `${seg.callId}-${seg.sequence}`,
    timestamp: formatMmSs(seg.startMs),
    speaker: seg.speaker ?? "",
    text: seg.text,
    ai_score: undefined,
  };
}

/** ms → "mm:ss" 포맷. 음수/NaN/Infinity 는 "00:00" 으로 fallback. */
function formatMmSs(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "00:00";
  const totalSeconds = Math.floor(ms / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
