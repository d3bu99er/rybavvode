import html
from datetime import UTC, datetime, timedelta

import folium

from app.models import Post


def parse_period(period: str) -> datetime | None:
    now = datetime.now(UTC)
    if period == "24h":
        return now - timedelta(hours=24)
    if period == "7d":
        return now - timedelta(days=7)
    if period == "30d":
        return now - timedelta(days=30)
    return None


def build_map(posts: list[Post]) -> str:
    if posts:
        center = [posts[0].topic.geocoded_lat, posts[0].topic.geocoded_lon]
    else:
        center = [55.751244, 37.618423]
    fmap = folium.Map(location=center, zoom_start=6, control_scale=True)
    for post in posts:
        topic = post.topic
        preview = html.escape((post.content_text or "")[:200])
        popup_html = (
            f"<b>{html.escape(topic.title)}</b><br/>"
            f"Автор: {html.escape(post.author)}<br/>"
            f"Дата: {post.posted_at_utc.isoformat()}<br/>"
            f"{preview}<br/>"
            f"<a href='{html.escape(post.url)}' target='_blank' rel='noopener noreferrer'>Открыть пост</a>"
        )
        folium.Marker(
            location=[topic.geocoded_lat, topic.geocoded_lon],
            popup=folium.Popup(popup_html, max_width=420),
            tooltip=topic.place_name,
        ).add_to(fmap)
    return fmap._repr_html_()
