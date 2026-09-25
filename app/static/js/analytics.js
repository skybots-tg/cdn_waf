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

    FC.flag = function (code) {
        if (!code || !/^[A-Za-z]{2}$/.test(code)) return '🏳️';
        return String.fromCodePoint(...code.toUpperCase().split('').map(c => 0x1F1E6 + c.charCodeAt(0) - 65));
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

    // Список «значение — доля — число» с полоской, как топы у Cloudflare.
    // format(item) → HTML подписи; value(item) → число справа.
    FC.renderTop = function (el, items, opts) {
        opts = opts || {};
        if (!el) return;
        if (!items || !items.length) return FC.empty(el, opts.emptyText);
        const field = (COUNT_UNITS[opts.metric] || COUNT_UNITS.requests)[0];
        const size = i => (i[field] != null ? i[field] : i.requests) || 0;
        const max = Math.max(...items.map(size), 1);
        el.innerHTML = items.map(function (item) {
            const label = opts.format ? opts.format(item) : FC.escape(item.key == null ? '—' : item.key);
            const width = Math.max(2, Math.round(size(item) / max * 100));
            const right = opts.value ? opts.value(item) : FC.num(item.requests);
            const pct = item.percentage != null ? '<span style="color:var(--text-muted);font-size:12px;margin-left:8px;">' + FC.pct(item.percentage) + '</span>' : '';
            return '<div style="margin-bottom:10px;">' +
                '<div class="flex-between" style="gap:12px;font-size:14px;">' +
                '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;" title="' + FC.escape(item.key) + '">' + label + '</span>' +
                '<span style="font-weight:600;white-space:nowrap;">' + right + pct + '</span></div>' +
                '<div style="height:4px;background:var(--bg-tertiary);border-radius:2px;margin-top:4px;">' +
                '<div style="height:4px;width:' + width + '%;background:' + (opts.color || 'var(--accent-primary)') + ';border-radius:2px;"></div></div></div>';
        }).join('') + (opts.partial ? '<p style="font-size:12px;color:var(--text-muted);margin-top:8px;">Raw logs are kept for 30 days — this list covers the last 30 days.</p>' : '');
    };

    // График «всего / из кэша» по шагам периода (Chart.js).
    FC.trafficChart = function (canvas, previous, data, metric) {
        if (previous) previous.destroy();
        const isBytes = metric === 'bandwidth';
        const labels = data.timestamps.map(t => FC.bucketLabel(t, data.bucket));
        const styles = getComputedStyle(document.documentElement);
        const accent = styles.getPropertyValue('--accent-primary').trim() || '#f38020';
        const success = styles.getPropertyValue('--success').trim() || '#10b981';
        const line = (label, values, color) => ({
            label: label, data: values, borderColor: color, backgroundColor: color + '22',
            fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2,
        });
        // Просмотры и посетители — одна линия; у запросов и трафика — ещё «из кэша».
        const single = { visits: 'Visits', page_views: 'Page views', visitors: 'Unique visitors (IP)' }[metric];
        const datasets = single
            ? [line(single, data.series[metric] || [], accent)]
            : [
                line(isBytes ? 'Total bandwidth' : 'Total requests', isBytes ? data.series.bandwidth : data.series.requests, accent),
                line(isBytes ? 'Served from cache' : 'Cached requests', isBytes ? data.series.cached_bandwidth : data.series.cached_requests, success),
            ];
        return new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: labels,
                datasets: datasets,
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { display: true, labels: { boxWidth: 12 } },
                    tooltip: { callbacks: { label: c => c.dataset.label + ': ' + (isBytes ? FC.bytes(c.parsed.y) : FC.num(c.parsed.y)) } },
                },
                scales: {
                    x: { ticks: { maxTicksLimit: 10, autoSkip: true }, grid: { display: false } },
                    y: { beginAtZero: true, ticks: { callback: v => isBytes ? FC.bytes(v) : FC.num(v) } },
                },
            },
        });
    };

    FC.rangeLabel = function (range) {
        return ({ '1h': 'last hour', '24h': 'last 24 hours', '7d': 'last 7 days', '30d': 'last 30 days',
                  '90d': 'last 90 days', '6m': 'last 6 months' })[range] || range;
    };

    // Период в адресе (?range=7d): страницу можно обновить или переслать.
    FC.initRange = function (select, onChange) {
        const params = new URLSearchParams(window.location.search);
        const saved = params.get('range') || localStorage.getItem('analytics_range');
        if (saved && [...select.options].some(o => o.value === saved)) select.value = saved;
        select.addEventListener('change', function () {
            try { localStorage.setItem('analytics_range', select.value); } catch (e) { /* приватный режим */ }
            const p = new URLSearchParams(window.location.search);
            p.set('range', select.value);
            history.replaceState(null, '', window.location.pathname + '?' + p.toString());
            onChange(select.value);
        });
        return select.value;
    };

    // Фильтр «кто прислал запрос» (?traffic=people): all — всё, people — люди,
    // bots — боты. Классы считает панель (app/services/traffic_class.py).
    FC.initTraffic = function (select, onChange) {
        const params = new URLSearchParams(window.location.search);
        let saved = params.get('traffic');
        try { saved = saved || localStorage.getItem('analytics_traffic'); } catch (e) { /* приватный режим */ }
        if (saved && [...select.options].some(o => o.value === saved)) select.value = saved;
        select.addEventListener('change', function () {
            try { localStorage.setItem('analytics_traffic', select.value); } catch (e) { /* приватный режим */ }
            const p = new URLSearchParams(window.location.search);
            if (select.value === 'all') p.delete('traffic'); else p.set('traffic', select.value);
            const query = p.toString();
            history.replaceState(null, '', window.location.pathname + (query ? '?' + query : ''));
            onChange(select.value);
        });
        return select.value;
    };

    // Что считают топы (?count=visitors): уникальные IP, просмотры страниц
    // или запросы. Одна страница — это десятки запросов за CSS и картинками.
    FC.initCount = function (select, onChange) {
        const params = new URLSearchParams(window.location.search);
        let saved = params.get('count');
        try { saved = saved || localStorage.getItem('analytics_count'); } catch (e) { /* приватный режим */ }
        if (saved && [...select.options].some(o => o.value === saved)) select.value = saved;
        select.addEventListener('change', function () {
            try { localStorage.setItem('analytics_count', select.value); } catch (e) { /* приватный режим */ }
            const p = new URLSearchParams(window.location.search);
            p.set('count', select.value);
            history.replaceState(null, '', window.location.pathname + '?' + p.toString());
            onChange(select.value);
        });
        return select.value;
    };

    const COUNT_UNITS = {
        visits: ['visits', 'visits'], visitors: ['visitors', 'IP'],
        views: ['views', 'views'], requests: ['requests', 'req'],
    };

    // Число справа в строке топа: выбранная метрика крупно, остальные мелко.
    FC.countValue = function (metric, opts) {
        opts = opts || {};
        return function (item) {
            const order = [metric].concat(['visits', 'visitors', 'views', 'requests'].filter(m => m !== metric))
                .filter(m => !(opts.skip || []).includes(m) && item[COUNT_UNITS[m][0]] != null);
            const text = m => FC.num(item[COUNT_UNITS[m][0]]) + ' ' + COUNT_UNITS[m][1];
            const rest = order.slice(1).map(text).join(' · ');
            return text(order[0]) + (rest ? ' <span style="color:var(--text-muted);font-weight:400;font-size:12px;">· ' + rest + '</span>' : '');
        };
    };

    // Время визита «1:05» (секунды → минуты:секунды), как в Метрике.
    FC.duration = function (seconds) {
        if (seconds == null) return '—';
        const s = Math.round(Number(seconds) || 0);
        return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
    };

    // Подпись под визитами: отказы, глубина, время — по сырым логам.
    FC.visitStats = function (s) {
        if (!s.visits) return 'Page views with less than 30 min between them';
        return FC.pct(s.bounce_rate) + ' bounce · ' + (s.visit_depth || 0).toFixed(1) + ' pages · ' + FC.duration(s.visit_duration);
    };

    // Строка топа «Who Visits»: люди — зелёные, боты — серые.
    FC.trafficLabel = function (item) {
        const icon = item.people
            ? '<i class="fas fa-user" style="color:var(--success);width:16px;"></i>'
            : '<i class="fas fa-robot" style="color:var(--text-muted);width:16px;"></i>';
        return icon + ' ' + FC.escape(item.label || item.key);
    };

    // Адрес с сетью и классом: «37.99.96.137 · Kar-Tel LLC · People».
    FC.ipLabel = function (item) {
        const parts = [item.network, item.traffic_label].filter(Boolean).map(FC.escape);
        return '<span class="mono">' + FC.escape(item.key) + '</span>' +
            (parts.length ? ' <span style="color:var(--text-muted);font-size:12px;">' + parts.join(' · ') + '</span>' : '');
    };

    FC.trafficNote = function (traffic, partial) {
        if (!traffic || traffic === 'all') return '';
        return (traffic === 'people' ? ' · people only' : ' · bots only') +
            (partial ? ' (traffic filter covers the last 30 days)' : '');
    };

    global.FC = FC;
})(window);
