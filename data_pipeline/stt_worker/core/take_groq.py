import subprocess
import sys
import time
import requests
import io
import wave
from groq import Groq  # 🔥 Groq 공식 라이브러리 도입

# =====================================================================
# [설정 및 Contract 1 규격 정보]
# =====================================================================
TICKER = "FAST"
input_device = "alsa_output.usb-Lenovo_Lenovo_Wireless_VoIP_Headset-Receiver_20230912.1-00.analog-stereo.monitor"
AI_ENGINE_URL = "http://localhost:8000/api/v1/analyze" 

# 🔥 [Groq API 키 설정] 발급받으신 실전 키를 입력하세요.
GROQ_API_KEY = "gsk_yO..." 

sequence_counter = 0

# =====================================================================
# [인프라 가동] Groq 클라이언트 및 오디오 시스템 초기화
# =====================================================================
print(f"📦 [{TICKER}] 초고속 클라우드 Groq API 모드 전환 중...")
groq_client = Groq(api_key=GROQ_API_KEY)

# FFmpeg 구동 (16000Hz, 16비트 단일 채널 단자 수집)
command = [
    'ffmpeg', '-f', 'pulse', '-i', input_device,
    '-ac', '1', '-ar', '16000', '-f', 's16le', 'pipe:1'
]
process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

print(f"\n🚀 'Earning Whisperer' Groq 클라우드 뇌세포 동기화 완료: {TICKER}")
print("="*60)

# 💡 생 바이트 데이터를 인메모리 가상 WAV 파일로 변환하는 초고속 함수
def build_in_memory_wav(raw_bytes_data):
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wf:
        wf.setnchannels(1)      # 모노
        wf.setsampwidth(2)     # 16비트 (2바이트)
        wf.setframerate(16000)  # 16kHz
        wf.writeframes(raw_bytes_data)
    wav_buffer.seek(0)
    return wav_buffer

try:
    # 텍스트와 Numpy를 전부 걷어내고, 오직 "생 오디오 바이트"만 저장합니다.
    audio_bytes_buffer = b""

    while True:
        # 2초 분량 데이터 획득 (16000Hz * 2바이트 = 1초당 32,000바이트 ➔ 2초면 64,000바이트)
        raw_audio_chunk = process.stdout.read(64000) 
        if not raw_audio_chunk: 
            break

        audio_bytes_buffer += raw_audio_chunk
        
        # 현재 누적 바이트를 시간(초) 단위로 환산
        accumulated_seconds = len(audio_bytes_buffer) / 32000

        # 최소 10초 분량의 소리가 모일 때까지는 서버를 깨우지 않고 묵묵히 모읍니다.
        if accumulated_seconds < 10.0:
            sys.stdout.write(f"\r\033[K[클라우드 전송 대기 중] 오디오 자바라 수집 중... ({accumulated_seconds:.1f}초)")
            sys.stdout.flush()
            continue

        # 🎯 10초가 넘었다면? 메모리 안에서 가상 WAV 파일로 0.001초 만에 포장!
        virtual_wav_file = build_in_memory_wav(audio_bytes_buffer)

        try:
            sys.stdout.write(f"\r\033[K⚡ [Groq LPU Engine] 세계 최고속 인프라 추론 요청 중...")
            sys.stdout.flush()

            # 🧠 Groq 클라우드 서버의 Whisper Large-v3 뇌세포에 전송
            # verbose_json 옵션을 줘야 타임스탬프 세그먼트가 넘어옵니다.
            api_response = groq_client.audio.transcriptions.create(
                file=("earning_clip.wav", virtual_wav_file.read()),
                model="whisper-large-v3",
                language="en",
                response_format="verbose_json"
            )

            # API 결과물에서 세그먼트 추출
            segments = getattr(api_response, 'segments', [])
            if not segments:
                continue

            full_text = getattr(api_response, 'text', '').strip()

            # 🔍 [타임스탬프 기반 정밀 오디오 슬라이싱 레이어]
            last_completed_idx = -1
            for i, seg in enumerate(segments):
                txt = seg.get('text', '').strip()
                if txt and txt[-1] in ['.', '?', '!']:
                    last_completed_idx = i

            # 문장 마감 기호가 발견되었거나, 혹은 숨 안 쉬고 말해서 20초 장벽을 넘었을 때 발송 조건 충족!
            if last_completed_idx != -1 or accumulated_seconds >= 20.0:
                
                if last_completed_idx != -1:
                    # 진짜 마침표로 끝난 문장 블록들만 추출해서 병합
                    completed_segments = segments[:last_completed_idx + 1]
                    chunk_to_send = " ".join([s.get('text', '').strip() for s in completed_segments]).strip()
                    
                    # ✂️ 진짜 문장이 완결된 정확한 지점의 시간(초) 확보
                    slice_timestamp = completed_segments[-1].get('end', accumulated_seconds)
                    
                    # 오디오 바이트 버퍼 정밀 컷팅 (1초 = 32000 바이트)
                    bytes_to_drop = int(slice_timestamp * 32000)
                    audio_bytes_buffer = audio_bytes_buffer[bytes_to_drop:]
                else:
                    # 20초 하드캡 예외 상황 처리
                    chunk_to_send = full_text
                    audio_bytes_buffer = b""

                if chunk_to_send:
                    # [Contract 1] 규격 상자에 포장
                    contract_payload = {
                        "ticker": TICKER,
                        "text_chunk": chunk_to_send,
                        "sequence": sequence_counter,
                        "timestamp": int(time.time()),
                        "is_final": False
                    }

                    print("\n\n" + "🚀"*5 + f" [Groq 클라우드 완결 문장 전송 # {sequence_counter}] " + "🚀"*5)
                    print(f"💬 본문: {contract_payload['text_chunk']}")
                    
                    # 로컬 FastAPI 서버(`server_ai.py`) 뒷단으로 격격 슛팅!
                    try:
                        response = requests.post(AI_ENGINE_URL, json=contract_payload, timeout=2)
                        if response.status_code == 200:
                            print(f"📡 [FastAPI 기지국] 수신 동기화 완료 -> {response.json()}")
                    except Exception as e:
                        print(f"❌ [기지국 통신 실패] {e}")
                        
                    print("-" * 60 + "\n")
                    sequence_counter += 1

        except Exception as e:
            print(f"\n⚠️ [Groq API 통신 장애 발생] 다시 시도합니다: {e}")
            time.sleep(1)

except KeyboardInterrupt:
    print("\n\n종료 시그널 감지. 파이프라인 정지 처리 중...")
finally:
    process.terminate()