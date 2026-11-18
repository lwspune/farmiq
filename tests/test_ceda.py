import json

from farmiq_data.ceda import CedaClient, fetch_series


class FakeTransport:
    def __init__(self):
        self.calls = []

    def __call__(self, method, path, body):
        self.calls.append((method, path, body))
        if path == "/agmarknet/prices":
            return {"output": {"type": "success", "data": [{"date": "2020-01-01T00:00:00.000Z", "market_id": 1}]}}
        if path == "/agmarknet/quantities":
            return {"output": {"type": "success", "data": [{"date": "2020-01-01T00:00:00.000Z", "market_id": 1}]}}
        return {"output": {"type": "error", "message": "No data", "data": []}}


def test_client_unwraps_output_data():
    t = FakeTransport()
    client = CedaClient(transport=t, pause_seconds=0)
    rows = client.prices(commodity_id=78, state_id=27, district_ids=[522], from_date="2003-01-01", to_date="2025-12-31")
    assert rows == [{"date": "2020-01-01T00:00:00.000Z", "market_id": 1}]
    method, path, body = t.calls[0]
    assert (method, path) == ("POST", "/agmarknet/prices")
    assert body == {"commodity_id": 78, "state_id": 27, "district_id": [522],
                    "from_date": "2003-01-01", "to_date": "2025-12-31"}


def test_client_treats_no_data_as_empty_not_error():
    client = CedaClient(transport=FakeTransport(), pause_seconds=0)
    assert client._call("POST", "/agmarknet/other", {}) == []


def test_fetch_series_saves_raw_json_and_skips_existing(tmp_path):
    t = FakeTransport()
    client = CedaClient(transport=t, pause_seconds=0)
    out = fetch_series(client, tmp_path, "prices", commodity_id=78, district_id=522,
                       from_date="2003-01-01", to_date="2025-12-31")
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["rows"] == [{"date": "2020-01-01T00:00:00.000Z", "market_id": 1}]
    assert saved["request"]["district_id"] == [522]
    assert "fetched_at" in saved

    fetch_series(client, tmp_path, "prices", commodity_id=78, district_id=522,
                 from_date="2003-01-01", to_date="2025-12-31")
    assert len(t.calls) == 1  # second run reuses the saved file
