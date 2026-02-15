import html
from datetime import UTC, datetime, timedelta

import folium

from app.models import Post, Topic


def parse_period(period: str) -> datetime | None:
    now = datetime.now(UTC)
    if period == "24h":
        return now - timedelta(hours=24)
    if period == "7d":
        return now - timedelta(days=7)
    if period == "30d":
        return now - timedelta(days=30)
    return None


def build_map(topic_rows: list[tuple[Topic, list[Post]]]) -> str:
    if topic_rows:
        center = [topic_rows[0][0].geocoded_lat, topic_rows[0][0].geocoded_lon]
    else:
        center = [55.751244, 37.618423]

    fmap = folium.Map(location=center, zoom_start=6, control_scale=True)
    for topic, posts in topic_rows:
        items: list[str] = []
        for post in posts:
            full_text = html.escape(post.content_text or "")
            images: list[str] = []
            for att in post.attachments:
                if att.is_image and att.local_rel_path:
                    src = f"/media/attachments/{att.local_rel_path}"
                    images.append(
                        f"<img src='{html.escape(src)}' alt='{html.escape(att.file_name)}' "
                        "style='max-width:240px; display:block; margin-top:6px;'/>"
                    )
            items.append(
                "<li>"
                f"<b>{html.escape(post.author)}</b> ({post.posted_at_utc.isoformat()})<br/>"
                f"{full_text}"
                f"{''.join(images)}"
                "</li>"
            )

        popup_html = (
            f"<b>{html.escape(topic.title)}</b><br/>"
            f"<a href='{html.escape(topic.url)}' target='_blank' rel='noopener noreferrer'>Open topic</a><br/>"
            f"Latest messages ({len(posts)}):"
            f"<ol>{''.join(items)}</ol>"
        )
        folium.Marker(
            location=[topic.geocoded_lat, topic.geocoded_lon],
            popup=folium.Popup(popup_html, max_width=580),
            tooltip=topic.place_name,
        ).add_to(fmap)
    return fmap._repr_html_()
