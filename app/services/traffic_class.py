"""Кто прислал запрос: человек, поисковик, скрипт, сканер или браузер из дата-центра.

До 24.09.2026 аналитика делила трафик только по User-Agent, и в «Chrome» и
«Safari» попадало всё, что так представляется. У lampwork.dev за первые
сутки из 4 704 запросов людей со стороны было около сотни: остальное —
сканеры `.env`, SEO- и ИИ-краулеры, превью ссылок и браузеры, запущенные
на серверах AWS, Google Cloud, OVH и Vultr.

Класс ставится при приёме строки (``classify``) по трём признакам:

* User-Agent: объявленные боты по видам, библиотеки и headless-браузеры;
* путь: запросы к ``/.env``, ``/.git/config``, ``wp-login.php``, получившие
  4xx, — это сканер уязвимостей. Сайт на WordPress отдаёт свои пути с 200
  и сканером не считается;
* сеть: браузер из сети хостинга (ASN из GeoLite2-ASN) — ``hosted``. Это
  либо бот под видом браузера, либо человек через VPN. Кто из них кто,
  видно по поведению, и ``refine`` в своде раз в 5 минут переводит тех,
  кто листает страницы как человек, в ``vpn``.

Запросы мобильных приложений к своему API (Happ, Reshu, Telegram) с домашних
и мобильных сетей — ``app``: за ними тоже люди. Те же библиотеки с серверов —
``tool``.

«Люди» в фильтре аналитики — ``human``, ``vpn`` и ``app``, всё остальное — боты.
"""
from __future__ import annotations

import re
from typing import Optional

HUMAN = "human"
VPN = "vpn"
APP = "app"
HOSTED = "hosted"
SEARCH = "search"
AI = "ai"
SEO = "seo"
PREVIEW = "preview"
MONITOR = "monitor"
ARCHIVE = "archive"
BOT = "bot"
TOOL = "tool"
SCANNER = "scanner"

PEOPLE = (HUMAN, VPN, APP)
# Объявленные боты: их классы не трогает пересмотр по поведению.
DECLARED = (SEARCH, AI, SEO, PREVIEW, MONITOR, ARCHIVE)

LABELS = {
    HUMAN: "People",
    VPN: "People via VPN or proxy",
    APP: "Mobile apps",
    HOSTED: "Browsers in data centers",
    SEARCH: "Search engines",
    AI: "AI crawlers",
    SEO: "SEO crawlers",
    PREVIEW: "Link previews",
    MONITOR: "Monitoring",
    ARCHIVE: "Web archives",
    BOT: "Other bots",
    TOOL: "Scripts and headless browsers",
    SCANNER: "Vulnerability scanners",
}


def _rx(*parts: str) -> re.Pattern:
    return re.compile("|".join(parts), re.I)


