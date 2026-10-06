import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams, Navigate } from "react-router-dom";
import { useTradingStore } from "../store/useTradingStore";
import { usePortfolioStore } from "../store/usePortfolioStore";
import { useConnectionStore } from "../store/useConnectionStore";
import { useDrawerStore } from "../store/useDrawerStore";
import { useTranscriptStore } from "../store/useTranscriptStore";
import { ipc, IPC_CHANNELS } from "../lib/ipc";
import SpeakerProfileModal from "../components/trading/SpeakerProfileModal";
import CallBar from "../components/call/CallBar";
import CallBriefing from "../components/call/CallBriefing";
import TranscriptStream from "../components/call/TranscriptStream";
import CallSideTabs from "../components/call/CallSideTabs";
import CallVerdict from "../components/call/CallVerdict";
import PriceCard from "../components/call/PriceCard";
import OrderSheet, { type OrderSubmitPayload } from "../components/call/OrderSheet";
import { useOrderAccount } from "../hooks/useOrderAccount";
import { DEMO_START_PARAM, DEMO_START_VALUE } from "../constants/demo";
import { showIpcErrorToast } from "../components/common/Toast";
import { applyTradeRecords, type SessionOrder, type TradeRecord } from "../lib/sessionOrders";
import {
  countDiffsByType,
  currentCallSegments,
  deriveCallPhase,
  formatCallClock,
  groupDiffsBySequence,
} from "../lib/callScreen";
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

/** 위쪽에 떠 있는 콜 바 아래로 내용이 지나가도록 각 면의 위쪽에 비워 두는 높이(px). */
const TOP_INSET = 72;

/** 콜 상태마다 주인공 열과 보조 열의 폭. */
const COLUMNS = {
  BEFORE: "minmax(0, 1.7fr) minmax(320px, 1fr)",
  LIVE: "minmax(0, 1.8fr) minmax(320px, 1fr)",
  ENDED: "minmax(300px, 0.9fr) minmax(0, 1.6fr)",
} as const;

const EMPTY_PRICES: readonly PricePoint[] = [];

