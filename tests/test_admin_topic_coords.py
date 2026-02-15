from app.services.repository import get_topic, update_topic_coordinates


def test_manual_topic_coordinates_update(db_session):
    topic = get_topic(db_session, 1)
    assert topic is not None

    ok = update_topic_coordinates(
        db_session,
        topic_id=topic.id,
        lat=56.123,
        lon=38.456,
        confidence=0.95,
        provider="manual",
    )
    assert ok is True
    db_session.commit()

    updated = get_topic(db_session, topic.id)
    assert updated is not None
    assert updated.geocoded_lat == 56.123
    assert updated.geocoded_lon == 38.456
    assert updated.geocode_provider == "manual"
    assert updated.geocode_confidence == 0.95
