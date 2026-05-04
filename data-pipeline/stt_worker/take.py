import subprocess
import numpy as np
from faster_whisper import WhisperModel
import sys
import time
import json  # 출력을 위해 추가

# [설정] Contract 1 규격 정보
TICKER = "FAST"
input_device = "alsa_output.usb-Lenovo_Lenovo_Wireless_VoIP_Headset-Receiver_20230912.1-00.analog-stereo.monitor"

# [상태 관리] 시퀀스 번호
sequence_counter = 0

# 모델 로드 (본방 직전이니 절대 끄지 마세요!)
print(f"📦 [{TICKER}] 실시간 로컬 분석 모드 준비 중...")
model = WhisperModel("distil-large-v3", device="cpu", compute_type="int8", cpu_threads=16)

# 오디오 캡처 (FFmpeg)
command = [
    'ffmpeg', '-f', 'pulse', '-i', input_device,
    '-ac', '1', '-ar', '16000', '-f', 's16le', 'pipe:1'
]
process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

print(f"\n🔥 'Earning Whisperer' 본방 모드 가동: {TICKER}")
print("="*60)

try:
    accumulated_text = ""
    chunk_count = 0

    while True:
        raw_audio = process.stdout.read(64000) # 2초 분량
        if not raw_audio: break

        audio_data = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = model.transcribe(audio_data, beam_size=1, language="en", vad_filter=True)

        for segment in segments:
            text = segment.text.strip()
            if text:
                accumulated_text += " " + text
                # 실시간으로 글자가 뽑히는 건 계속 보여줍니다.
                sys.stdout.write(f"\r[분석 중] {text}")
                sys.stdout.flush()

        chunk_count += 1

        # 약 10초(5번)가 쌓이면 API 규격에 맞춰 터미널에 출력
        if chunk_count >= 5:
            if accumulated_text.strip():
                # [Contract 1] 규격 데이터 생성
                contract_payload = {
                    "ticker": TICKER,
                    "text_chunk": accumulated_text.strip(),
                    "sequence": sequence_counter,
                    "timestamp": int(time.time()),
                    "is_final": False
                }

                # --- 서버 전송 대신 터미널에 JSON 형태로 출력 ---
                print("\n\n" + "-"*20 + " [SEND MOCKUP] " + "-"*20)
                print(json.dumps(contract_payload, indent=4, ensure_ascii=False))
                print("-" * 55 + "\n")

                sequence_counter += 1
                accumulated_text = ""
                chunk_count = 0

except KeyboardInterrupt:
    print("\n\n✅ 어닝 콜 기록이 안전하게 종료되었습니다.")
finally:
    process.terminate()