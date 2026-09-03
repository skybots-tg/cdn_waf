"""
Тесты применения сертификатов на edge-ноде.

Здесь проверяется ровно один сценарий, который однажды уже стоил домену
рабочего HTTPS: сертификат продлили, файлы на диске обновились, а nginx-конфиг
остался байт в байт прежним. Агент сравнивал только текст конфига, пропускал
reload — и nginx продолжал отдавать из памяти старый сертификат до тех пор,
пока кто-нибудь не менял конфигурацию по другой причине.
"""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "edge_node"))

# Агент живёт на edge-нодах и тянет их зависимости (aiofiles, psutil); на
# control plane, где гоняются тесты, их нет и быть не должно. Проверяемая
# логика — запись файлов и решение о reload — ни одну из них не трогает,
# поэтому недостающие подменяем заглушками, а установленные оставляем как есть.
for _name in ("aiofiles", "psutil"):
    try:
        __import__(_name)
    except ImportError:
        _stub = types.ModuleType(_name)
        _stub.__getattr__ = lambda attr: MagicMock()  # noqa: B023
        sys.modules[_name] = _stub

from edge_config_updater import EdgeConfigUpdater  # noqa: E402


def _updater(tmp_path: Path) -> EdgeConfigUpdater:
    """Экземпляр без чтения config.yaml — нужны только поля, что трогает тест."""
    agent = object.__new__(EdgeConfigUpdater)
    agent.certs_dir = tmp_path / "ssl"
    agent.nginx_config_path = tmp_path / "cdn.conf"
    agent.current_version = 1
    agent.certificates_changed = False
    return agent


# ── запись файлов ────────────────────────────────────────────────────

def test_write_reports_change_for_new_file(tmp_path):
    agent = _updater(tmp_path)
    target = tmp_path / "ssl" / "example.com.crt"

    assert agent._write_if_changed(target, "PEM-1") is True
    assert target.read_text() == "PEM-1"


def test_write_reports_no_change_for_same_content(tmp_path):
    agent = _updater(tmp_path)
    target = tmp_path / "ssl" / "example.com.crt"
    agent._write_if_changed(target, "PEM-1")

    assert agent._write_if_changed(target, "PEM-1") is False


def test_write_reports_change_when_content_differs(tmp_path):
    agent = _updater(tmp_path)
    target = tmp_path / "ssl" / "example.com.crt"
    agent._write_if_changed(target, "PEM-1")

    assert agent._write_if_changed(target, "PEM-2") is True
    assert target.read_text() == "PEM-2"


def test_key_permissions_are_fixed_even_without_change(tmp_path):
    """Ключ мог приехать из бэкапа с чужой маской — права правим всегда."""
    agent = _updater(tmp_path)
    target = tmp_path / "ssl" / "example.com.key"
    agent._write_if_changed(target, "KEY", mode=0o600)
    target.chmod(0o644)

    assert agent._write_if_changed(target, "KEY", mode=0o600) is False
    assert target.stat().st_mode & 0o777 == 0o600


# ── решение о перезагрузке ───────────────────────────────────────────

class _Recorder:
    """Мок update_config'а: подменяет всё, кроме проверяемой логики."""

    def __init__(self, agent, nginx_config: str, certificates_changed: bool):
        self.agent = agent
        self.nginx_config = nginx_config
        self.certificates_changed = certificates_changed
        self.reloads = 0

        async def fetch_config():
            return {"version": 2, "domains": []}

        async def process_certificates(config):
            agent.certificates_changed = self.certificates_changed
            return config

        def generate_nginx_config(config):
            return self.nginx_config

        def reload_nginx():
            self.reloads += 1
            return True

        agent.fetch_config = fetch_config
        agent.process_certificates = process_certificates
        agent.generate_nginx_config = generate_nginx_config
        agent.reload_nginx = reload_nginx
        agent.backup_config = lambda: None


@pytest.mark.asyncio
async def test_identical_config_and_certs_skips_reload(tmp_path):
    agent = _updater(tmp_path)
    agent.nginx_config_path.write_text("# Version: 1\nserver {}\n")
    rec = _Recorder(agent, "# Version: 2\nserver {}\n", certificates_changed=False)

    await agent.update_config()

    assert rec.reloads == 0
    assert agent.current_version == 2


@pytest.mark.asyncio
async def test_new_certificate_reloads_even_with_identical_config(tmp_path):
    """Тот самый случай продления: конфиг прежний, сертификат новый."""
    agent = _updater(tmp_path)
    agent.nginx_config_path.write_text("# Version: 1\nserver {}\n")
    rec = _Recorder(agent, "# Version: 2\nserver {}\n", certificates_changed=True)

    await agent.update_config()

    assert rec.reloads == 1
    assert agent.current_version == 2
    # Конфиг не переписывали: менять там нечего.
    assert agent.nginx_config_path.read_text().startswith("# Version: 1")


@pytest.mark.asyncio
async def test_changed_config_is_written_and_reloaded(tmp_path):
    agent = _updater(tmp_path)
    agent.nginx_config_path.write_text("# Version: 1\nserver {}\n")
    rec = _Recorder(agent, "# Version: 2\nserver { listen 443; }\n", certificates_changed=False)

    await agent.update_config()

    assert rec.reloads == 1
    assert "listen 443" in agent.nginx_config_path.read_text()
