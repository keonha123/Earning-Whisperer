# server_ai.py (옆 컴퓨터 전용)
import asyncio
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel

app = FastAPI(title="CallStrike-AI-Engine", version="2026.5")

class EarningsAnalyzeRequest(BaseModel):
    ticker: str
    text_chunk: str
    sequence: int
    timestamp: int
    is_final: bool

async def process_llm_analysis(payload: EarningsAnalyzeRequest):
    print(f"\n🧠 [AI Engine - LLM] '{payload.ticker}' 분석 가동 (Seq: {payload.sequence})")
    print(f"📝 분석할 텍스트: {payload.text_chunk}")
    
    if payload.is_final:
        print(f"🏁 [{payload.ticker}] 어닝콜 세션 종료. 최종 리포트 생성.")

@app.post("/api/v1/analyze")
async def analyze_earnings_stream(payload: EarningsAnalyzeRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(process_llm_analysis, payload)
    return {
        "status": "ACK",
        "received_sequence": payload.sequence,
        "ticker": payload.ticker
    }

if __name__ == "__main__":
    import uvicorn
    # 0.0.0.0 가동으로 와이파이 망 내 외부 접속 허용
    uvicorn.run(app, host="0.0.0.0", port=8000)