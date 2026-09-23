"""
Скрипты страниц не должны объявлять глобальные имена, уже занятые main.js.

main.js подключается в base.html ПОСЛЕ скриптов страницы. Совпавшая функция
молча подменяет страничную (23.09.2026: «renderDomains» из main.js рисовал
не ту таблицу, и списки доменов на экранах аналитики, CDN и WAF висели на
«Loading…»; «getStatusBadge» показывал у нод «info» вместо статуса), а
совпавший const/class роняет весь main.js с SyntaxError (константа API на
странице аналитики домена — и на ней не работали ни подстановка токена, ни
общие помощники).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN_JS = ROOT / "app" / "static" / "js" / "main.js"

_DECL = re.compile(
    r"^\s*(?:async\s+)?function\s+([A-Za-z0-9_$]+)|^(?:const|let|var|class)\s+([A-Za-z0-9_$]+)",
    re.M,
)

# Совпадения, которые были до этой проверки: страницы настроек и DNS
# дублируют функции main.js. Новых сюда не добавлять — переименовать.
KNOWN = {
    "settings.html": {
        "closeModal", "copyAPIKey", "createAPIKey", "deleteAPIKey", "getToken",
        "removeMember", "showCreateAPIKeyModal", "showInviteMemberModal",
    },
    "dns_management.html": {"loadDomains"},
    # Те же помощники, что в main.js, по смыслу одинаковые.
    "edge_nodes.js": {"getToken"},
    "dns_nodes.js": {"getToken"},
    "domain_settings.js": {"closeModal", "getToken"},
}


def _names(text):
    return {a or b for a, b in _DECL.findall(text)}


def test_page_scripts_do_not_shadow_main_js():
    main_names = _names(MAIN_JS.read_text(encoding="utf-8"))
    sources = list((ROOT / "app" / "templates").glob("*.html"))
    sources += [p for p in (ROOT / "app" / "static" / "js").glob("*.js") if p.name != "main.js"]
    clashes = {}
    for path in sources:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".html":
            text = "\n".join(re.findall(r"<script>(.*?)</script>", text, re.S))
        clash = (_names(text) & main_names) - KNOWN.get(path.name, set())
        if clash:
            clashes[path.name] = sorted(clash)
    assert not clashes, f"имена уже объявлены в main.js: {clashes}"
