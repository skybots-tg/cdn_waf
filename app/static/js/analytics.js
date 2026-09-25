// Общие помощники экранов аналитики (домен, общая аналитика, CDN, WAF,
// дашборд, логи, ноды). Один модуль, чтобы цифры везде форматировались
// одинаково и время везде было местным.
//
// API отдаёт время в UTC с «Z» (analytics_query.iso). До 23.09.2026 «Z» не
// было, браузер читал время как местное, и «5 минут назад» врало на пояс.
(function (global) {
    const FC = {};

    FC.escape = function (value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    };

    FC.num = function (n) {
        n = Number(n) || 0;
        if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, '') + 'B';
        if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
        if (Math.abs(n) >= 1e4) return (n / 1e3).toFixed(1).replace(/\.0$/, '') + 'k';
        return n.toLocaleString('en-US');
    };

    FC.bytes = function (b) {
        b = Number(b) || 0;
        const units = ['B', 'KB', 'MB', 'GB', 'TB'];
        let i = 0;
        while (b >= 1024 && i < units.length - 1) { b /= 1024; i++; }
        return (i === 0 ? b : b.toFixed(b >= 100 ? 0 : 1)) + ' ' + units[i];
    };

    FC.ms = function (v) {
        if (v == null) return '—';
        v = Number(v);
        return v >= 1000 ? (v / 1000).toFixed(2) + ' s' : Math.round(v) + ' ms';
    };

    FC.pct = function (v) {
        return v == null ? '—' : (Number(v) || 0).toFixed(1).replace(/\.0$/, '') + '%';
    };

    // Значок изменения к прошлому периоду. invert — рост это плохо (ошибки,
    // угрозы); points — изменение в процентных пунктах (доля кэша).
    FC.change = function (value, opts) {
        opts = opts || {};
        if (value == null) return '<span style="color: var(--text-muted);">no previous data</span>';
        const up = value > 0;
        const good = opts.invert ? !up : up;
        const color = value === 0 ? 'var(--text-muted)' : (good ? 'var(--success)' : 'var(--error)');
        const arrow = value === 0 ? '' : (up ? '▲ ' : '▼ ');
        const unit = opts.points ? ' pp' : '%';
        return '<span style="color:' + color + ';">' + arrow + Math.abs(value).toFixed(1).replace(/\.0$/, '') +
            unit + '</span> <span style="color: var(--text-muted);">vs previous period</span>';
    };

    FC.parseTime = function (iso) {
        if (!iso) return null;
        // Старые ответы без зоны — это UTC.
        return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z');
    };

    FC.localTime = function (iso, withDate) {
        const d = FC.parseTime(iso);
        if (!d || isNaN(d)) return '—';
        const opts = { hour: '2-digit', minute: '2-digit', second: '2-digit' };
        if (withDate !== false) { opts.year = 'numeric'; opts.month = 'short'; opts.day = 'numeric'; }
        return d.toLocaleString(undefined, opts);
    };

    FC.relative = function (iso) {
        const d = FC.parseTime(iso);
        if (!d || isNaN(d)) return '—';
        const s = Math.round((Date.now() - d.getTime()) / 1000);
        if (s < 60) return s + 's ago';
        if (s < 3600) return Math.floor(s / 60) + 'm ago';
        if (s < 86400) return Math.floor(s / 3600) + 'h ago';
        return Math.floor(s / 86400) + 'd ago';
    };

    // Подпись шага графика в местном времени.
    FC.bucketLabel = function (iso, bucket) {
        const d = FC.parseTime(iso);
        if (bucket === 'minute') return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
        if (bucket === 'hour') return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
        return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    };

    let regionNames = null;
    try { regionNames = new Intl.DisplayNames(['en'], { type: 'region' }); } catch (e) { regionNames = null; }

    // Код страны меткой: флаги-эмодзи Windows рисует двумя буквами, и в
    // списке это выглядело как опечатка (стиль .cc — в style.css).
    FC.flag = function (code) {
        if (!code || !/^[A-Za-z]{2}$/.test(code)) return '<span class="cc">··</span>';
        return '<span class="cc">' + code.toUpperCase() + '</span>';
    };

    FC.country = function (code) {
        if (!code) return 'Unknown';
        let name = code;
        try { name = (regionNames && regionNames.of(code.toUpperCase())) || code; } catch (e) { name = code; }
        return FC.flag(code) + ' ' + name;
    };

    FC.statusColor = function (status) {
        status = Number(status) || 0;
        if (status >= 500) return 'var(--error)';
        if (status >= 400) return 'var(--warning)';
        if (status >= 300) return 'var(--info)';
        return 'var(--success)';
    };

    FC.cacheBadge = function (s) {
        const map = {
            HIT: 'badge-success', STALE: 'badge-success', UPDATING: 'badge-success', REVALIDATED: 'badge-success',
            MISS: 'badge-warning', EXPIRED: 'badge-warning', BYPASS: 'badge-info',
        };
        if (!s) return '<span class="badge" style="opacity:.6;">DYNAMIC</span>';
        return '<span class="badge ' + (map[s] || '') + '">' + FC.escape(s) + '</span>';
    };

    FC.get = async function (url) {
        const r = await fetch(url);
        if (!r.ok) {
            let detail = r.status + ' ' + r.statusText;
            try { const j = await r.json(); if (j && j.detail) detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch (e) { /* не JSON */ }
            throw new Error(detail);
        }
        return r.json();
    };

    // Выгрузка файла через fetch: обычный переход по ссылке не несёт
    // Bearer-токен, и API ответил бы 401.
    FC.download = async function (url, filename) {
        try {
            const r = await fetch(url);
            if (!r.ok) throw new Error(r.status + ' ' + r.statusText);
            const blob = await r.blob();
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            setTimeout(() => { URL.revokeObjectURL(link.href); link.remove(); }, 1000);
        } catch (e) {
            if (typeof showNotification === 'function') showNotification('Export failed: ' + e.message, 'error');
            else alert('Export failed: ' + e.message);
        }
    };

    FC.loading = function (el) {
        if (el) el.innerHTML = '<p style="text-align:center;color:var(--text-muted);padding:24px;"><i class="fas fa-spinner fa-spin"></i> Loading…</p>';
    };

    FC.empty = function (el, text) {
        if (el) el.innerHTML = '<p style="text-align:center;color:var(--text-muted);padding:24px;">' + FC.escape(text || 'No data for this period') + '</p>';
    };

    FC.error = function (el, err) {
        if (el) el.innerHTML = '<p style="text-align:center;color:var(--error);padding:24px;"><i class="fas fa-exclamation-triangle"></i> ' +
            FC.escape((err && err.message) || err || 'Failed to load') + '</p>';
    };

    // Цвета графика из темы: подписи и сетка не спорят с данными.
    function themeColors() {
        const st = getComputedStyle(document.documentElement);
        const v = (name, fallback) => st.getPropertyValue(name).trim() || fallback;
        return {
            accent: v('--accent-primary', '#ff6b35'), second: v('--accent-secondary', '#339af0'),
            text: v('--text-muted', '#868e96'), grid: v('--glass-border', 'rgba(128,128,128,.2)'),
        };
    }

    // График по шагам периода (Chart.js). Одна линия — без легенды: её
    // называет кнопка над графиком. У запросов и трафика вторая линия —
    // «из кэша», тогда легенда нужна.
    FC.trafficChart = function (canvas, previous, data, metric) {
        if (previous) previous.destroy();
        const isBytes = metric === 'bandwidth';
        const c = themeColors();
        const labels = data.timestamps.map(t => FC.bucketLabel(t, data.bucket));
        const line = (label, values, color, fill) => ({
            label: label, data: values, borderColor: color, backgroundColor: color + '26',
            fill: fill, cubicInterpolationMode: 'monotone', pointRadius: 0, pointHoverRadius: 4,
            pointHoverBackgroundColor: color, borderWidth: 2,
        });
        const single = { visits: 'Visits', page_views: 'Page views', visitors: 'Unique visitors (IP)' }[metric];
        const datasets = single
            ? [line(single, data.series[metric] || [], c.accent, true)]
            : [
                line(isBytes ? 'Total' : 'All requests', isBytes ? data.series.bandwidth : data.series.requests, c.accent, true),
                line(isBytes ? 'From cache' : 'From cache', isBytes ? data.series.cached_bandwidth : data.series.cached_requests, c.second, false),
            ];
        return new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: { labels: labels, datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        display: datasets.length > 1, align: 'end',
                        labels: { boxWidth: 10, boxHeight: 10, color: c.text, usePointStyle: true, pointStyle: 'rectRounded' },
                    },
                    tooltip: { callbacks: { label: t => ' ' + t.dataset.label + ': ' + (isBytes ? FC.bytes(t.parsed.y) : FC.num(t.parsed.y)) } },
                },
                scales: {
                    x: { ticks: { maxTicksLimit: 8, autoSkip: true, color: c.text, maxRotation: 0 }, grid: { display: false }, border: { color: c.grid } },
                    y: {
                        beginAtZero: true, border: { display: false }, grid: { color: c.grid },
                        // Визиты и просмотры — целые: деления «0.5» бессмысленны.
                        ticks: { color: c.text, precision: 0, maxTicksLimit: 6, callback: v => isBytes ? FC.bytes(v) : FC.num(v) },
                    },
                },
            },
        });
    };

    FC.rangeLabel = function (range) {
        return ({ '1h': 'last hour', '24h': 'last 24 hours', '7d': 'last 7 days', '30d': 'last 30 days',
                  '90d': 'last 90 days', '6m': 'last 6 months' })[range] || range;
    };

    function remember(param, storage, value, fallback) {
        try { localStorage.setItem(storage, value); } catch (e) { /* приватный режим */ }
        const p = new URLSearchParams(window.location.search);
        if (value === fallback) p.delete(param); else p.set(param, value);
        const query = p.toString();
        history.replaceState(null, '', window.location.pathname + (query ? '?' + query : ''));
    }

    // Период в адресе (?range=7d): страницу можно обновить или переслать.
    FC.initRange = function (select, onChange) {
        const params = new URLSearchParams(window.location.search);
        let saved = params.get('range');
        try { saved = saved || localStorage.getItem('analytics_range'); } catch (e) { /* приватный режим */ }
        if (saved && [...select.options].some(o => o.value === saved)) select.value = saved;
        select.addEventListener('change', function () {
            remember('range', 'analytics_range', select.value, null);
            onChange(select.value);
        });
        return select.value;
    };

    // Переключатель из кнопок (.seg): значение в адресе (?traffic=people,
    // ?count=views) и в памяти браузера, как у периода.
    //   traffic — кто прислал запрос: all, people, bots (классы — app/services/traffic_class.py);
    //   count   — что считают отчёты: visits, visitors, views, requests.
    FC.initSeg = function (el, param, fallback, onChange) {
        const storage = 'analytics_' + param;
        const buttons = [...el.querySelectorAll('button[data-value]')];
        const valid = v => buttons.some(b => b.dataset.value === v);
        let value = new URLSearchParams(window.location.search).get(param);
        try { value = value || localStorage.getItem(storage); } catch (e) { /* приватный режим */ }
        if (!valid(value)) value = fallback;
        const paint = () => buttons.forEach(b => b.setAttribute('aria-pressed', String(b.dataset.value === value)));
        paint();
        buttons.forEach(b => b.addEventListener('click', () => {
            if (b.dataset.value === value) return;
            value = b.dataset.value;
            paint();
            remember(param, storage, value, fallback);
            onChange(value);
        }));
        return value;
    };

    // Изменение к прошлому периоду, коротко: «▲ 27%». invert — рост это
    // плохо (отказы, ошибки, угрозы); points — в процентных пунктах.
    FC.delta = function (value, opts) {
        opts = opts || {};
        if (value == null) return '<span class="delta delta--none" title="No data for the previous period">—</span>';
        if (value === 0) return '<span class="delta delta--flat" title="vs previous period">0%</span>';
        const up = value > 0;
        const good = opts.invert ? !up : up;
        const text = (up ? '▲ ' : '▼ ') + Math.abs(value).toFixed(1).replace(/\.0$/, '') + (opts.points ? ' pp' : '%');
        return '<span class="delta ' + (good ? 'delta--up' : 'delta--down') + '" title="vs previous period">' + text + '</span>';
    };

    // Время визита «1:05» (секунды → минуты:секунды), как в Метрике.
    FC.duration = function (seconds) {
        if (seconds == null) return '—';
        const s = Math.round(Number(seconds) || 0);
        return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
    };

    // Колонки отчётов. Посетитель — уникальный IP.
    const COLS = {
        visits: { title: 'Visits', value: i => i.visits },
        visitors: { title: 'IPs', value: i => i.visitors },
        views: { title: 'Views', value: i => i.views },
        requests: { title: 'Req.', value: i => i.requests, wide: true },
        bytes: { title: 'Traffic', value: i => i.bytes, fmt: FC.bytes, wide: true },
    };

    // Отчёт-таблица: имя, числа по колонкам и доля выбранной метрики с
    // полоской. Длинные имена обрезаются, полное — в подсказке.
    //   opts.name(item) → HTML имени, opts.sub(item) → вторая строка,
    //   opts.columns — ключи COLS, opts.metric — по чему доля и полоска.
    FC.renderReport = function (el, items, opts) {
        opts = opts || {};
        if (!el) return;
        if (!items || !items.length) return FC.empty(el, opts.emptyText);
        const columns = opts.columns || ['visits', 'visitors', 'views'];
        const metric = columns.includes(opts.metric) ? opts.metric : columns[0];
        const size = i => Number(COLS[metric].value(i)) || 0;
        const max = Math.max(...items.map(size), 1);
        const head = '<colgroup><col>' + columns.map(k => '<col class="' + (COLS[k].wide ? 'c-num-wide' : 'c-num') + '">').join('') +
            '<col class="c-share"></colgroup><thead><tr><th>' + FC.escape(opts.label || '') + '</th>' +
            columns.map(k => '<th class="num' + (k === metric ? ' is-active' : '') + '">' + COLS[k].title + '</th>').join('') +
            '<th class="num">Share</th></tr></thead>';
        const rows = items.map(item => {
            const name = opts.name ? opts.name(item) : FC.escape(item.key == null ? '—' : item.key);
            const sub = opts.sub ? opts.sub(item) : '';
            const title = FC.escape(item.key == null ? '' : item.key);
            const cells = columns.map(k => {
                const v = COLS[k].value(item);
                return '<td class="num' + (k === metric ? ' is-active' : '') + '">' + (v == null ? '—' : (COLS[k].fmt || FC.num)(v)) + '</td>';
            }).join('');
            const width = Math.max(1.5, size(item) / max * 100);
            const share = '<td><div class="share"><span class="share__bar"><i style="width:' + width.toFixed(1) + '%"></i></span>' +
                '<span class="share__pct">' + FC.pct(item.percentage) + '</span></div></td>';
            return '<tr><td class="rt__name" title="' + title + '">' + name + (sub ? '<span class="rt__sub">' + sub + '</span>' : '') + '</td>' + cells + share + '</tr>';
        }).join('');
        el.innerHTML = '<div class="rt-wrap"><table class="rt">' + head + '<tbody>' + rows + '</tbody></table></div>' +
            (opts.partial ? '<p class="rt__note">Raw logs are kept for 30 days — this list covers the last 30 days.</p>' : '');
    };

    // Люди против ботов одной полоской над «Who Visits».
    FC.renderSplit = function (el, items, metric) {
        if (!el) return;
        const key = (COLS[metric] || COLS.visits).value;
        let people = 0, bots = 0;
        (items || []).forEach(i => { if (i.people) people += Number(key(i)) || 0; else bots += Number(key(i)) || 0; });
        const total = people + bots;
        if (!total) { el.innerHTML = ''; return; }
        const c = themeColors();
        const pct = n => (n / total * 100);
        el.innerHTML = '<div class="split"><div class="split__bar">' +
            (people ? '<i style="width:' + pct(people) + '%;background:var(--success)"></i>' : '') +
            (bots ? '<i style="width:' + pct(bots) + '%;background:' + c.text + '"></i>' : '') +
            '</div><div class="split__legend">' +
            '<span><span class="swatch" style="background:var(--success)"></span>People <b>' + FC.num(people) + '</b> · ' + FC.pct(pct(people)) + '</span>' +
            '<span><span class="swatch" style="background:' + c.text + '"></span>Bots <b>' + FC.num(bots) + '</b> · ' + FC.pct(pct(bots)) + '</span>' +
            '</div></div>';
    };

    // Классы ответов одной полоской (2xx/3xx/4xx/5xx) с подписями.
    FC.renderStatusSplit = function (el, s) {
        if (!el) return;
        const total = s.total_requests || 0;
        const parts = [
            ['2xx', s.status_2xx, 'var(--success)'], ['3xx', s.status_3xx, 'var(--info)'],
            ['4xx', s.status_4xx, 'var(--warning)'], ['5xx', s.status_5xx, 'var(--error)'],
        ];
        if (!total) return FC.empty(el, 'No requests in this period');
        el.innerHTML = '<div class="split"><div class="split__bar">' +
            parts.filter(p => p[1]).map(p => '<i style="width:' + (p[1] / total * 100) + '%;background:' + p[2] + '"></i>').join('') +
            '</div><div class="split__legend">' +
            parts.map(p => '<span><span class="swatch" style="background:' + p[2] + '"></span>' + p[0] + ' <b>' + FC.num(p[1]) + '</b> · ' + FC.pct(p[1] / total * 100) + '</span>').join('') +
            '</div></div>';
    };

    // Имя строки «Who Visits»: люди — зелёные, боты — серые.
    FC.trafficLabel = function (item) {
        return item.people
            ? '<i class="fas fa-user who-icon who-icon--people"></i>' + FC.escape(item.label || item.key)
            : '<i class="fas fa-robot who-icon who-icon--bots"></i>' + FC.escape(item.label || item.key);
    };

    // Вторая строка у адреса: сеть и класс («Kar-Tel LLC · People»).
    FC.ipSub = function (item) {
        return [item.network, item.traffic_label].filter(Boolean).map(FC.escape).join(' · ');
    };

    FC.trafficNote = function (traffic, partial) {
        if (!traffic || traffic === 'all') return '';
        return (traffic === 'people' ? ' · people only' : ' · bots only') +
            (partial ? ' (traffic filter covers the last 30 days)' : '');
    };

    global.FC = FC;
})(window);
