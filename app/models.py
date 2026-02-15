from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)

    topics: Mapped[list["Topic"]] = relationship("Topic", back_populates="source", cascade="all, delete-orphan")


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_topics_source_external"),
        Index("ix_topics_geocoded_lat_lon", "geocoded_lat", "geocoded_lon"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    place_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    geocoded_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    geocoded_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    geocode_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    geocode_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    geocode_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    source: Mapped[Source] = relationship("Source", back_populates="topics")
    posts: Mapped[list["Post"]] = relationship("Post", back_populates="topic", cascade="all, delete-orphan")


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("topic_id", "external_id", name="uq_posts_topic_external"),
        Index("ix_posts_posted_at_utc", "posted_at_utc"),
        Index("ix_posts_is_deleted", "is_deleted"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    posted_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    topic: Mapped[Topic] = relationship("Topic", back_populates="posts")
    attachments: Mapped[list["PostAttachment"]] = relationship(
        "PostAttachment", back_populates="post", cascade="all, delete-orphan"
    )


class PostAttachment(Base):
    __tablename__ = "post_attachments"
    __table_args__ = (
        UniqueConstraint("post_id", "source_url", name="uq_post_attachments_post_source_url"),
        Index("ix_post_attachments_post_id", "post_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    local_rel_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_image: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    post: Mapped[Post] = relationship("Post", back_populates="attachments")
