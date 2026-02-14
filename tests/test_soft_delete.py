from app.services.repository import list_posts, restore_post, soft_delete_post


def test_soft_delete_and_filter(db_session):
    posts = list_posts(db_session, include_deleted=False, has_geo=False)
    assert len(posts) == 1

    ok = soft_delete_post(db_session, posts[0].id)
    assert ok is True
    db_session.commit()

    visible = list_posts(db_session, include_deleted=False, has_geo=False)
    assert len(visible) == 0

    all_rows = list_posts(db_session, include_deleted=True, has_geo=False)
    assert len(all_rows) == 1
    assert all_rows[0].is_deleted is True

    restore_post(db_session, all_rows[0].id)
    db_session.commit()

    visible_after = list_posts(db_session, include_deleted=False, has_geo=False)
    assert len(visible_after) == 1
    assert visible_after[0].is_deleted is False
