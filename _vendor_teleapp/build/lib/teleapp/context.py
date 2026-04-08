from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class PhotoInput:
    file_id: str
    file_unique_id: str
    width: int
    height: int


@dataclass(slots=True)
class AnimationInput:
    file_id: str
    file_unique_id: str
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    file_name: str | None = None
    mime_type: str | None = None


@dataclass(slots=True)
class DocumentInput:
    file_id: str
    file_unique_id: str
    file_name: str | None = None
    mime_type: str | None = None


@dataclass(slots=True)
class StickerInput:
    file_id: str
    file_unique_id: str
    emoji: str | None = None
    set_name: str | None = None


@dataclass(slots=True)
class LocationInput:
    latitude: float
    longitude: float


@dataclass(slots=True)
class VenueInput:
    latitude: float
    longitude: float
    title: str
    address: str


@dataclass(slots=True)
class AudioInput:
    file_id: str
    file_unique_id: str
    duration: int | None = None
    file_name: str | None = None
    mime_type: str | None = None


@dataclass(slots=True)
class VoiceInput:
    file_id: str
    file_unique_id: str
    duration: int | None = None
    mime_type: str | None = None


@dataclass(slots=True)
class VideoInput:
    file_id: str
    file_unique_id: str
    width: int | None = None
    height: int | None = None
    duration: int | None = None


@dataclass(slots=True)
class ContactInput:
    phone_number: str
    first_name: str
    last_name: str | None = None
    user_id: int | None = None


@dataclass(slots=True)
class PollInput:
    question: str
    options: list[str]
    allows_multiple_answers: bool = False


@dataclass(slots=True)
class CallbackQueryInput:
    id: str
    data: str | None = None


@dataclass(slots=True)
class MessageContext:
    chat_id: int
    text: str
    request_id: str | None = None
    command: str | None = None
    caption: str | None = None
    animation: AnimationInput | None = None
    photos: list[PhotoInput] | None = None
    document: DocumentInput | None = None
    sticker: StickerInput | None = None
    location: LocationInput | None = None
    venue: VenueInput | None = None
    audio: AudioInput | None = None
    voice: VoiceInput | None = None
    video: VideoInput | None = None
    contact: ContactInput | None = None
    poll: PollInput | None = None
    callback_query: CallbackQueryInput | None = None
    raw_update: Any = None
