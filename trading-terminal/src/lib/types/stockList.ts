export interface Sp500Stock {
  ticker: string
  companyName: string
  sector: string | null
  marketCapUsd: number | null
  currentPrice: number | null
  changePercent: number | null
}

export interface StockPriceEntry {
  ticker: string
  currentPrice: number
  previousClose: number
  changePercent: number
  updatedAt: number
}
