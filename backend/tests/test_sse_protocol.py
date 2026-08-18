import json

from app.api.chat import SSEEventEncoder, _append_sse_record, _get_replay_events


def parse_sse_frame(frame: str) -> dict:
    result = {"data": {}}
    for line in frame.strip().splitlines():
        if line.startswith("id:"):
            result["id"] = line[3:].strip()
        elif line.startswith("event:"):
            result["event"] = line[6:].strip()
        elif line.startswith("data:"):
            result["data"] = json.loads(line[5:].strip())
    return result


def test_sse_encoder_adds_stable_ids_and_contiguous_sequences():
    stored = []
    encoder = SSEEventEncoder("stream-a", request_message_id=42, persist=stored.append)

    first = parse_sse_frame(encoder.encode("status", {"message": "处理中"}))
    second = parse_sse_frame(encoder.encode("done", {"status": "completed"}))

    assert first["id"] == "stream-a:1"
    assert first["data"]["sequence"] == 1
    assert first["data"]["request_message_id"] == 42
    assert second["id"] == "stream-a:2"
    assert second["data"]["sequence"] == 2
    assert [item["id"] for item in stored] == ["stream-a:1", "stream-a:2"]


def test_replay_returns_only_events_after_contiguous_sequence():
    context = {
        "sse_streams": {
            "stream-a": {
                "events": [
                    {"id": "stream-a:1", "event": "status", "sequence": 1, "data": {}},
                    {"id": "stream-a:2", "event": "message", "sequence": 2, "data": {}},
                    {"id": "stream-a:3", "event": "done", "sequence": 3, "data": {}},
                ]
            }
        }
    }

    replay = _get_replay_events(context, "stream-a", after_sequence=1)

    assert [item["sequence"] for item in replay] == [2, 3]


def test_persistence_limits_stream_count_and_event_count():
    context = {}

    for stream_number in range(4):
        stream_id = f"stream-{stream_number}"
        for sequence in range(1, 103):
            context = _append_sse_record(context, {
                "id": f"{stream_id}:{sequence}",
                "event": "message",
                "sequence": sequence,
                "data": {"stream_id": stream_id, "sequence": sequence},
            })

    streams = context["sse_streams"]
    assert list(streams) == ["stream-1", "stream-2", "stream-3"]
    assert len(streams["stream-3"]["events"]) == 100
    assert streams["stream-3"]["events"][0]["sequence"] == 3
