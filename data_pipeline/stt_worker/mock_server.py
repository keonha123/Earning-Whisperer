from fastapi import FastAPI, Request
import uvicorn

app = FastAPI()

@app.post("/api/v1/analyze")
async def receive_data(request: Request):
    # 전송받은 JSON 데이터를 읽어서 출력합니다.
    data = await request.json()
    print(f"\n📥 [데이터 수신] Ticker: {data['ticker']} | Seq: {data['sequence']}")
    print(f"📝 내용: {data['text_chunk'][:100]}...") # 너무 기니까 앞부분만 출력
    return {"status": "success", "message": "Data received"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)