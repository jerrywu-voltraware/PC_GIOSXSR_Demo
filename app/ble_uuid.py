"""Match Flutter's short UUID representation against WinRT's expanded UUIDs."""
from .constants import TARGET_SERVICE_UUID_SUFFIXES


def mobile_uuid(value: str) -> str:
    uuid = str(value).strip().lower()
    base_tail = "-0000-1000-8000-00805f9b34fb"
    if len(uuid) == 36 and uuid.endswith(base_tail):
        head = uuid[:8]
        if all(c in "0123456789abcdef" for c in head):
            return head[4:] if head.startswith("0000") else head
    if len(uuid) == 8 and uuid.startswith("0000"):
        return uuid[4:]
    return uuid


def is_pru_service(value: str) -> bool:
    return mobile_uuid(value).endswith(TARGET_SERVICE_UUID_SUFFIXES)