export default function TradingRoomPage() {
  const { setSession, setDemo } = useTradingStore();
  const isDemo = useTradingStore((s) => s.isDemo);
  const orderableCash = usePortfolioStore((s) => s.orderableCash);
  const holdings = usePortfolioStore((s) => s.holdings);
  // 잔고를 한 번이라도 불러왔는지. 0주 보유와 "아직 안 불러왔다" 를 구분해야 한다.
  const balanceLoaded = usePortfolioStore((s) => s.lastSyncedAt) != null;
  const hasCredentials = useConnectionStore((s) => s.hasCredentials);
  const openDrawer = useDrawerStore((s) => s.open);
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  // ticker 는 ?ticker= 쿼리 파라미터로만 정한다. 없으면 종목 화면으로 보낸다.
  const ticker = searchParams.get("ticker") || null;

  // ── 실시간 트랜스크립트 (Contract 4.5 STOMP /topic/transcript/{ticker}) ──────
  // ticker 변경 시 자동 SUBSCRIBE/UNSUBSCRIBE. segment 는 store 에 누적된다.
  const { segments: liveSegments, endedCallIds } = useLiveTranscript(ticker);

  // ── 실시간 팩트체크 (Contract 4.6 STOMP /topic/factcheck/{ticker}) ──────────
  // 뉴스 대조 팩트체크는 제품 범위에서 빠져 화면에 그리지 않는다. 수신 코드 제거는 별도 작업이라
  // 구독과 재생 시작 시 비우기는 그대로 둔다.
  const { claims: factCheckClaims, clear: clearFactCheck } =
    useFactCheck(ticker);

  // ── 직전 콜 발언 대조 (STOMP /topic/transcript-diff/{ticker}) ──────────────
  // 주제와 무관한 발언은 도착하지 않는다.
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

  // ── 종목 상세 (STOCK_GET_DETAIL) — 브리핑 · 30일 차트 · 회사명 ──────────────
  const {
    data: companyDetail,
    loading: companyLoading,
    error: companyError,
  } = useCompanyDetail(ticker);
  const chartSeries = useMemo<readonly PricePoint[]>(() => {
    const c30 = companyDetail?.chart30d;
    if (c30 && c30.length > 0) {
      return (
        c30
          .filter((d) => Number.isFinite(d.close))
          // date 는 "YYYY-MM-DD" → 축 라벨용 "MM-DD" 로 축약.
          .map((d) => ({ time: d.date.slice(5), price: d.close }))
      );
    }
    return EMPTY_PRICES;
  }, [companyDetail]);

  // ── 콜 상태와 이번 회차 자막 ─────────────────────────────────────────────────
  // 시연을 중지한 콜은 종료 표시가 오지 않는다. 이 화면에서 끝난 것으로 다룬다.
  const [stoppedCallId, setStoppedCallId] = useState<string | null>(null);
  const effectiveEndedCallIds = useMemo(
    () => (stoppedCallId ? new Set([...endedCallIds, stoppedCallId]) : endedCallIds),
    [endedCallIds, stoppedCallId],
  );
  const phase = deriveCallPhase(
    liveSegments,
    effectiveEndedCallIds,
    earningsSummary ? earningsSummary.callId : undefined,
  );
  // 같은 종목을 다시 재생하면 지난 회차 자막이 store 에 남는다. 화면에는 이번 회차만 둔다.
  const segments = useMemo(() => currentCallSegments(liveSegments), [liveSegments]);
  const diffsBySequence = useMemo(
    () => groupDiffsBySequence(transcriptDiffItems),
    [transcriptDiffItems],
  );
  const diffCounts = useMemo(
    () => countDiffsByType(transcriptDiffItems),
    [transcriptDiffItems],
  );
  const isLive = phase === "LIVE";
  const lastCallId = segments.length > 0 ? segments[segments.length - 1].callId : null;
  // 지난 회차 판단은 보이지 않는다 — 콜 상태 판단과 같은 기준이다.
  const currentSummary =
    earningsSummary &&
    (earningsSummary.callId == null || lastCallId == null || earningsSummary.callId === lastCallId)
      ? earningsSummary
      : null;
  const activeCallId = lastCallId;
  // 콜 시작 기준 경과 시간 — 마지막 자막이 끝난 지점이다.
  const elapsedLabel =
    segments.length > 0 ? formatCallClock(segments[segments.length - 1].endMs) : null;
  // 무엇과 비교했는지. 첫 대조 항목이 도착해야 알 수 있다.
  const previousCallLabel = transcriptDiffPreviousCall
    ? transcriptDiffPreviousCall.fiscalQuarter ||
      transcriptDiffPreviousCall.title ||
      transcriptDiffPreviousCall.documentId
    : null;
  const [focus, setFocus] = useState<{ sequence: number; nonce: number } | null>(null);

  // ── 발화자 프로필 ───────────────────────────────────────────────────────────
  // 명부는 사실 정보(이름/직책/소속)만 백엔드에서 오고, 발언량은 이 화면이 받아 둔 세그먼트로 계산한다.
  const speakerProfiles = useSpeakerProfiles(ticker);
  const [speakerModalOpen, setSpeakerModalOpen] = useState(false);
  const [speakerModalKey, setSpeakerModalKey] = useState<string | null>(null);

  // 콜 바 버튼 — 명부 전체를 연다. 모달이 "발언 중인 사람 → 없으면 첫 사람" 순서로 고른다.
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

  // 발화자 집계는 모달이 열려 있을 때만 계산한다. 세그먼트가 도착할 때마다 새 배열이
  // 만들어지므로, 닫힌 상태에서도 돌면 회차 내내 헛일을 반복한다.
  const speakerStats = useMemo(
    () =>
      speakerModalOpen
        ? computeSpeakerStats(speakerProfiles, liveSegments, factCheckClaims, activeCallId)
        : new Map<string, SpeakerCallStats>(),
    [speakerModalOpen, speakerProfiles, liveSegments, factCheckClaims, activeCallId],
  );

  // 지금 발언 중인 사람 — 마지막 세그먼트의 화자. 콜이 끝났으면 아무도 발언 중이 아니다.
  const currentSpeakerKey = useMemo(() => {
    if (!isLive || segments.length === 0) return null;
    const last = segments[segments.length - 1];
    return findProfileByLabel(speakerProfiles, last.speaker)?.matchKey ?? null;
  }, [isLive, speakerProfiles, segments]);

  // 회사명은 종목 상세(STOCK_GET_DETAIL)에서 온다 — 종목 브리핑 패널과 같은 소스.
  const companyName = companyDetail?.companyName ?? null;
  // 현재가/변동: 실시간 시세 우선, 없으면 종목 상세의 현재가. 실시세가 있으면 변동치도 실데이터 기준만
  // 쓴다 — 전일종가 결측(previousClose<=0) 시엔 표시하지 않는다.
  const currentPrice =
    livePrice?.currentPrice ?? companyDetail?.currentPrice ?? null;
  const changePercent =
    livePrice && livePrice.previousClose > 0
      ? ((livePrice.currentPrice - livePrice.previousClose) / livePrice.previousClose) * 100
      : undefined;
  const changeAmount =
    livePrice && livePrice.previousClose > 0
      ? livePrice.currentPrice - livePrice.previousClose
      : undefined;
  const holding = ticker ? holdings.find((h) => h.ticker === ticker) : undefined;

  // ── 주문 계좌 ────────────────────────────────────────────────────────────────
  const orderAccount = useOrderAccount();
  const hasKey =
    orderAccount === "KIS_REAL" ? hasCredentials.real : hasCredentials.paper;
  const [orderOpen, setOrderOpen] = useState(false);

  // ── 어닝콜 시연 재생 제어 (Contract 7.8) ────────────────────────────────────
  const [demoBusy, setDemoBusy] = useState(false);

  // ── 이 화면에서 낸 주문 (세션 한정 로컬 state) ───────────────────────────────
  // 전체 이력은 거래 내역이 담당한다. 여기는 "방금 낸 주문이 어떻게 됐는지" 만 본다.
  // store 에 두지 않는 이유: 화면을 나가면 의미가 없는 값이고, 종목이 바뀌면 초기화한다.
  const [sessionOrders, setSessionOrders] = useState<readonly SessionOrder[]>([]);

  useEffect(() => {
    setSessionOrders([]);
    setOrderOpen(false);
    setStoppedCallId(null);
  }, [ticker]);

  // 접수 주문의 체결 반영. 체결 재확인은 백엔드 기록만 고치므로, 그 기록을 다시 받아
  // 증권사 주문번호로 짝지어 패널에 옮긴다.
  const syncSessionOrders = useCallback(async () => {
    const page = await ipc.invoke<{ content?: TradeRecord[] } | null>(
      IPC_CHANNELS.TRADES_GET,
      { page: 0, size: 50 },
    );
    setSessionOrders((prev) => applyTradeRecords(prev, page?.content ?? []));
  }, []);

  // KIS 체결통보로 main 이 재확인을 마치면 알려 준다 — 버튼 없이 바뀌는 경로.
  useEffect(
    () =>
      ipc.on(IPC_CHANNELS.TRADES_RECONCILED, () => {
        void syncSessionOrders().catch((e) =>
          console.warn("[CallScreen] 체결 반영 실패:", e),
        );
      }),
    [syncSessionOrders],
  );

  const [refreshingOrders, setRefreshingOrders] = useState(false);

  async function handleRefreshOrders() {
    if (refreshingOrders) return;
    setRefreshingOrders(true);
    try {
      // 거래 내역 화면과 같은 재확인이다. 진행 중이면 main 이 그 결과를 함께 기다린다.
      // 실패해도 기록은 다시 읽는다 — 다른 경로(체결통보, 거래 내역 화면)가 이미 고쳤을 수 있다.
      await ipc.invoke(IPC_CHANNELS.TRADES_RECONCILE_PENDING).catch(showIpcErrorToast);
      await syncSessionOrders();
    } catch (e) {
      showIpcErrorToast(e);
    } finally {
      setRefreshingOrders(false);
    }
  }

  // ticker 결정 시 세션 시작 — cleanup 없음 (비명시적 이동 시 세션 유지가 의도된 동작)
  useEffect(() => {
    if (!ticker) return;
    ipc
      .invoke(IPC_CHANNELS.TRADE_SESSION_START, { ticker })
      .then(() => setSession(true, ticker))
      .catch(console.error);
  }, [ticker]);

  const [submitting, setSubmitting] = useState(false);

  // 홈의 `시연 재생` 으로 들어오면(?demo=start) 자막 구독을 건 뒤 재생을 시작한다.
  // 구독보다 재생이 먼저 시작되면 첫 발언을 놓친다. 구독 요청은 응답을 기다리지 않으므로
  // 잠깐 두고 시작한다. 시작할 때 표시를 지워 다시 마운트돼도 재생을 또 시작하지 않게 한다.
  // 표시를 먼저 지우면 이 효과가 정리되면서 타이머가 취소되므로, 지우기는 타이머 안에서 한다.
  const autoStartDemo = searchParams.get(DEMO_START_PARAM) === DEMO_START_VALUE;
  useEffect(() => {
    if (!ticker || !autoStartDemo) return;
    const t = setTimeout(() => {
      setSearchParams({ ticker }, { replace: true });
      void runDemo(restartDemo);
    }, 800);
    return () => clearTimeout(t);
    // runDemo · restartDemo 는 렌더마다 새로 만들어지지만 이 효과는 진입 때 한 번만 돈다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, autoStartDemo]);

  // ticker 없으면 종목 화면으로 — 모든 hooks 이후에 체크
  if (!ticker) return <Navigate to="/stocks" replace />;

  /**
   * 시연 재생 시작 (Contract 7.8).
   *
   * 백엔드가 스크립트를 실제 인입 경로로 흘려보내므로, 이 화면은 평소와 똑같이
   * STOMP 로 받기만 하면 된다. 이전 회차의 대조 · 판단이 남아 있으면 혼동되므로 먼저 비운다.
   */
  async function startDemo() {
    if (!ticker) return;
    const result = (await ipc.invoke(IPC_CHANNELS.DEMO_EARNINGS_START, { ticker })) as
      | { ok: true; segmentCount: number; evidenceWarning?: string }
      | { ok: false; reason: string; message: string };
    if (result.ok) {
      if (result.evidenceWarning) {
        showIpcErrorToast(new Error(result.evidenceWarning));
      }
      // 지난 회차 자막은 새 재생이 실제로 시작된 뒤에 비운다. 시작이 실패했는데 자막만 사라지면
      // 빈 자막 옆에 지난 판단이 남는다.
      useTranscriptStore.getState().clearTicker(ticker);
      setStoppedCallId(null);
      clearFactCheck(ticker);
      clearTranscriptDiff(ticker);
      // 이전 회차의 종합 판단이 남아 있으면 새 어닝콜이 시작됐는데도 지난 결론이 계속 떠 있게 된다.
      clearEarningsSummary(ticker);
      // 세션 시작 응답이 늦게 와도 시연 표시가 꺼지지 않게, 세션 종목을 먼저 맞춘 뒤 표시를 켠다.
      setSession(true, ticker);
      setDemo(true);
      return;
    }
    // showIpcErrorToast 는 Error 를 기대한다 — 문자열을 그대로 넘기지 않는다.
    showIpcErrorToast(
      new Error(
        result.reason === "ALREADY_RUNNING"
          ? "이미 시연이 진행 중입니다. 잠시 후 다시 시도하세요."
          : result.message,
      ),
    );
  }

  async function runDemo(action: () => Promise<void>) {
    if (demoBusy) return;
    setDemoBusy(true);
    try {
      await action();
    } catch (e) {
      showIpcErrorToast(e);
    } finally {
      setDemoBusy(false);
    }
  }

  async function stopDemo() {
    if (!ticker) return;
    const stopped = await ipc.invoke<boolean>(IPC_CHANNELS.DEMO_EARNINGS_STOP, { ticker });
    // 중지하면 종료 표시가 오지 않아 LIVE 로 남는다. 이 화면에서 끝난 콜로 다룬다.
    if (stopped && lastCallId) setStoppedCallId(lastCallId);
  }

  /** 처음부터 — 재생을 멈추고 다시 시작한다. 지난 회차 자막은 시작이 성공한 뒤에 비운다. */
  async function restartDemo() {
    if (!ticker) return;
    await ipc.invoke(IPC_CHANNELS.DEMO_EARNINGS_STOP, { ticker }).catch(() => undefined);
    await startDemo();
  }

  async function handleOrderSubmit(payload: OrderSubmitPayload) {
    if (!ticker) return;
    setSubmitting(true);
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
      setSubmitting(false);
    }
  }

  function addSessionOrder(order: SessionOrder) {
    // 최근 것이 앞에 온다. 세션 한정이라 상한은 넉넉히 둔다.
    setSessionOrders((prev) => [order, ...prev].slice(0, 30));
  }

  const priceCard = (
    <PriceCard
      currentPrice={currentPrice}
      changeAmount={changeAmount}
      changePercent={changePercent}
      series={chartSeries}
      holding={holding}
      balanceLoaded={balanceLoaded}
    />
  );

  return (
    <div className="relative h-[calc(100%+3rem)] -m-6 p-3">
      {/* 콜 바 — 내용 위에 떠 있고, 각 면은 위쪽을 비워 두어 내용이 이 아래로 지나간다 */}
      <div className="absolute top-3 left-3 right-3 z-20">
        <CallBar
          ticker={ticker}
          companyName={companyName}
          phase={phase}
          isDemo={isDemo}
          elapsedLabel={elapsedLabel}
          previousCallLabel={previousCallLabel}
          speakerCount={speakerProfiles.length}
          onSpeakers={speakerProfiles.length > 0 ? openSpeakerRoster : undefined}
          onCompanyInfo={() => openDrawer(ticker)}
          onOrder={() => setOrderOpen((v) => !v)}
          orderOpen={orderOpen}
          demo={{
            busy: demoBusy,
            onStop: () => void runDemo(stopDemo),
            onRestart: () => void runDemo(restartDemo),
          }}
        />
      </div>

      <div
        className="grid h-full gap-3 transition-[grid-template-columns] duration-500"
        style={{ gridTemplateColumns: COLUMNS[phase] }}
      >
        {phase === "BEFORE" && (
          <>
            <CallBriefing
              detail={companyDetail}
              loading={companyLoading}
              error={companyError}
              topInset={TOP_INSET}
            />
            <aside
              className="frost h-full rounded-[28px] overflow-y-auto px-6 pb-6"
              style={{ paddingTop: TOP_INSET + 16 }}
              aria-label="가격과 내 포지션"
            >
              {priceCard}
            </aside>
          </>
        )}

        {phase === "LIVE" && (
          <>
            <TranscriptStream
              segments={segments}
              diffsBySequence={diffsBySequence}
              isLive
              topInset={TOP_INSET}
              focus={focus}
              onSpeakerClick={speakerProfiles.length > 0 ? openSpeakerProfile : undefined}
            />
            <CallSideTabs
              diffItems={transcriptDiffItems}
              onFocusSequence={(sequence) => setFocus({ sequence, nonce: Date.now() })}
              price={priceCard}
              topInset={TOP_INSET}
            />
          </>
        )}

        {phase === "ENDED" && (
          <>
            <TranscriptStream
              segments={segments}
              diffsBySequence={diffsBySequence}
              isLive={false}
              compact
              topInset={TOP_INSET}
              onSpeakerClick={speakerProfiles.length > 0 ? openSpeakerProfile : undefined}
            />
            <CallVerdict
              summary={currentSummary}
              demoStopped={stoppedCallId != null && stoppedCallId === lastCallId}
              diffCounts={diffCounts}
              previousCallLabel={previousCallLabel}
              onOpenTicker={(t) => openDrawer(t)}
              topInset={TOP_INSET}
            />
          </>
        )}
      </div>

      <OrderSheet
        open={orderOpen}
        onClose={() => setOrderOpen(false)}
        ticker={ticker}
        currentPrice={currentPrice}
        orderableCash={orderableCash}
        heldQty={balanceLoaded ? holding?.qty ?? 0 : null}
        account={orderAccount}
        hasKey={hasKey}
        onOpenSettings={() =>
          navigate(`/settings?kis=${orderAccount === "KIS_REAL" ? "real" : "paper"}`)
        }
        onSubmit={handleOrderSubmit}
        submitting={submitting}
        orders={sessionOrders}
        onRefreshOrders={() => void handleRefreshOrders()}
        refreshingOrders={refreshingOrders}
        topInset={TOP_INSET}
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
