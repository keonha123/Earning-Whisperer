import json

import pytest

from tools.reindex_transcripts import main


def test_reindex_preview_does_not_write_and_apply_rejects_existing_collection(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"items": [{"provider_id": "test", "ticker": "WMT", "title": "Transcript",
        "content": "We reiterated full year guidance."}]}), encoding="utf-8")
    destination = tmp_path / "new-local-store"
    args = ["--input", str(source), "--path", str(destination), "--collection", "transcript_v2",
        "--provider", "hash", "--model", "hash-local", "--dimension", "64", "--version", "hash-v2"]
    summary = main(args)
    assert summary["chunks"] == 1
    assert not destination.exists()
    applied = main([*args, "--apply"])
    assert applied["verified_chunks"] == 1
    with pytest.raises(ValueError, match="Destination collection exists"):
        main([*args, "--apply"])
