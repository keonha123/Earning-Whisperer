import subprocess
import numpy as np
from faster_whisper import WhisperModel
import sys
import time
import requests

# =====================================================================
# [설정 및 Contract 1 규격 정보]
# =====================================================================
TICKER = "FAST"
input_device = "alsa_output.usb-Lenovo_Lenovo_Wireless_VoIP_Headset-Receiver_20230912.1-00.analog-stereo.monitor"
AI_ENGINE_URL = "http://localhost:8000/api/v1/analyze" 

sequence_counter = 0

# =====================================================================
# [엔진 가동] Whisper 모델 로드
# =====================================================================
print(f"📦 [{TICKER}] 타임스탬프 정밀 동기화형 STT 엔진 가동 준비 중...")
model = WhisperModel("distil-large-v3", device="cpu", compute_type="int8", cpu_threads=16)

command = [
    'ffmpeg', '-f', 'pulse', '-i', input_device,
    '-ac', '1', '-ar', '16000', '-f', 's16le', 'pipe:1'
]
process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

print(f"\n🔥 'Earning Whisperer' 무손실 오디오 슬라이싱 모드 가동: {TICKER}")
print("="*60)

try:
    audio_buffer = np.array([], dtype=np.float32)

    while True:
        raw_audio = process.stdout.read(64000) # 2초 분량 소리 수집
        if not raw_audio: 
            break

        audio_chunk = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0
        audio_buffer = np.append(audio_buffer, audio_chunk)

        accumulated_seconds = len(audio_buffer) / 16000

        # Whisper 추론 가동
        segments, _ = model.transcribe(audio_buffer, beam_size=1, language="en", vad_filter=True)

        # 실시간 연산을 위해 세그먼트들을 리스트로 즉시 확보
        segment_list = list(segments)

        full_text = " ".join([s.text.strip() for s in segment_list]).strip()
        sys.stdout.write(f"\r\033[K[실시간 문맥 교정 중] {full_text}")
        sys.stdout.flush()

        # 🔍 [하드웨어 레벨 정밀 분석 알고리즘]
        # 현재 생성된 Whisper 세그먼트 중, 진짜 문장 마침표(. ! ?)로 끝난 가장 마지막 세그먼트의 위치를 찾습니다.
        last_completed_idx = -1
        for i, seg in enumerate(segment_list):
            txt = seg.text.strip()
            if txt and txt[-1] in ['.', '?', '!']:
                last_completed_idx = i

        # 🎯 [타임스탬프 트리거 적용]
        # 최소 10초가 지났고 완결된 문장 블록이 있거나, 혹은 20초 하드캡에 걸렸을 때만 발송
        if (accumulated_seconds >= 10.0 and last_completed_idx != -1) or (accumulated_seconds >= 20.0):
            
            if last_completed_idx != -1:
                # 1. 완성된 문장 세그먼트들만 쏙 골라내서 텍스트 병합
                completed_segments = segment_list[:last_completed_idx + 1]
                chunk_to_send = " ".join([s.text.strip() for s in completed_segments]).strip()
                
                # 2. ✂️ 핵심: 진짜 문장이 완전히 종료된 소리의 '정확한 타임스탬프(초)'를 추출!
                slice_timestamp = segment_list[last_completed_idx].end
                
                # 3. 오디오 버퍼 슬라이싱: 보낸 문장의 소리만 파형에서 잘라내고, 
                # 경계선에 걸쳐서 들려오던 다음 단어 소리는 1밀리초도 다치지 않게 버퍼에 고이 남겨둠!
                samples_to_drop = int(slice_timestamp * 16000)
                audio_buffer = audio_buffer[samples_to_drop:]
                
            else:
                # 20초가 지났는데도 마침표가 전혀 없는 특이 케이스는 전체 강제 발송 및 완전 리셋
                chunk_to_send = full_text
                audio_buffer = np.array([], dtype=np.float32)

            if chunk_to_send:
                # [Contract 1] 규격 패킷 발송
                contract_payload = {
                    "ticker": TICKER,
                    "text_chunk": chunk_to_send,
                    "sequence": sequence_counter,
                    "timestamp": int(time.time()),
                    "is_final": False
                }

                print("\n\n" + "✨"*5 + f" [무손실 오디오 마감 전송 # {sequence_counter}] " + "✨"*5)
                print(f"💬 본문: {contract_payload['text_chunk']}")
                
                try:
                    response = requests.post(AI_ENGINE_URL, json=contract_payload, timeout=2)
                    if response.status_code == 200:
                        print(f"📡 [AI Engine] 전송 승인 완료 -> {response.json()}")
                except Exception as e:
                    print(f"❌ [통신 실패] {e}")
                    
                print("-" * 60 + "\n")
                sequence_counter += 1

except KeyboardInterrupt:
    print("\n\n종료 시그널 감지. 최종 잔여 데이터 전송 중...")
    try:
        if len(audio_buffer) > 0:
            segments, _ = model.transcribe(audio_buffer, beam_size=1, language="en", vad_filter=True)
            final_text = " ".join([s.text.strip() for s in segments]).strip()
            if final_text:
                final_payload = {
                    "ticker": TICKER,
                    "text_chunk": final_text,
                    "sequence": sequence_counter,
                    "timestamp": int(time.time()),
                    "is_final": True
                }
                requests.post(AI_ENGINE_URL, json=final_payload, timeout=2)
        print("🏁 파이프라인 안전 종료 완료.")
    except:
        pass
    
finally:
    process.terminate()