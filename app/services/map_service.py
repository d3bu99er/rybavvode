import html
import json
import math
from datetime import UTC, datetime, timedelta

import folium
from branca.element import Element
from folium.plugins import HeatMap, MarkerCluster

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
      .topic-msg-segment {
        display: block;
      }
      .topic-post-quote {
        margin: 8px 0;
        padding: 8px 10px;
        border-left: 3px solid #94a3b8;
        background: #f8fafc;
        border-radius: 6px;
        color: #334155;
        font-size: 13px;
        line-height: 1.35;
      }
      .topic-post-img {
        display: block;
        max-width: 260px;
        margin-top: 8px;
        border-radius: 6px;
      }
      .topic-post-img-link {
        display: inline-block;
        cursor: zoom-in;
      }
      #topic-panel-lightbox {
        position: fixed;
        inset: 0;
        z-index: 100001;
        background: rgba(15, 23, 42, 0.88);
        display: none;
        align-items: center;
        justify-content: center;
        padding: 20px;
      }
      #topic-panel-lightbox.open {
        display: flex;
      }
      #topic-panel-lightbox img {
        max-width: min(96vw, 1500px);
        max-height: 92vh;
        border-radius: 10px;
        box-shadow: 0 18px 48px rgba(0, 0, 0, 0.42);
      }
      #topic-panel-lightbox-close {
        position: absolute;
        top: 14px;
        right: 14px;
        border: 1px solid rgba(255, 255, 255, 0.42);
        background: rgba(15, 23, 42, 0.68);
        color: #fff;
        border-radius: 8px;
        padding: 6px 10px;
        cursor: pointer;
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
        <h3 id="topic-panel-title">\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f \u0442\u043e\u043f\u0438\u043a\u0430</h3>
        <button id="topic-panel-close" type="button">\u0417\u0430\u043a\u0440\u044b\u0442\u044c</button>
      </div>
      <div id="topic-panel-body"></div>
      <div id="topic-panel-pagination">
        <button id="topic-prev" type="button">\u041d\u0430\u0437\u0430\u0434</button>
        <span id="topic-page-info">\u0421\u0442\u0440. 1</span>
        <button id="topic-next" type="button">\u0412\u043f\u0435\u0440\u0435\u0434</button>
      </div>
    </div>
    <div id="topic-panel-lightbox" aria-hidden="true">
      <button id="topic-panel-lightbox-close" type="button">\u0417\u0430\u043a\u0440\u044b\u0442\u044c</button>
      <img id="topic-panel-lightbox-image" alt="attachment" />
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
        const imageLightbox = document.getElementById('topic-panel-lightbox');
        const imageLightboxClose = document.getElementById('topic-panel-lightbox-close');
        const imageLightboxImage = document.getElementById('topic-panel-lightbox-image');

        const state = { topicId: null, topicTitle: '', page: 1, totalPages: 1, perPage: 15 };

        function esc(s) {
          return String(s || '').replace(/[&<>\"']/g, function(c) {
            if (c === '&') return '&amp;';
            if (c === '<') return '&lt;';
            if (c === '>') return '&gt;';
            if (c === '\"') return '&quot;';
            return '&#39;';
          });
        }

        function normalizeImageEntry(entry) {
          if (!entry) return null;
          if (typeof entry === 'string') {
            return { src: entry, href: entry };
          }
          const src = String(entry.src || '');
          if (!src) return null;
          const href = String(entry.href || src);
          return { src: src, href: href };
        }

        function cleanQuoteText(value) {
          return String(value || '')
            .replace(/Посмотреть\\s+вложение\\s+\\d+/gi, '')
            .replace(/\\s+/g, ' ')
            .trim();
        }

        function splitQuotePrefix(beforeText) {
          const trimmed = String(beforeText || '').trim();
          if (!trimmed) {
            return { leading: '', speaker: '' };
          }

          const punctIndexes = [
            trimmed.lastIndexOf('.'),
            trimmed.lastIndexOf('!'),
            trimmed.lastIndexOf('?'),
            trimmed.lastIndexOf(';'),
            trimmed.lastIndexOf(':')
          ];
          const cut = Math.max.apply(null, punctIndexes);

          let leading = '';
          let candidate = trimmed;
          if (cut >= 0) {
            leading = trimmed.slice(0, cut + 1).trim();
            candidate = trimmed.slice(cut + 1).trim();
          }

          if (!candidate) {
            return { leading: trimmed, speaker: '' };
          }

          const words = candidate.split(/\\s+/).filter(Boolean);
          if (candidate.length > 80 || words.length > 4) {
            return { leading: trimmed, speaker: '' };
          }
          if (/[,!?;:]/.test(candidate)) {
            return { leading: trimmed, speaker: '' };
          }
          if (!/[A-Za-zА-Яа-яЁё0-9]/.test(candidate)) {
            return { leading: trimmed, speaker: '' };
          }
          return { leading: leading, speaker: candidate };
        }

        function renderTextWithQuoteBlocks(text, quoteClass) {
          const raw = String(text || '').trim();
          if (!raw) return '';

          const quoteStartRe = /сказал\\(а\\):/i;
          const quoteEndRe = /нажмите\\s*,?\\s*чтобы\\s*раскрыть(?:\\.\\.\\.|…)?/i;
          let cursor = 0;
          const parts = [];

          while (cursor < raw.length) {
            const tail = raw.slice(cursor);
            const startMatch = quoteStartRe.exec(tail);
            if (!startMatch) {
              const rest = raw.slice(cursor).trim();
              if (rest) {
                parts.push(\"<span class='topic-msg-segment'>\" + esc(rest) + \"</span>\");
              }
              break;
            }

            const startIdx = cursor + startMatch.index;
            const beforeRaw = raw.slice(cursor, startIdx);
            const prefix = splitQuotePrefix(beforeRaw);
            if (prefix.leading) {
              parts.push(\"<span class='topic-msg-segment'>\" + esc(prefix.leading) + \"</span>\");
            }

            const quoteTail = raw.slice(startIdx);
            const endMatch = quoteEndRe.exec(quoteTail);
            if (!endMatch) {
              const rest = raw.slice(startIdx).trim();
              if (rest) {
                parts.push(\"<span class='topic-msg-segment'>\" + esc(rest) + \"</span>\");
              }
              break;
            }

            let quoteBody = cleanQuoteText(quoteTail.slice(0, endMatch.index));
            if (prefix.speaker) {
              quoteBody = prefix.speaker + ' сказал(а): ' + quoteBody.replace(/^сказал\\(а\\):\\s*/i, '');
            }
            if (quoteBody) {
              parts.push(\"<blockquote class='\" + quoteClass + \"'>\" + esc(quoteBody) + \"</blockquote>\");
            }
            cursor = startIdx + endMatch.index + endMatch[0].length;
          }

          if (!parts.length) {
            return \"<span class='topic-msg-segment'>\" + esc(raw) + \"</span>\";
          }
          return parts.join('');
        }

        function render(items) {
          if (!items.length) {
            body.innerHTML = '<p>\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0439 \u043d\u0435\u0442.</p>';
            return;
          }
          body.innerHTML = items.map(function(p) {
            const imgs = (p.image_links || p.images || []).map(function(entry) {
              const image = normalizeImageEntry(entry);
              if (!image) return '';
              return (
                \"<a class='topic-post-img-link' href='\" + esc(image.href) + \"'>\" +
                  \"<img class='topic-post-img' src='\" + esc(image.src) + \"' alt='attachment' />\" +
                \"</a>\"
              );
            }).join('');
            return (
              \"<div class='topic-post'>\" +
                \"<div class='topic-post-meta'><b>\" + esc(p.author) + \"</b> (\" + esc(p.posted_at_local) + \")</div>\" +
                \"<div class='topic-post-text'>\" + renderTextWithQuoteBlocks(p.content_text, 'topic-post-quote') + \"</div>\" +
                imgs +
              \"</div>\"
            );
          }).join('');
        }

        function openImageLightbox(url, altText) {
          if (!imageLightbox || !imageLightboxImage || !url) return;
          imageLightboxImage.src = url;
          imageLightboxImage.alt = altText || 'attachment';
          imageLightbox.classList.add('open');
        }

        function closeImageLightbox() {
          if (!imageLightbox || !imageLightboxImage) return;
          imageLightbox.classList.remove('open');
          imageLightboxImage.removeAttribute('src');
        }

        async function loadPage() {
          if (!state.topicId) return;
          const res = await fetch('/api/topics/' + state.topicId + '/messages?page=' + state.page + '&per_page=' + state.perPage);
          if (!res.ok) {
            body.innerHTML = '<p>\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f.</p>';
            return;
          }
          const data = await res.json();
          state.totalPages = data.total_pages || 1;
          render(data.items || []);
          pageInfo.textContent = '\u0421\u0442\u0440. ' + state.page + ' / ' + state.totalPages;
          prevBtn.disabled = state.page <= 1;
          nextBtn.disabled = state.page >= state.totalPages;
        }

        window.fishingMapOpenTopic = async function(topicId, topicTitle) {
          state.topicId = topicId;
          state.topicTitle = topicTitle || '\u0422\u043e\u043f\u0438\u043a';
          state.page = 1;
          title.textContent = state.topicTitle;
          panel.classList.add('open');
          await loadPage();
        };

        closeBtn.addEventListener('click', function() {
          panel.classList.remove('open');
        });
        if (body) {
          body.addEventListener('click', function(event) {
            const link = event.target.closest('a.topic-post-img-link');
            if (!link) return;
            const href = link.getAttribute('href');
            if (!href) return;
            event.preventDefault();
            const image = link.querySelector('img');
            openImageLightbox(href, image ? image.getAttribute('alt') : 'attachment');
          });
        }
        if (imageLightboxClose) {
          imageLightboxClose.addEventListener('click', function() {
            closeImageLightbox();
          });
        }
        if (imageLightbox) {
          imageLightbox.addEventListener('click', function(event) {
            if (event.target === imageLightbox) {
              closeImageLightbox();
            }
          });
        }
        document.addEventListener('keydown', function(event) {
          if (event.key === 'Escape' && imageLightbox && imageLightbox.classList.contains('open')) {
            closeImageLightbox();
          }
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
          var topicTitle = layer.options.topic_title || layer.options.topicTitle || '\\u0422\\u043e\\u043f\\u0438\\u043a';
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


def _activity_color(last_post_at: datetime | None) -> str:
    if last_post_at is None:
        return "#64748b"
    if last_post_at.tzinfo is None:
        last_post_at = last_post_at.replace(tzinfo=UTC)
    age_days = (datetime.now(UTC) - last_post_at.astimezone(UTC)).total_seconds() / 86400
    if age_days <= 1:
        return "#e63946"
    if age_days <= 7:
        return "#f77f00"
    if age_days <= 30:
        return "#ffba08"
    return "#4361ee"


def _activity_radius(posts_count: int) -> int:
    clamped = max(1, posts_count)
    return max(10, min(26, int(8 + math.sqrt(clamped) * 2.8)))


def _v2_assets(points_json: str, map_var: str, cluster_var: str) -> str:
    template = """
    <style>
      #fishing-sidebar {
        position: absolute;
        top: 12px;
        left: 12px;
        z-index: 99999;
        width: min(360px, 42vw);
        max-height: calc(100% - 24px);
        background: rgba(255, 255, 255, 0.96);
        border: 1px solid #d0d7de;
        border-radius: 12px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.14);
        backdrop-filter: blur(2px);
        display: flex;
        flex-direction: column;
        overflow: hidden;
      }
      #fishing-sidebar.collapsed #fishing-sidebar-body {
        display: none;
      }
      #fishing-sidebar-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 10px 12px;
        border-bottom: 1px solid #e5e7eb;
        background: #f8fafc;
      }
      #fishing-sidebar-title {
        margin: 0;
        font-size: 14px;
        line-height: 1.25;
      }
      #fishing-sidebar-toggle {
        border: 1px solid #cbd5e1;
        background: #fff;
        border-radius: 8px;
        padding: 4px 8px;
        cursor: pointer;
      }
      #fishing-sidebar-body {
        display: flex;
        flex-direction: column;
        min-height: 160px;
      }
      #fishing-topic-list {
        list-style: none;
        margin: 0;
        padding: 0;
        overflow-y: auto;
      }
      .fishing-topic-item {
        display: grid;
        grid-template-columns: auto 1fr auto;
        align-items: center;
        gap: 10px;
        width: 100%;
        border: 0;
        border-bottom: 1px solid #f1f5f9;
        background: #fff;
        text-align: left;
        padding: 10px 12px;
        cursor: pointer;
      }
      .fishing-topic-item:hover {
        background: #f8fafc;
      }
      .fishing-topic-item.active {
        background: #eff6ff;
      }
      .fishing-topic-dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.9);
      }
      .fishing-topic-main {
        min-width: 0;
      }
      .fishing-topic-title {
        font-size: 13px;
        font-weight: 600;
        line-height: 1.25;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .fishing-topic-meta {
        font-size: 12px;
        color: #475569;
        margin-top: 2px;
      }
      .fishing-topic-count {
        font-size: 12px;
        font-weight: 700;
        color: #1d4ed8;
      }
      .leaflet-marker-icon.map-activity-icon {
        background: transparent;
        border: 0;
      }
      .leaflet-control-layers-base {
        display: none;
      }
      .leaflet-control-layers-separator {
        display: none;
      }
      .leaflet-control-layers-overlays::before {
        content: "\\0421\\043b\\043e\\0438";
        display: block;
        font-weight: 700;
        margin: 2px 0 6px;
      }
      #topic-view {
        position: fixed;
        top: 0;
        right: 0;
        width: min(620px, 96vw);
        height: 100vh;
        background: #ffffff;
        border-left: 1px solid #d0d7de;
        box-shadow: -10px 0 28px rgba(0, 0, 0, 0.2);
        z-index: 100000;
        transform: translateX(100%);
        transition: transform .2s ease;
        display: flex;
        flex-direction: column;
      }
      #topic-view.open {
        transform: translateX(0);
      }
      #topic-view-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 12px 14px;
        border-bottom: 1px solid #e5e7eb;
        background: #f8fafc;
      }
      #topic-view-title {
        margin: 0;
        font-size: 15px;
        line-height: 1.25;
      }
      #topic-view-close {
        border: 1px solid #cbd5e1;
        background: #fff;
        border-radius: 8px;
        padding: 4px 8px;
        cursor: pointer;
      }
      #topic-view-body {
        flex: 1;
        overflow-y: auto;
        padding: 12px 14px;
      }
      .topic-view-item {
        border-bottom: 1px solid #edf2f7;
        padding: 10px 0;
      }
      .topic-view-item:last-child {
        border-bottom: 0;
      }
      .topic-view-meta {
        font-size: 13px;
        color: #334155;
        margin-bottom: 6px;
      }
      .topic-view-text {
        font-size: 14px;
        white-space: pre-wrap;
        line-height: 1.4;
      }
      .topic-msg-segment {
        display: block;
      }
      .topic-view-quote {
        margin: 8px 0;
        padding: 8px 10px;
        border-left: 3px solid #94a3b8;
        background: #f8fafc;
        border-radius: 6px;
        color: #334155;
        font-size: 13px;
        line-height: 1.35;
      }
      .topic-view-img {
        display: block;
        max-width: 320px;
        margin-top: 8px;
        border-radius: 6px;
      }
      .topic-view-img-link {
        display: inline-block;
        cursor: zoom-in;
      }
      #topic-view-lightbox {
        position: fixed;
        inset: 0;
        z-index: 100001;
        background: rgba(15, 23, 42, 0.88);
        display: none;
        align-items: center;
        justify-content: center;
        padding: 20px;
      }
      #topic-view-lightbox.open {
        display: flex;
      }
      #topic-view-lightbox img {
        max-width: min(96vw, 1500px);
        max-height: 92vh;
        border-radius: 10px;
        box-shadow: 0 18px 48px rgba(0, 0, 0, 0.42);
      }
      #topic-view-lightbox-close {
        position: absolute;
        top: 14px;
        right: 14px;
        border: 1px solid rgba(255, 255, 255, 0.42);
        background: rgba(15, 23, 42, 0.68);
        color: #fff;
        border-radius: 8px;
        padding: 6px 10px;
        cursor: pointer;
      }
      #topic-view-pagination {
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-top: 1px solid #e5e7eb;
        padding: 10px 14px;
        background: #ffffff;
      }
      .topic-view-pager-btn {
        border: 1px solid #cbd5e1;
        background: #fff;
        border-radius: 8px;
        padding: 4px 8px;
        cursor: pointer;
      }
      .topic-view-pager-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }
      @media (max-width: 900px) {
        #fishing-sidebar {
          top: 8px;
          left: 8px;
          right: 8px;
          width: auto;
          max-height: 44vh;
        }
        #topic-view {
          width: 100vw;
          max-width: 100vw;
        }
      }
    </style>
    <div id="fishing-sidebar">
      <div id="fishing-sidebar-header">
        <h3 id="fishing-sidebar-title">\u0412\u043e\u0434\u043e\u0451\u043c\u044b \u043d\u0430 \u043a\u0430\u0440\u0442\u0435</h3>
        <button id="fishing-sidebar-toggle" type="button">\u0421\u0432\u0435\u0440\u043d\u0443\u0442\u044c</button>
      </div>
      <div id="fishing-sidebar-body">
        <ul id="fishing-topic-list"></ul>
      </div>
    </div>
    <div id="topic-view">
      <div id="topic-view-header">
        <h3 id="topic-view-title">\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f \u0442\u043e\u043f\u0438\u043a\u0430</h3>
        <button id="topic-view-close" type="button">\u0417\u0430\u043a\u0440\u044b\u0442\u044c</button>
      </div>
      <div id="topic-view-body"></div>
      <div id="topic-view-pagination">
        <button id="topic-view-prev" type="button" class="topic-view-pager-btn">\u041d\u0430\u0437\u0430\u0434</button>
        <span id="topic-view-page-info">\u0421\u0442\u0440. 1 / 1</span>
        <button id="topic-view-next" type="button" class="topic-view-pager-btn">\u0412\u043f\u0435\u0440\u0435\u0434</button>
      </div>
    </div>
    <div id="topic-view-lightbox" aria-hidden="true">
      <button id="topic-view-lightbox-close" type="button">\u0417\u0430\u043a\u0440\u044b\u0442\u044c</button>
      <img id="topic-view-lightbox-image" alt="attachment" />
    </div>
    <script>
      (function() {
        const points = __POINTS_JSON__;
        const sidebar = document.getElementById("fishing-sidebar");
        const sidebarBody = document.getElementById("fishing-sidebar-body");
        const list = document.getElementById("fishing-topic-list");
        const toggleBtn = document.getElementById("fishing-sidebar-toggle");
        const view = document.getElementById("topic-view");
        const viewTitle = document.getElementById("topic-view-title");
        const viewBody = document.getElementById("topic-view-body");
        const viewClose = document.getElementById("topic-view-close");
        const viewPrev = document.getElementById("topic-view-prev");
        const viewNext = document.getElementById("topic-view-next");
        const viewPageInfo = document.getElementById("topic-view-page-info");
        const viewLightbox = document.getElementById("topic-view-lightbox");
        const viewLightboxClose = document.getElementById("topic-view-lightbox-close");
        const viewLightboxImage = document.getElementById("topic-view-lightbox-image");
        const markersByTopicId = new Map();
        const rowsByTopicId = new Map();
        const pointsByTopicId = new Map();
        const viewState = { topicId: null, topicTitle: "", page: 1, totalPages: 1, perPage: 20 };

        if (!sidebar || !list || !toggleBtn) {
          return;
        }

        function getMapObj() {
          return window["__MAP_VAR__"];
        }

        function getClusterLayer() {
          return window["__CLUSTER_VAR__"];
        }

        function formatTime(value) {
          if (!value) return "\\u043d\\u0435\\u0442 \\u0434\\u0430\\u043d\\u043d\\u044b\\u0445";
          const dt = new Date(value);
          if (Number.isNaN(dt.getTime())) return value;
          return dt.toLocaleString();
        }

        function esc(value) {
          return String(value || "").replace(/[&<>\"']/g, function(ch) {
            if (ch === "&") return "&amp;";
            if (ch === "<") return "&lt;";
            if (ch === ">") return "&gt;";
            if (ch === '\"') return "&quot;";
            return "&#39;";
          });
        }

        function normalizeImageEntry(entry) {
          if (!entry) return null;
          if (typeof entry === "string") {
            return { src: entry, href: entry };
          }
          const src = String(entry.src || "");
          if (!src) return null;
          const href = String(entry.href || src);
          return { src: src, href: href };
        }

        function cleanQuoteText(value) {
          return String(value || "")
            .replace(/Посмотреть\\s+вложение\\s+\\d+/gi, "")
            .replace(/\\s+/g, " ")
            .trim();
        }

        function splitQuotePrefix(beforeText) {
          const trimmed = String(beforeText || "").trim();
          if (!trimmed) {
            return { leading: "", speaker: "" };
          }

          const punctIndexes = [
            trimmed.lastIndexOf("."),
            trimmed.lastIndexOf("!"),
            trimmed.lastIndexOf("?"),
            trimmed.lastIndexOf(";"),
            trimmed.lastIndexOf(":")
          ];
          const cut = Math.max.apply(null, punctIndexes);

          let leading = "";
          let candidate = trimmed;
          if (cut >= 0) {
            leading = trimmed.slice(0, cut + 1).trim();
            candidate = trimmed.slice(cut + 1).trim();
          }

          if (!candidate) {
            return { leading: trimmed, speaker: "" };
          }

          const words = candidate.split(/\\s+/).filter(Boolean);
          if (candidate.length > 80 || words.length > 4) {
            return { leading: trimmed, speaker: "" };
          }
          if (/[,!?;:]/.test(candidate)) {
            return { leading: trimmed, speaker: "" };
          }
          if (!/[A-Za-zА-Яа-яЁё0-9]/.test(candidate)) {
            return { leading: trimmed, speaker: "" };
          }
          return { leading: leading, speaker: candidate };
        }

        function renderTextWithQuoteBlocks(text, quoteClass) {
          const raw = String(text || "").trim();
          if (!raw) return "";

          const quoteStartRe = /сказал\\(а\\):/i;
          const quoteEndRe = /нажмите\\s*,?\\s*чтобы\\s*раскрыть(?:\\.\\.\\.|…)?/i;
          let cursor = 0;
          const parts = [];

          while (cursor < raw.length) {
            const tail = raw.slice(cursor);
            const startMatch = quoteStartRe.exec(tail);
            if (!startMatch) {
              const rest = raw.slice(cursor).trim();
              if (rest) {
                parts.push("<span class='topic-msg-segment'>" + esc(rest) + "</span>");
              }
              break;
            }

            const startIdx = cursor + startMatch.index;
            const beforeRaw = raw.slice(cursor, startIdx);
            const prefix = splitQuotePrefix(beforeRaw);
            if (prefix.leading) {
              parts.push("<span class='topic-msg-segment'>" + esc(prefix.leading) + "</span>");
            }

            const quoteTail = raw.slice(startIdx);
            const endMatch = quoteEndRe.exec(quoteTail);
            if (!endMatch) {
              const rest = raw.slice(startIdx).trim();
              if (rest) {
                parts.push("<span class='topic-msg-segment'>" + esc(rest) + "</span>");
              }
              break;
            }

            let quoteBody = cleanQuoteText(quoteTail.slice(0, endMatch.index));
            if (prefix.speaker) {
              quoteBody = prefix.speaker + " сказал(а): " + quoteBody.replace(/^сказал\\(а\\):\\s*/i, "");
            }
            if (quoteBody) {
              parts.push("<blockquote class='" + quoteClass + "'>" + esc(quoteBody) + "</blockquote>");
            }
            cursor = startIdx + endMatch.index + endMatch[0].length;
          }

          if (!parts.length) {
            return "<span class='topic-msg-segment'>" + esc(raw) + "</span>";
          }
          return parts.join("");
        }

        function renderViewItems(items) {
          if (!viewBody) return;
          if (!items.length) {
            viewBody.innerHTML = "<p>\\u0421\\u043e\\u043e\\u0431\\u0449\\u0435\\u043d\\u0438\\u0439 \\u043d\\u0435\\u0442.</p>";
            return;
          }
          viewBody.innerHTML = items.map(function(post) {
            const images = (post.image_links || post.images || []).map(function(entry) {
              const image = normalizeImageEntry(entry);
              if (!image) return "";
              return (
                "<a class='topic-view-img-link' href='" + esc(image.href) + "'>" +
                  "<img class='topic-view-img' src='" + esc(image.src) + "' alt='attachment' />" +
                "</a>"
              );
            }).join("");
            return (
              "<article class='topic-view-item'>" +
                "<div class='topic-view-meta'><b>" + esc(post.author) + "</b> (" + esc(post.posted_at_local) + ")</div>" +
                "<div class='topic-view-text'>" + renderTextWithQuoteBlocks(post.content_text || "", "topic-view-quote") + "</div>" +
                images +
              "</article>"
            );
          }).join("");
        }

        function openViewLightbox(url, altText) {
          if (!viewLightbox || !viewLightboxImage || !url) return;
          viewLightboxImage.src = url;
          viewLightboxImage.alt = altText || "attachment";
          viewLightbox.classList.add("open");
        }

        function closeViewLightbox() {
          if (!viewLightbox || !viewLightboxImage) return;
          viewLightbox.classList.remove("open");
          viewLightboxImage.removeAttribute("src");
        }

        async function loadViewPage() {
          if (!viewState.topicId || !viewBody) return;
          try {
            const res = await fetch(
              "/api/topics/" + viewState.topicId + "/messages?page=" + viewState.page + "&per_page=" + viewState.perPage
            );
            if (!res.ok) {
              viewBody.innerHTML = "<p>\\u041d\\u0435 \\u0443\\u0434\\u0430\\u043b\\u043e\\u0441\\u044c \\u0437\\u0430\\u0433\\u0440\\u0443\\u0437\\u0438\\u0442\\u044c \\u0441\\u043e\\u043e\\u0431\\u0449\\u0435\\u043d\\u0438\\u044f.</p>";
              return;
            }
            const data = await res.json();
            viewState.totalPages = data.total_pages || 1;
            renderViewItems(data.items || []);
            if (viewPageInfo) {
              viewPageInfo.textContent = "\\u0421\\u0442\\u0440. " + viewState.page + " / " + viewState.totalPages;
            }
            if (viewPrev) {
              viewPrev.disabled = viewState.page <= 1;
            }
            if (viewNext) {
              viewNext.disabled = viewState.page >= viewState.totalPages;
            }
          } catch (err) {
            viewBody.innerHTML = "<p>\\u041e\\u0448\\u0438\\u0431\\u043a\\u0430 \\u0441\\u0435\\u0442\\u0438 \\u043f\\u0440\\u0438 \\u0437\\u0430\\u0433\\u0440\\u0443\\u0437\\u043a\\u0435 \\u0441\\u043e\\u043e\\u0431\\u0449\\u0435\\u043d\\u0438\\u0439.</p>";
          }
        }

        function openTopicView(topicId, topicTitle) {
          if (!view || !viewTitle) return;
          viewState.topicId = topicId;
          viewState.topicTitle = topicTitle || "\\u0422\\u043e\\u043f\\u0438\\u043a";
          viewState.page = 1;
          viewTitle.textContent = viewState.topicTitle;
          view.classList.add("open");
          loadViewPage();
        }

        function activate(topicId) {
          rowsByTopicId.forEach((row, id) => {
            row.classList.toggle("active", id === String(topicId));
          });
        }

        function focusTopic(topicId) {
          const marker = markersByTopicId.get(String(topicId));
          const mapObj = getMapObj();
          const clusterLayer = getClusterLayer();
          if (!marker || !mapObj) {
            return false;
          }
          if (clusterLayer && typeof clusterLayer.zoomToShowLayer === "function") {
            clusterLayer.zoomToShowLayer(marker, function() {
              marker.openPopup();
            });
          } else {
            marker.openPopup();
          }
          const latLng = marker.getLatLng();
          mapObj.flyTo(latLng, Math.max(mapObj.getZoom(), 8), { duration: 0.35 });
          activate(topicId);
          return true;
        }

        function bindMarker(point) {
          const id = String(point.topic_id);
          if (markersByTopicId.has(id)) {
            return true;
          }
          const marker = window[point.marker_var];
          if (!marker) {
            return false;
          }
          markersByTopicId.set(id, marker);
          marker.on("click", function() {
            activate(point.topic_id);
            openTopicView(point.topic_id, point.title);
          });
          return true;
        }

        const sorted = [...points].sort((a, b) => {
          const aTime = new Date(a.last_post_at || 0).getTime();
          const bTime = new Date(b.last_post_at || 0).getTime();
          return bTime - aTime;
        });
        sorted.forEach((point) => pointsByTopicId.set(String(point.topic_id), point));

        function bindAvailableMarkers() {
          sorted.forEach((point) => {
            bindMarker(point);
          });
          return markersByTopicId.size;
        }

        function waitForMarkers(tries, onDone) {
          const attached = bindAvailableMarkers();
          if (attached >= sorted.length || tries <= 0) {
            if (typeof onDone === "function") {
              onDone();
            }
            return;
          }
          setTimeout(function() {
            waitForMarkers(tries - 1, onDone);
          }, 50);
        }

        if (!sorted.length) {
          const empty = document.createElement("li");
          empty.style.padding = "12px";
          empty.style.fontSize = "13px";
          empty.style.color = "#64748b";
          empty.textContent = "\\u041d\\u0435\\u0442 \\u0432\\u043e\\u0434\\u043e\\u0451\\u043c\\u043e\\u0432 \\u0434\\u043b\\u044f \\u0432\\u044b\\u0431\\u0440\\u0430\\u043d\\u043d\\u044b\\u0445 \\u0444\\u0438\\u043b\\u044c\\u0442\\u0440\\u043e\\u0432.";
          list.appendChild(empty);
        }

        sorted.forEach((point) => {
          const item = document.createElement("button");
          item.type = "button";
          item.className = "fishing-topic-item";
          item.innerHTML =
            "<span class='fishing-topic-dot' style='background:" + point.color + ";'></span>" +
            "<span class='fishing-topic-main'>" +
              "<div class='fishing-topic-title'></div>" +
              "<div class='fishing-topic-meta'></div>" +
            "</span>" +
            "<span class='fishing-topic-count'></span>";

          item.querySelector(".fishing-topic-title").textContent = point.title;
          item.querySelector(".fishing-topic-meta").textContent = "\\u041f\\u043e\\u0441\\u043b\\u0435\\u0434\\u043d\\u0438\\u0439 \\u043f\\u043e\\u0441\\u0442: " + formatTime(point.last_post_at);
          item.querySelector(".fishing-topic-count").textContent = point.posts_count;
          item.addEventListener("click", function() {
            openTopicView(point.topic_id, point.title);
            waitForMarkers(80, function() {
              focusTopic(point.topic_id);
            });
          });
          rowsByTopicId.set(String(point.topic_id), item);
          list.appendChild(item);
        });

        window.fishingMapFocusTopic = function(topicId) {
          const point = pointsByTopicId.get(String(topicId));
          if (point) {
            openTopicView(point.topic_id, point.title);
          }
          waitForMarkers(80, function() {
            focusTopic(topicId);
          });
        };

        waitForMarkers(200);

        toggleBtn.addEventListener("click", function() {
          sidebar.classList.toggle("collapsed");
          const isCollapsed = sidebar.classList.contains("collapsed");
          toggleBtn.textContent = isCollapsed ? "\\u0420\\u0430\\u0437\\u0432\\u0435\\u0440\\u043d\\u0443\\u0442\\u044c" : "\\u0421\\u0432\\u0435\\u0440\\u043d\\u0443\\u0442\\u044c";
          if (!isCollapsed && sidebarBody) {
            sidebarBody.scrollTop = 0;
          }
        });

        if (viewClose) {
          viewClose.addEventListener("click", function() {
            view.classList.remove("open");
          });
        }
        if (viewBody) {
          viewBody.addEventListener("click", function(event) {
            const link = event.target.closest("a.topic-view-img-link");
            if (!link) return;
            const href = link.getAttribute("href");
            if (!href) return;
            event.preventDefault();
            const image = link.querySelector("img");
            openViewLightbox(href, image ? image.getAttribute("alt") : "attachment");
          });
        }
        if (viewLightboxClose) {
          viewLightboxClose.addEventListener("click", function() {
            closeViewLightbox();
          });
        }
        if (viewLightbox) {
          viewLightbox.addEventListener("click", function(event) {
            if (event.target === viewLightbox) {
              closeViewLightbox();
            }
          });
        }
        document.addEventListener("keydown", function(event) {
          if (event.key === "Escape" && viewLightbox && viewLightbox.classList.contains("open")) {
            closeViewLightbox();
          }
        });
        if (viewPrev) {
          viewPrev.addEventListener("click", function() {
            if (viewState.page > 1) {
              viewState.page -= 1;
              loadViewPage();
            }
          });
        }
        if (viewNext) {
          viewNext.addEventListener("click", function() {
            if (viewState.page < viewState.totalPages) {
              viewState.page += 1;
              loadViewPage();
            }
          });
        }
      })();
    </script>
    """
    return (
        template.replace("__MAP_VAR__", map_var)
        .replace("__CLUSTER_VAR__", cluster_var)
        .replace("__POINTS_JSON__", points_json)
    )


def build_map_v2(topic_activity_rows: list[tuple[Topic, int, datetime | None]]) -> str:
    if topic_activity_rows:
        center = [topic_activity_rows[0][0].geocoded_lat, topic_activity_rows[0][0].geocoded_lon]
    else:
        center = [55.751244, 37.618423]

    fmap = folium.Map(location=center, zoom_start=6, control_scale=True, tiles="CartoDB positron")
    cluster = MarkerCluster(name="\u041a\u043b\u0430\u0441\u0442\u0435\u0440\u044b \u0432\u043e\u0434\u043e\u0451\u043c\u043e\u0432", show=True).add_to(fmap)
    bounds: list[list[float]] = []
    heat_data: list[list[float]] = []
    sidebar_points: list[dict[str, str | int | float | None]] = []

    for topic, posts_count, last_post_at in topic_activity_rows:
        if topic.geocoded_lat is None or topic.geocoded_lon is None:
            continue
        lat = float(topic.geocoded_lat)
        lon = float(topic.geocoded_lon)
        color = _activity_color(last_post_at)
        radius = _activity_radius(posts_count)
        diameter = radius * 2
        last_post_str = last_post_at.strftime("%d.%m.%Y %H:%M UTC") if last_post_at else "-"

        popup_html = (
            "<div style='min-width:220px'>"
            f"<b>{html.escape(topic.title)}</b><br/>"
            f"\u041f\u043e\u0441\u0442\u043e\u0432: {posts_count}<br/>"
            f"\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0439 \u043f\u043e\u0441\u0442: {html.escape(last_post_str)}<br/>"
            f"<a href='{html.escape(topic.url)}' target='_blank' rel='noopener noreferrer'>\u041e\u0442\u043a\u0440\u044b\u0442\u044c \u0442\u043e\u043f\u0438\u043a</a>"
            "</div>"
        )
        marker = folium.Marker(
            location=[lat, lon],
            tooltip=f"{topic.place_name} - {posts_count}",
            icon=folium.DivIcon(
                class_name="map-activity-icon",
                icon_size=(diameter, diameter),
                icon_anchor=(radius, radius),
                popup_anchor=(0, -radius),
                html=(
                    "<div "
                    f"style='width:{diameter}px;height:{diameter}px;border-radius:50%;"
                    f"background:{color};border:2px solid #fff;box-shadow:0 2px 10px rgba(0,0,0,.35);opacity:.92;'>"
                    "</div>"
                ),
            ),
        )
        marker.add_child(folium.Popup(popup_html, max_width=360))
        marker.add_to(cluster)

        bounds.append([lat, lon])
        heat_weight = min(1.0, 0.3 + min(posts_count, 40) / 40)
        heat_data.append([lat, lon, heat_weight])
        sidebar_points.append(
            {
                "topic_id": topic.id,
                "title": topic.title,
                "posts_count": int(posts_count),
                "last_post_at": last_post_at.isoformat() if last_post_at else None,
                "color": color,
                "marker_var": marker.get_name(),
            }
        )

    if heat_data:
        HeatMap(
            heat_data,
            name="\u0422\u0435\u043f\u043b\u043e\u0432\u0430\u044f \u043a\u0430\u0440\u0442\u0430 \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0441\u0442\u0438",
            show=False,
            radius=24,
            blur=18,
            min_opacity=0.35,
            max_zoom=11,
        ).add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)
    if bounds:
        fmap.fit_bounds(bounds, padding=(30, 30))

    points_json = json.dumps(sidebar_points, ensure_ascii=False).replace("</", "<\\/")
    fmap.get_root().html.add_child(Element(_v2_assets(points_json, fmap.get_name(), cluster.get_name())))
    return fmap._repr_html_()
