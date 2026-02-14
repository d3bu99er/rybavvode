from app.services.repository import posts_for_map


def test_posts_use_topic_coordinates(db_session):
    rows = posts_for_map(db_session, since=None, q=None, limit=50, min_geo_confidence=0.4)
    assert len(rows) == 1
    post = rows[0]
    assert post.topic.geocoded_lat == 55.7
    assert post.topic.geocoded_lon == 37.6
