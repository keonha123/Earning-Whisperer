import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams, Navigate } from "react-router-dom";
import { useTradingStore } from "../store/useTradingStore";
import { useUserStore } from "../store/useUserStore";
import { usePortfolioStore } from "../store/usePortfolioStore";
import { ipc, IPC_CHANNELS } from "../lib/ipc";
import ModeSelector from "../components/common/ModeSelector";
import PositionOrderPanel, {
  type SessionOrder,
} from "../components/trading/PositionOrderPanel";
import STTScriptPanel from "../components/trading/STTScriptPanel";
import SpeakerProfileModal from "../components/trading/SpeakerProfileModal";
import OrderBar, {
  type OrderBarSubmitPayload,
} from "../components/trading/OrderBar";
import TradingRoomHeader from "../components/trading/TradingRoomHeader";
import VerificationPanel from "../components/trading/VerificationPanel";
import EarningsSummaryPanel from "../components/trading/EarningsSummaryPanel";
import { showIpcErrorToast } from "../components/common/Toast";
import type { TranscriptLine } from "../types/transcript";
import type { PricePoint } from "../types/priceSeries";
import { useLiveTranscript } from "../hooks/useLiveTranscript";
import { useSpeakerProfiles } from "../hooks/useSpeakerProfiles";
import { computeSpeakerStats, findProfileByLabel } from "../lib/speakerStats";
import type { SpeakerCallStats } from "../types/speakerProfile";
import { usePrices } from "../hooks/usePrices";
import { useCompanyDetail } from "../hooks/useCompanyDetail";
import { useFactCheck } from "../hooks/useFactCheck";
import { useTranscriptDiff } from "../hooks/useTranscriptDiff";
import { useEarningsSummary } from "../hooks/useEarningsSummary";
import type { TranscriptSegment } from "../store/useTranscriptStore";


const TIMEFRAMES = ["1m", "5m", "1H", "1D", "1W", "1M"] as const;
type Timeframe = (typeof TIMEFRAMES)[number];

const EMPTY_PRICES: readonly PricePoint[] = [];

