# Local STT performance benchmark

Run on the machine and model configuration being evaluated. Use a local recording
with representative English speech; three minutes is useful for a first check,
while a longer sample is needed to observe sustained backlog.

```bash
python -m data_pipeline.tools.debug.benchmark_stt \
  --audio-file /results/earnings-sample.wav \
  --model /models/distil-large-v3 \
  --device cpu --compute-type int8 --cpu-threads 8 \
  --duration-seconds 180 \
  --output /results/stt-performance.json
```

The model directory must already contain a converted faster-whisper model.
Alternatively, `--model distil-large-v3 --model-cache-dir /models` resolves a
previously populated Hugging Face cache. This tool enforces offline model loading;
it does not download missing files. A missing model produces an error report.
`--duration-seconds 0` processes the complete input file. Processing includes
draining the inference backlog after the file finishes playing.

The benchmark runs the production worker's audio reader, overlap windows,
recognition, and counters. FFmpeg's `-re` sends the file at playback speed while
the model loads. The benchmark substitutes a local in-memory transcript sink and
does not send transcripts to the database, backend, or AI engine. Its final JSON
contains transcript counts, not recognized speech. `production_delivery_exercised`
is always false, including when `worker_exit_code` is zero.

Read these values together:

| Field | Meaning |
| --- | --- |
| `model_load_seconds` | Cold model initialization time, while input is being queued |
| `realtime_factor` | Inference time divided by new input audio duration; overlap is excluded from the denominator |
| `maximum_pending_audio_seconds` | Largest observed pending input duration |
| `dropped_bytes` | Actual input bytes dropped by the worker's bounded queue |
| `first_text_seconds` | Time from worker start to its first nonempty recognition |
| `worker_exit_code` | Whether this benchmark's worker completed successfully |
| `transcript_segments`, `transcript_characters` | Local sink counts; no transcript text is retained in the report |

An average factor below 1 is necessary for keeping up with the input under these
conditions. It does not prove accuracy, bounded latency for an entire live call,
browser capture reliability, or capacity on a different AWS instance. Check
backlog and drops, retain the CPU/memory limit fields, and use the same audio when
comparing models or machines. Run benchmarks separately so they do not compete for
the same CPU. The default model is `distil-large-v3`; a tiny-model check validates
the measurement path but does not establish the production model's performance.
