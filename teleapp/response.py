from __future__ import annotations

from dataclasses import dataclass

from teleapp.context import MessageContext
from teleapp.protocol import AppEvent


@dataclass(slots=True)
class Response:
    text: str
    event_type: str = "output"

    def to_event(self, ctx: MessageContext) -> AppEvent:
        return AppEvent(
            type=self.event_type,
            text=self.text,
            chat_id=ctx.chat_id,
            request_id=ctx.request_id,
            stream="inprocess",
        )


@dataclass(slots=True)
class TextResponse(Response):
    event_type: str = "output"


@dataclass(slots=True)
class StatusResponse(Response):
    event_type: str = "status"


@dataclass(slots=True)
class ErrorResponse(Response):
    event_type: str = "error"


@dataclass(slots=True)
class PhotoResponse(Response):
    file_path: str | None = None
    file_id: str | None = None
    caption: str | None = None
    event_type: str = "photo"

    def to_event(self, ctx: MessageContext) -> AppEvent:
        return AppEvent(
            type=self.event_type,
            text=self.text,
            chat_id=ctx.chat_id,
            request_id=ctx.request_id,
            stream="inprocess",
            raw={
                "file_path": self.file_path,
                "file_id": self.file_id,
                "caption": self.caption,
            },
        )


@dataclass(slots=True)
class AnimationResponse(Response):
    file_path: str | None = None
    file_id: str | None = None
    caption: str | None = None
    event_type: str = "animation"

    def to_event(self, ctx: MessageContext) -> AppEvent:
        return AppEvent(
            type=self.event_type,
            text=self.text,
            chat_id=ctx.chat_id,
            request_id=ctx.request_id,
            stream="inprocess",
            raw={
                "file_path": self.file_path,
                "file_id": self.file_id,
                "caption": self.caption,
            },
        )


@dataclass(slots=True)
class DocumentResponse(Response):
    file_path: str | None = None
    file_id: str | None = None
    caption: str | None = None
    event_type: str = "document"

    def to_event(self, ctx: MessageContext) -> AppEvent:
        return AppEvent(
            type=self.event_type,
            text=self.text,
            chat_id=ctx.chat_id,
            request_id=ctx.request_id,
            stream="inprocess",
            raw={
                "file_path": self.file_path,
                "file_id": self.file_id,
                "caption": self.caption,
            },
        )


@dataclass(slots=True)
class StickerResponse(Response):
    sticker: str = ""
    text: str = ""
    event_type: str = "sticker"

    def to_event(self, ctx: MessageContext) -> AppEvent:
        return AppEvent(
            type=self.event_type,
            text=self.text,
            chat_id=ctx.chat_id,
            request_id=ctx.request_id,
            stream="inprocess",
            raw={"sticker": self.sticker},
        )


@dataclass(slots=True)
class LocationResponse(Response):
    latitude: float = 0.0
    longitude: float = 0.0
    event_type: str = "location"

    def to_event(self, ctx: MessageContext) -> AppEvent:
        return AppEvent(
            type=self.event_type,
            text=self.text,
            chat_id=ctx.chat_id,
            request_id=ctx.request_id,
            stream="inprocess",
            raw={
                "latitude": self.latitude,
                "longitude": self.longitude,
            },
        )


@dataclass(slots=True)
class VenueResponse(Response):
    latitude: float = 0.0
    longitude: float = 0.0
    title: str = ""
    address: str = ""
    event_type: str = "venue"

    def to_event(self, ctx: MessageContext) -> AppEvent:
        return AppEvent(
            type=self.event_type,
            text=self.text,
            chat_id=ctx.chat_id,
            request_id=ctx.request_id,
            stream="inprocess",
            raw={
                "latitude": self.latitude,
                "longitude": self.longitude,
                "title": self.title,
                "address": self.address,
            },
        )


@dataclass(slots=True)
class AudioResponse(Response):
    file_path: str | None = None
    file_id: str | None = None
    caption: str | None = None
    event_type: str = "audio"

    def to_event(self, ctx: MessageContext) -> AppEvent:
        return AppEvent(
            type=self.event_type,
            text=self.text,
            chat_id=ctx.chat_id,
            request_id=ctx.request_id,
            stream="inprocess",
            raw={
                "file_path": self.file_path,
                "file_id": self.file_id,
                "caption": self.caption,
            },
        )


@dataclass(slots=True)
class VoiceResponse(Response):
    file_path: str | None = None
    file_id: str | None = None
    caption: str | None = None
    event_type: str = "voice"

    def to_event(self, ctx: MessageContext) -> AppEvent:
        return AppEvent(
            type=self.event_type,
            text=self.text,
            chat_id=ctx.chat_id,
            request_id=ctx.request_id,
            stream="inprocess",
            raw={
                "file_path": self.file_path,
                "file_id": self.file_id,
                "caption": self.caption,
            },
        )


@dataclass(slots=True)
class VideoResponse(Response):
    file_path: str | None = None
    file_id: str | None = None
    caption: str | None = None
    event_type: str = "video"

    def to_event(self, ctx: MessageContext) -> AppEvent:
        return AppEvent(
            type=self.event_type,
            text=self.text,
            chat_id=ctx.chat_id,
            request_id=ctx.request_id,
            stream="inprocess",
            raw={
                "file_path": self.file_path,
                "file_id": self.file_id,
                "caption": self.caption,
            },
        )


@dataclass(slots=True)
class ContactResponse(Response):
    phone_number: str = ""
    first_name: str = ""
    last_name: str | None = None
    event_type: str = "contact"

    def to_event(self, ctx: MessageContext) -> AppEvent:
        return AppEvent(
            type=self.event_type,
            text=self.text,
            chat_id=ctx.chat_id,
            request_id=ctx.request_id,
            stream="inprocess",
            raw={
                "phone_number": self.phone_number,
                "first_name": self.first_name,
                "last_name": self.last_name,
            },
        )


@dataclass(slots=True)
class PollResponse(Response):
    question: str = ""
    options: list[str] | None = None
    allows_multiple_answers: bool = False
    event_type: str = "poll"

    def to_event(self, ctx: MessageContext) -> AppEvent:
        return AppEvent(
            type=self.event_type,
            text=self.text,
            chat_id=ctx.chat_id,
            request_id=ctx.request_id,
            stream="inprocess",
            raw={
                "question": self.question,
                "options": list(self.options or []),
                "allows_multiple_answers": self.allows_multiple_answers,
            },
        )


@dataclass(slots=True)
class Button:
    text: str
    data: str


@dataclass(slots=True)
class ButtonResponse(Response):
    buttons: list[Button] | None = None
    event_type: str = "buttons"

    def to_event(self, ctx: MessageContext) -> AppEvent:
        return AppEvent(
            type=self.event_type,
            text=self.text,
            chat_id=ctx.chat_id,
            request_id=ctx.request_id,
            stream="inprocess",
            raw={
                "buttons": [
                    {
                        "text": button.text,
                        "data": button.data,
                    }
                    for button in (self.buttons or [])
                ]
            },
        )


def coerce_response(result, ctx: MessageContext) -> AppEvent:
    if isinstance(result, AppEvent):
        return result
    if isinstance(result, Response):
        return result.to_event(ctx)
    if result is None:
        return StatusResponse("handler completed").to_event(ctx)
    return TextResponse(str(result)).to_event(ctx)
