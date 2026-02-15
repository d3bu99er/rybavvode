from datetime import UTC, datetime, timedelta

import folium
from branca.element import Element

from app.models import Topic


def parse_period(period: str) -> datetime | None:
    now = datetime.now(UTC)
    if period == "24h":
        return now - timedelta(hours=24)
    if period == "7d":
        return now - timedelta(days=7)
    if period == "30d":
        return now - timedelta(days=30)
    return None


def _panel_assets() -> str:
    return """
    <style>
      #topic-panel {
        position: fixed;
        top: 0;
        right: 0;
        height: 100vh;
        width: min(520px, 95vw);
        background: #ffffff;
        border-left: 1px solid #d0d7de;
        box-shadow: -6px 0 18px rgba(0, 0, 0, 0.12);
        z-index: 99999;
        transform: translateX(100%);
        transition: transform .18s ease-out;
        display: flex;
        flex-direction: column;
      }
      #topic-panel.open { transform: translateX(0); }
      #topic-panel-header {
        padding: 12px 14px;
        border-bottom: 1px solid #e5e7eb;
        display: flex;
        gap: 8px;
        align-items: center;
        justify-content: space-between;
        background: #f9fafb;
      }
      #topic-panel-title {
        margin: 0;
        font-size: 15px;
        line-height: 1.35;
      }
      #topic-panel-close {
        border: 1px solid #d1d5db;
        background: #fff;
        border-radius: 6px;
        padding: 4px 8px;
        cursor: pointer;
      }
      #topic-panel-body {
        overflow-y: auto;
        padding: 12px 14px;
        flex: 1;
      }
      .topic-post {
        border-bottom: 1px solid #eceff3;
        padding: 10px 0;
      }
      .topic-post:last-child { border-bottom: 0; }
      .topic-post-meta {
        font-size: 13px;
        margin-bottom: 6px;
      }
      .topic-post-text {
        white-space: pre-wrap;
        line-height: 1.35;
      }
      .topic-post-img {
        display: block;
        max-width: 260px;
        margin-top: 8px;
        border-radius: 6px;
      }
      #topic-panel-pagination {
        padding: 10px 14px;
        border-top: 1px solid #e5e7eb;
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
      #topic-panel-pagination button {
        border: 1px solid #d1d5db;
        background: #fff;
        border-radius: 6px;
        padding: 4px 8px;
        cursor: pointer;
      }
      #topic-panel-pagination button:disabled {
        opacity: .5;
        cursor: not-allowed;
      }
    </style>
    <div id="topic-panel">
      <div id="topic-panel-header">
        <h3 id="topic-panel-title">Сообщения топика</h3>
        <button id="topic-panel-close" type="button">Закрыть</button>
      </div>
      <div id="topic-panel-body"></div>
      <div id="topic-panel-pagination">
        <button id="topic-prev" type="button">Назад</button>
        <span id="topic-page-info">Стр. 1</span>
        <button id="topic-next" type="button">Вперед</button>
      </div>
    </div>
    <script>
      (function() {
        const panel = document.getElementById('topic-panel');
        const title = document.getElementById('topic-panel-title');
        const body = document.getElementById('topic-panel-body');
        const closeBtn = document.getElementById('topic-panel-close');
        const prevBtn = document.getElementById('topic-prev');
        const nextBtn = document.getElementById('topic-next');
        const pageInfo = document.getElementById('topic-page-info');

        const state = { topicId: null, topicTitle: '', page: 1, totalPages: 1, perPage: 15 };

        function esc(s) {
          return String(s || '').replace(/[&<>"']/g, function(c) {
            return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
          });
        }

        function render(items) {
          if (!items.length) {
            body.innerHTML = '<p>Сообщений нет.</p>';
            return;
          }
          body.innerHTML = items.map(function(p) {
            const imgs = (p.images || []).map(function(src) {
              return "<img class='topic-post-img' src='" + esc(src) + "' />";
            }).join('');
            return (
              "<div class='topic-post'>" +
                "<div class='topic-post-meta'><b>" + esc(p.author) + "</b> (" + esc(p.posted_at_local) + ")</div>" +
                "<div class='topic-post-text'>" + esc(p.content_text) + "</div>" +
                imgs +
              "</div>"
            );
          }).join('');
        }

        async function loadPage() {
          if (!state.topicId) return;
          const res = await fetch('/api/topics/' + state.topicId + '/messages?page=' + state.page + '&per_page=' + state.perPage);
          if (!res.ok) {
            body.innerHTML = '<p>Не удалось загрузить сообщения.</p>';
            return;
          }
          const data = await res.json();
          state.totalPages = data.total_pages || 1;
          render(data.items || []);
          pageInfo.textContent = 'Стр. ' + state.page + ' / ' + state.totalPages;
          prevBtn.disabled = state.page <= 1;
          nextBtn.disabled = state.page >= state.totalPages;
        }

        window.fishingMapOpenTopic = async function(topicId, topicTitle) {
          state.topicId = topicId;
          state.topicTitle = topicTitle || 'Топик';
          state.page = 1;
          title.textContent = state.topicTitle;
          panel.classList.add('open');
          await loadPage();
        };

        closeBtn.addEventListener('click', function() {
          panel.classList.remove('open');
        });
        prevBtn.addEventListener('click', async function() {
          if (state.page > 1) {
            state.page -= 1;
            await loadPage();
          }
        });
        nextBtn.addEventListener('click', async function() {
          if (state.page < state.totalPages) {
            state.page += 1;
            await loadPage();
          }
        });
      })();
    </script>
    """


def build_map(topics: list[Topic]) -> str:
    if topics:
        center = [topics[0].geocoded_lat, topics[0].geocoded_lon]
    else:
        center = [55.751244, 37.618423]

    fmap = folium.Map(location=center, zoom_start=6, control_scale=True)
    fmap.get_root().html.add_child(Element(_panel_assets()))

    for topic in topics:
        marker = folium.Marker(
            location=[topic.geocoded_lat, topic.geocoded_lon],
            tooltip=topic.place_name,
            topic_id=topic.id,
            topic_title=topic.title,
        )
        marker.add_to(fmap)
    map_var = fmap.get_name()
    bind_js = f"""
    (function() {{
      function getMap() {{
        return window['{map_var}'];
      }}
      function bindTopicClicks() {{
        var mapObj = getMap();
        if (!mapObj) return false;
        mapObj.eachLayer(function(layer) {{
          if (!(layer instanceof L.Marker) || !layer.options) return;
          if (layer._fishingClickBound) return;
          var topicId = layer.options.topic_id || layer.options.topicId;
          if (!topicId) return;
          var topicTitle = layer.options.topic_title || layer.options.topicTitle || 'Топик';
          layer.on('click', function() {{
            window.fishingMapOpenTopic(topicId, topicTitle);
          }});
          layer._fishingClickBound = true;
        }});
        mapObj.on('layeradd', bindTopicClicks);
        return true;
      }}

      function waitAndBind(tries) {{
        if (bindTopicClicks()) return;
        if (tries <= 0) return;
        setTimeout(function() {{ waitAndBind(tries - 1); }}, 50);
      }}
      waitAndBind(200);
    }})();
    """
    fmap.get_root().script.add_child(Element(bind_js))
    return fmap._repr_html_()
