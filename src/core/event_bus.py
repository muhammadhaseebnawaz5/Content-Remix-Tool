"""
EventBus - Singleton publish-subscribe messaging system.
No module talks directly to another; all communication goes through EventBus.
"""

from typing import Callable, Dict, List, Any
from PySide6.QtCore import QObject, Signal


class EventBus(QObject):
    """Singleton EventBus for decoupled module communication."""

    # Processing events
    PROCESSING_STARTED = "processing_started"
    PROCESSING_PROGRESS = "processing_progress"
    PROCESSING_COMPLETED = "processing_completed"
    PROCESSING_PAUSED = "processing_paused"
    PROCESSING_RESUMED = "processing_resumed"
    PROCESSING_CANCELLED = "processing_cancelled"

    # Single video lifecycle
    VIDEO_QUEUED = "video_queued"
    VIDEO_STARTED = "video_started"
    VIDEO_COMPLETED = "video_completed"
    VIDEO_FAILED = "video_failed"

    # Project events
    PROJECT_LOADED = "project_loaded"
    PROJECT_SAVED = "project_saved"
    PROJECT_MODIFIED = "project_modified"
    PROJECT_CREATED = "project_created"

    # AI events
    AI_INFERENCE_STARTED = "ai_inference_started"
    AI_INFERENCE_COMPLETED = "ai_inference_completed"

    # UI events
    UI_THEME_CHANGED = "ui_theme_changed"
    UI_NOTIFICATION = "ui_notification"

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        super().__init__()
        self._subscribers: Dict[str, List[Callable]] = {}
        self._initialized = True

    def subscribe(self, event: str, callback: Callable) -> None:
        """Subscribe a callback to an event."""
        if event not in self._subscribers:
            self._subscribers[event] = []
        self._subscribers[event].append(callback)

    def unsubscribe(self, event: str, callback: Callable) -> None:
        """Unsubscribe a callback from an event."""
        if event in self._subscribers and callback in self._subscribers[event]:
            self._subscribers[event].remove(callback)

    def emit(self, event: str, data: Any = None) -> None:
        """Emit an event with optional data to all subscribers."""
        if event in self._subscribers:
            for callback in self._subscribers[event]:
                try:
                    if data is not None:
                        callback(data)
                    else:
                        callback()
                except Exception as e:
                    print(f"EventBus error handling {event}: {e}")

    def clear(self) -> None:
        """Clear all subscribers."""
        self._subscribers.clear()


# Global accessor
def get_event_bus() -> EventBus:
    return EventBus()
