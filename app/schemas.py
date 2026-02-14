from datetime import datetime

from pydantic import BaseModel


class TopicOut(BaseModel):
    id: int
    external_id: str
    title: str
    url: str
    place_name: str
    geocoded_lat: float | None
    geocoded_lon: float | None
    geocode_provider: str | None
    geocode_confidence: float | None

    class Config:
        from_attributes = True


class PostOut(BaseModel):
    id: int
    topic_id: int
    external_id: str
    author: str
    posted_at_utc: datetime
    content_text: str
    url: str
    is_deleted: bool
    deleted_at: datetime | None
    topic: TopicOut

    class Config:
        from_attributes = True
