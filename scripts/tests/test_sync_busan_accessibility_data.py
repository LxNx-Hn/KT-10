import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "sync_busan_accessibility_data.py"
SPEC = importlib.util.spec_from_file_location("accessibility_sync", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


def test_resolve_decoding_key_prefers_deco_and_rejects_encoded_only_key(monkeypatch):
    monkeypatch.delenv("DECO", raising=False)
    monkeypatch.delenv("DATA_GO_KR_SERVICE_KEY", raising=False)

    assert sync.resolve_decoding_key({"DECO": "decoded-key"}) == "decoded-key"

    try:
        sync.resolve_decoding_key({"DATA_GO_KR_SERVICE_KEY": "a%2Bb"})
    except RuntimeError as exc:
        assert "Decoding" in str(exc)
    else:
        raise AssertionError("encoded key must be rejected")


def test_fetch_tourism_accessibility_paginates_and_validates_total(monkeypatch):
    calls = []

    def fake_request(url):
        calls.append(url)
        page = 1 if "pageNo=1" in url else 2
        items = [{"subject": "one"}] if page == 1 else [{"subject": "two"}]
        return {"response": {"header": {"resultCode": "00"}, "body": {
            "totalCount": 2,
            "items": {"item": items},
        }}}

    monkeypatch.setattr(sync, "_request_json", fake_request)

    assert sync.fetch_tourism_accessibility("decoded-key", page_size=1) == [
        {"subject": "one"},
        {"subject": "two"},
    ]
    assert len(calls) == 2
