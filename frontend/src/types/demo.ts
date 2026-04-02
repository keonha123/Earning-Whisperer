export interface DemoSignalMessage {
  ticker: string;
  text_chunk: string;
  raw_score: number;
  ema_score: number;
  rationale: string;
  action: "BUY" | "SELL" | "HOLD";
  timestamp: number;
  is_session_end: boolean;
}

export interface DemoPriceMessage {
  ticker: string;
  price: number;
  change: number;
  change_percent: number;
  timestamp: number;
}

export interface SignalEntry {
  action: "BUY" | "SELL" | "HOLD";
  emaScore: number;
  rationale: string;
  timestamp: number;
}

export interface EmaDataPoint {
  time: number;
  ema: number;
  raw: number;
}
