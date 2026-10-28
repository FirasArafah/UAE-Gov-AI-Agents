import json


def sse_event(event_type: str, data: dict) -> dict:
    return {
        "event": event_type,
        "data": json.dumps(data, ensure_ascii=False),
    }