export default function TradingRoomPage() {
  const { mode, setMode, activeSignal, setSession } =
    useTradingStore();
  const { plan, settings, setSettings } = useUserStore();
  const orderableCash = usePortfolioStore((s) => s.orderableCash);
  const holdings = usePortfolioStore((s) => s.holdings);
  // 잔고를 한 번이라도 불러왔는지. 0주 보유와 "아직 안 불러왔다" 를 구분해야 한다.
  const balanceLoaded = usePortfolioStore((s) => s.lastSyncedAt) != null;
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

  // ── 직전 콜 발언 대조 (STOMP /topic/transcript-diff/{ticker}) ──────────────
  // 팩트체크와 같은 ticker 를 따라간다. 주제와 무관한 발언은 도착하지 않는다.
  const {
    items: transcriptDiffItems,
    previousCall: transcriptDiffPreviousCall,
    clear: clearTranscriptDiff,
  } = useTranscriptDiff(ticker);

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

  // ── 발화자 프로필 ───────────────────────────────────────────────────────────
  // 명부는 사실 정보(이름/직책/소속)만 백엔드에서 오고, 발언량과 팩트체크 귀속은
  // 이 화면이 이미 받아 둔 세그먼트/판정으로 계산한다.
  const speakerProfiles = useSpeakerProfiles(ticker);
  const [speakerModalOpen, setSpeakerModalOpen] = useState(false);
  const [speakerModalKey, setSpeakerModalKey] = useState<string | null>(null);

  // 헤더 버튼 — 명부 전체를 연다. 열 사람을 따로 지정하지 않고, 모달이 "발언 중인 사람
  // → 없으면 첫 사람" 순서로 고른다.
  const openSpeakerRoster = useCallback(() => {
    setSpeakerModalKey(null);
    setSpeakerModalOpen(true);
  }, []);

  const openSpeakerProfile = useCallback(
    (label: string) => {
      const found = findProfileByLabel(speakerProfiles, label);
      // 명부에 없는 이름이면 첫 번째 사람을 열어 준다 — 모달은 명부 전체를 보여주므로
      // 빈 화면 대신 목록에서 직접 찾을 수 있다.
      setSpeakerModalKey(found?.matchKey ?? speakerProfiles[0]?.matchKey ?? null);
      setSpeakerModalOpen(true);
    },
    [speakerProfiles],
  );

  // 활성 callId — 가장 최근 segment 의 callId. 없으면 null.
  const activeCallId =
    liveSegments.length > 0
      ? liveSegments[liveSegments.length - 1].callId
      : null;

  // 발화자 집계는 모달이 열려 있을 때만 계산한다. 세그먼트가 도착할 때마다 새 배열이
  // 만들어지므로, 닫힌 상태에서도 돌면 회차 내내 헛일을 반복한다.
  const speakerStats = useMemo(
    () =>
      speakerModalOpen
        ? computeSpeakerStats(speakerProfiles, liveSegments, factCheckClaims, activeCallId)
        : new Map<string, SpeakerCallStats>(),
    [speakerModalOpen, speakerProfiles, liveSegments, factCheckClaims, activeCallId],
  );

  // LIVE 판정 (Contract 4.5 반영):
  //  - 활성 트랜스크립트 세션이 있고 (activeCallId 존재),
  //  - 그 callId 가 endedCallIds 에 포함되지 않을 때 LIVE.
  //  - fallback: 트랜스크립트 세션이 없으면 신호 기반 판정. 단 현재 종목의 신호일 때만 —
  //    다른 종목 신호로 LIVE 를 오표시하지 않는다.
  const isLive =
    activeCallId != null
      ? !endedCallIds.has(activeCallId)
      : signalForTicker != null;

  // 지금 발언 중인 사람 — 마지막 세그먼트의 화자. 콜이 끝났으면 아무도 발언 중이 아니다.
  const currentSpeakerKey = useMemo(() => {
    if (!isLive || liveSegments.length === 0) return null;
    const last = liveSegments[liveSegments.length - 1];
    return findProfileByLabel(speakerProfiles, last.speaker)?.matchKey ?? null;
  }, [isLive, speakerProfiles, liveSegments]);

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

  // ── 이 화면에서 낸 주문 (세션 한정 로컬 state) ───────────────────────────────
  // 전체 이력은 거래내역 화면이 담당한다. 여기는 "방금 낸 주문이 어떻게 됐는지" 만 본다.
  // store 에 두지 않는 이유: 화면을 나가면 의미가 없는 값이고, 종목이 바뀌면 초기화한다.
  const [sessionOrders, setSessionOrders] = useState<readonly SessionOrder[]>([]);

  useEffect(() => {
    setSessionOrders([]);
  }, [ticker]);

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
        | { ok: true; segmentCount: number; evidenceWarning?: string }
        | { ok: false; reason: string; message: string }
      if (result.ok) {
        // 재생은 시작됐지만 근거가 없으면 팩트체크가 전부 "근거 부족" 으로 나온다.
        // 조용히 넘어가면 시연 중에 원인을 알 수 없다.
        if (result.evidenceWarning) {
          showIpcErrorToast(new Error(result.evidenceWarning))
        }
        clearFactCheck(ticker)
        clearTranscriptDiff(ticker)
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
    // 주문 종목·수량·지정가는 요청에만 있고 응답에는 없다. 여기서 둘을 합쳐 기록한다.
    const localId = `${ticker}-${payload.side}-${Date.now()}`;
    const base = {
      localId,
      side: payload.side,
      qty: payload.qty,
      requestedPrice: payload.price ?? null,
      placedAt: Date.now(),
    };
    try {
      const result = (await ipc.invoke(IPC_CHANNELS.KIS_PLACE_MANUAL_ORDER, {
        side: payload.side,
        ticker,
        qty: payload.qty,
        price: payload.price,
      })) as {
        status: "PENDING" | "EXECUTED";
        orderId: string | null;
        executedPrice: number | null;
        executedQty: number;
        errorMessage: string | null;
      } | null;
      addSessionOrder({
        ...base,
        status: result?.status ?? "PENDING",
        executedQty: result?.executedQty ?? 0,
        executedPrice: result?.executedPrice ?? null,
        brokerOrderId: result?.orderId ?? null,
        errorMessage: result?.errorMessage ?? null,
      });
    } catch (e) {
      showIpcErrorToast(e);
      // 실패도 남긴다. 토스트는 사라지고, 무엇이 왜 안 됐는지 다시 볼 곳이 없어진다.
      addSessionOrder({
        ...base,
        status: "FAILED",
        executedQty: 0,
        executedPrice: null,
        brokerOrderId: null,
        errorMessage: e instanceof Error ? e.message : "주문에 실패했습니다.",
      });
    } finally {
      setIsOrderLoading(false);
    }
  }

  function addSessionOrder(order: SessionOrder) {
    // 최근 것이 앞에 온다. 세션 한정이라 상한은 넉넉히 둔다.
    setSessionOrders((prev) => [order, ...prev].slice(0, 30));
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
          onSpeakerProfile={
            speakerProfiles.length > 0 ? openSpeakerRoster : undefined
          }
          speakerCount={speakerProfiles.length}
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
        /*
          정보의 종류로 묶는다 — 왼쪽은 "무엇을 말했나", 가운데는 "내가 어떻게 행동할까",
          오른쪽은 "기계가 어떻게 판단했나". 이전에는 팩트체크가 가운데, 지난 분기 대비가
          오른쪽에 있어 성격이 같은 둘이 컬럼을 넘어 갈려 있었다.

          폭은 32 : 38 : 30 이다. 오른쪽이 25 였을 때 판정 카드의 인용 제목이 잘렸고,
          종합 판단도 좁아서 회피·손절 계획이 스크롤 아래로 내려갔다. 왼쪽을 35 에서 32 로
          줄인 것은 스크립트가 한 줄 단위로 짧게 들어오기 때문이다.
        */
        style={{ gridTemplateColumns: "32fr 38fr 30fr" }}
      >
        {/* LEFT 32% — STT 스크립트 */}
        <STTScriptPanel
          transcript={transcript}
          isLive={isLive && transcript.length > 0}
          wpm={undefined}
          onSpeakerClick={
            speakerProfiles.length > 0 ? openSpeakerProfile : undefined
          }
        />

        {/* MIDDLE 38% — 가격 차트 (상) + 보유 · 주문 (하). 아래의 주문 바까지 동선이 이어진다 */}
        <section className="card p-0 flex flex-col overflow-hidden min-h-0">
          <div className="h-10 px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0">
            <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-[0.14em] inline-flex items-center gap-2">
              <span className="w-2 h-2 rounded-sm bg-accent-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
              {ticker ?? "—"} · 실시간 차트
            </span>
            <TimeframeToggle value={timeframe} onChange={setTimeframe} />
          </div>

          <div className="flex-1 flex flex-col min-h-0">
            {/* 가격 pane — 전체의 45%. 기존 비율을 유지한다 */}
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

            {/*
              보유 · 주문 pane — 전체의 55%. 팩트체크가 있던 자리의 비율을 그대로 쓴다.
              보유 현황은 높이가 고정이고 아래 주문 목록이 남는 만큼을 받는다.
            */}
            <div
              style={{ flex: "55 1 0%" }}
              className="flex flex-col min-h-0 overflow-hidden border-t border-border-subtle"
            >
              <PositionOrderPanel
                ticker={ticker}
                holding={holdings.find((h) => h.ticker === ticker)}
                balanceLoaded={balanceLoaded}
                currentPrice={currentPrice ?? undefined}
                orders={sessionOrders}
              />
            </div>
          </div>
        </section>

        {/* RIGHT 30% — 발언 검증 + 종합 판단(도착 시) */}
        {/*
          이 래퍼가 30fr 컬럼의 grid item 이다. min-w-0 / overflow-hidden 이 없으면
          긴 영문 rationale 이나 줄바꿈 불가 토큰이 컬럼을 밀어 차트 컬럼을 잡아먹는다.
          이전에는 이 자리의 section 이 그 역할을 하고 있었다.
        */}
        <div className="flex flex-col gap-3 min-h-0 min-w-0 overflow-hidden">
        {/*
          뉴스 대조와 지난 분기 대비를 한 패널에 담는다. 근거는 다르지만 둘 다 특정
          발언에 붙는 판단이라 성격이 같고, 나누면 도착이 드문 쪽이 빈 상자로 남는다.
          종합 판단이 들어올 자리를 확보하는 효과도 있다. 배치 논의는 #122 에 있다.
        */}
        <section
          className="card p-0 flex flex-col overflow-hidden min-h-0"
          style={{ flex: earningsSummary ? "4 1 0%" : "1 1 0%" }}
        >
          <VerificationPanel
            claims={factCheckClaims}
            diffItems={transcriptDiffItems}
            previousCall={transcriptDiffPreviousCall}
            analyzing={factCheckAnalyzing}
          />
        </section>

        {/*
          종합 판단은 어닝콜이 끝나야 도착한다. 도착 전에는 자리를 비워 두고
          발언 검증이 열을 다 쓰게 한다 — 빈 카드를 미리 띄워 둘 이유가 없다.
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
          종합 판단은 이 시연의 결론이다. 도착하면 발언 검증보다 넓게 준다 —
          좁게 뒀더니 회피·손절 계획·파급효과가 전부 스크롤 아래로 내려갔다.
        */}
        {earningsSummary && (
          <section className="card p-0 flex flex-col overflow-hidden min-h-0" style={{ flex: "6 1 0%" }}>
            <div className="h-10 px-3.5 flex items-center justify-between border-b border-border-subtle shrink-0">
              <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-[0.14em] inline-flex items-center gap-2">
                <span className="w-2 h-2 rounded-sm bg-accent-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
                어닝콜 종합 판단
              </span>
            </div>
            <EarningsSummaryPanel summary={earningsSummary} />
          </section>
        )}

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

      <SpeakerProfileModal
        open={speakerModalOpen}
        onClose={() => setSpeakerModalOpen(false)}
        profiles={speakerProfiles}
        stats={speakerStats}
        initialSpeakerKey={speakerModalKey ?? currentSpeakerKey}
        activeSpeakerKey={currentSpeakerKey}
        isLive={isLive}
      />
    </div>
  );
}

/** ─────────────────────────────────────────────────────────────────────────────
 * 내부 헬퍼 컴포넌트 / 함수
 * ──────────────────────────────────────────────────────────────────────────── */

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
