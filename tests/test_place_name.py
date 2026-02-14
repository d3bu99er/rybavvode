from app.services.forum_scraper import ForumScraper


def test_title_to_place_name_basic():
    title = "Платник Зеленый Берег (отзывы)"
    assert ForumScraper.title_to_place_name(title) == "Платник Зеленый Берег (отзывы)"


def test_title_to_place_name_trim_spaces():
    title = "  Озеро   Лесное   "
    assert ForumScraper.title_to_place_name(title) == "Озеро Лесное"