# Порядок важен: GPTBot — это ИИ, а не «прочий бот», у превью Telegram в
# User-Agent есть «TwitterBot».
_SCANNER_UA = _rx(
    r"zgrab", r"masscan", r"nuclei", r"nmap", r"nikto", r"sqlmap", r"censys",
    r"expanse", r"palo alto", r"internetmeasurement", r"onyphe", r"netcraft",
    r"l9explore", r"l9tcpid", r"shodan", r"bitsight", r"modat", r"odin\b",
    r"leakix", r"httpx - open-source", r"wpscan", r"dirbuster", r"gobuster", r"ffuf",
)
_AI_UA = _rx(
    r"GPTBot", r"OAI-SearchBot", r"ChatGPT-User", r"ClaudeBot", r"Claude-User",
    r"Claude-SearchBot", r"anthropic-ai", r"PerplexityBot", r"Perplexity-User",
    r"Amazonbot", r"CCBot", r"Bytespider", r"meta-externalagent", r"meta-externalfetcher",
    r"Google-Extended", r"cohere-ai", r"Diffbot", r"YouBot", r"MistralAI",
    r"DeepSeekBot", r"Timpibot", r"ImagesiftBot", r"Kangaroo Bot", r"PanguBot",
    r"AI2Bot", r"Applebot-Extended", r"DuckAssistBot", r"GrokBot", r"xAI-",
)
_SEARCH_UA = _rx(
    r"Googlebot", r"Google-InspectionTool", r"GoogleOther", r"Google-Site-Verification",
    r"Storebot-Google", r"AdsBot-Google", r"Mediapartners-Google", r"FeedFetcher-Google",
    r"Google-Read-Aloud", r"APIs-Google", r"Google-Safety",
    # Приложение Яндекса и Яндекс Браузер — люди: YandexSearch/, YaBrowser/, YaApp.
    r"\bYandex(?!Search)[A-Z][A-Za-z]*/\d", r"YaDirectFetcher",
    r"bingbot", r"BingPreview", r"msnbot", r"adidxbot", r"Applebot", r"DuckDuckBot",
    r"Baiduspider", r"SeznamBot", r"PetalBot", r"Mail\.RU_Bot", r"coccocbot",
    r"Qwantbot", r"Yeti/", r"Sogou", r"MojeekBot", r"Exabot", r"YisouSpider",
)
_SEO_UA = _rx(
    r"AhrefsBot", r"AhrefsSiteAudit", r"SemrushBot", r"SiteAuditBot", r"MJ12bot",
    r"DotBot", r"DataForSeoBot", r"BLEXBot", r"serpstatbot", r"MegaIndex", r"Barkrowler",
    r"Screaming Frog", r"Sitebulb", r"rogerbot", r"linkdexbot", r"SEOkicks",
    r"trendictionbot", r"SERanking", r"Linkfluence", r"SEOlyticsCrawler", r"Seekport",
)
_PREVIEW_UA = _rx(
    r"TelegramBot", r"WhatsApp", r"facebookexternalhit", r"Facebot",
    r"Twitterbot", r"Slackbot", r"Slack-ImgProxy", r"Discordbot", r"LinkedInBot",
    r"vkShare", r"OdklBot", r"SkypeUriPreview", r"redditbot", r"Iframely", r"Embedly",
    r"Viber", r"Pinterestbot", r"MAX-preview", r"Snap URL Preview", r"Mastodon/",
    r"Bluesky", r"Google-PageRenderer", r"YandexMessenger",
)
_MONITOR_UA = _rx(
    r"UptimeRobot", r"Pingdom", r"StatusCake", r"Better ?Uptime", r"Site24x7",
    r"Uptime-?Kuma", r"Zabbix", r"Prometheus", r"blackbox", r"NewRelicPinger",
    r"Datadog", r"Checkly", r"HetrixTools", r"Freshping", r"updown\.io", r"GTmetrix",
    r"Chrome-Lighthouse", r"Lighthouse", r"PTST/", r"PageSpeed", r"Uptime",
)
# HTTP-клиенты мобильных приложений: на телефоне это человек, на сервере — скрипт.
_APP_UA = _rx(
    r"CFNetwork/", r"^Dalvik/", r"okhttp/", r"^Telegram/", r"Telegram-Android/",
    r"^Happ/", r"^Reshu/", r"^Streisand/", r"^v2rayNG", r"^Hiddify", r"^FoXray", r"^V2Box",
    r"^Shadowrocket", r"^Karing", r"^sing-box", r"^clash", r"^Stash/", r"^Surge",
)
_ARCHIVE_UA = _rx(r"archive\.org", r"ia_archiver", r"Wayback", r"heritrix", r"Arquivo")
_TOOL_UA = _rx(
    r"^curl", r"^Wget", r"python-", r"^python", r"httpx", r"aiohttp",
    r"Go-http-client", r"^Java/", r"Apache-HttpClient", r"libwww", r"node-fetch",
    r"axios", r"undici", r"^node", r"Scrapy", r"HeadlessChrome", r"PhantomJS",
    r"Puppeteer", r"Playwright", r"Electron/.*Headless", r"^Ruby", r"^PHP", r"Guzzle",
    r"WinHttp", r"^Mozilla/5\.0$", r"NSPlayer",
    r"Postman", r"Insomnia", r"^HTTPie", r"reqwest", r"^Faraday", r"RestSharp",
)
# «Бот вообще»: слово с версией (Somethingbot/1.0) или адрес для связи в UA.
# Не голое «bot» — у телефонов CUBOT оно стоит в модели.
_BOT_UA = _rx(
    r"(bot|crawl|spider|slurp|fetcher|scraper)[\w.-]*/\d",
    r"\+https?://", r"compatible;[^)]*(bot|crawler|spider)",
)
# У настоящего браузера в UA есть движок с версией.
_BROWSER_UA = _rx(
    r"Chrome/\d", r"CriOS/\d", r"Firefox/\d", r"FxiOS/\d", r"Version/\d[^ ]* (Mobile/\S+ )?Safari/",
    r"Edg[A-Z]?/\d", r"OPR/\d", r"YaBrowser/\d", r"Mobile/\d+[A-Z]\d+", r"Trident/",
)

# Пути, которые спрашивают только сканеры. Считаются, если сайт ответил 4xx:
# сайт на WordPress отдаёт свои wp-пути с 200, и его посетители — не сканеры.
_PROBE_PATH = _rx(
    r"^/\.(env|git|aws|ssh|svn|hg|DS_Store|vscode|idea|htaccess|htpasswd|npmrc|docker)",
    r"/\.env(\.|$)", r"/\.git/",
    r"^/(wp-(admin|login|config|content|includes)|wordpress|xmlrpc\.php)",
    r"^/(phpmyadmin|pma|myadmin|mysql|adminer|cgi-bin|actuator|server-status|solr|jenkins)",
    r"^/vendor/phpunit", r"\.php\d?$", r"\.(sql|bak|old|swp|tar|tgz|rar|7z)$",
    r"^/(backup|dump|db)\.(zip|gz|sql)",
)


def is_probe(path: Optional[str], status: Optional[int]) -> bool:
    """Запрос к пути сканера, на который сайт ответил ошибкой."""
    if not path or status is None or not 400 <= status < 500:
        return False
    return bool(_PROBE_PATH.search(path))


def ua_class(user_agent: Optional[str]) -> Optional[str]:
    """Класс по одному User-Agent; None — похоже на обычный браузер."""
    ua = (user_agent or "").strip()
    if not ua or ua == "-":
        return TOOL
    for pattern, cls in (
        (_SCANNER_UA, SCANNER),
        (_AI_UA, AI),
        (_SEARCH_UA, SEARCH),
        (_SEO_UA, SEO),
        (_PREVIEW_UA, PREVIEW),
        (_ARCHIVE_UA, ARCHIVE),
        (_MONITOR_UA, MONITOR),
        (_APP_UA, APP),
        (_TOOL_UA, TOOL),
        (_BOT_UA, BOT),
    ):
        if pattern.search(ua):
            return cls
    if not _BROWSER_UA.search(ua):
        # «Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36» без
        # версии браузера — обрезанный UA из скрипта.
        return TOOL
    return None


def classify(
    user_agent: Optional[str],
    path: Optional[str],
    status: Optional[int],
    hosting: bool,
) -> str:
    """Класс строки лога при приёме (``hosting`` — адрес из сети хостинга)."""
    if is_probe(path, status):
        return SCANNER
    cls = ua_class(user_agent)
    if cls == APP and hosting:
        return TOOL
    if cls:
        return cls
    return HOSTED if hosting else HUMAN
