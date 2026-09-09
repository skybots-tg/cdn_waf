"""Proxied aliases must use stored origins, never the public CDN address."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.api.internal import _dns_origin, _resolve_cname_origins, get_edge_config
from app.models.certificate import Certificate
from app.models.dns import DNSRecord
from app.models.domain import Domain
from app.models.origin import Origin


def record(name, content, kind="CNAME", proxied=True, ident=1, weight=100):
    return SimpleNamespace(name=name, content=content, type=kind, proxied=proxied,
                           id=ident, weight=weight)


def resolve(alias, records, mapped=None):
    return _resolve_cname_origins(alias, "example.com", records, mapped or {})


def test_alias_preserves_explicit_origin_settings_and_does_not_mutate_them():
    alias = record("www", "EXAMPLE.COM.")
    explicit = {"host": "198.51.100.9", "port": 8443, "protocol": "https",
                "id": 42, "weight": 20, "is_backup": True}
    result = resolve(alias, [alias], {"@": [explicit]})
    assert result == [explicit]
    assert result[0] is not explicit


def test_chain_resolves_dns_only_target_and_all_weighted_addresses():
    records = [record("www", "alias.example.com"),
               record("alias", "origin.example.com.", proxied=False, ident=2),
               record("origin", "198.51.100.10", "A", False, 3, 25),
               record("origin", "198.51.100.11", "A", False, 4, 75)]
    assert resolve(records[0], records) == [_dns_origin(r) for r in records[2:]]


@pytest.mark.parametrize("target", ["missing.example.com", "outside.test",
                                   "example.com.attacker.test", "www.example.com"])
def test_missing_external_and_self_referential_targets_fail_closed(target):
    alias = record("www", target)
    assert resolve(alias, [alias]) == []


def test_cycle_fails_closed():
    records = [record("www", "alias.example.com"),
               record("alias", "www.example.com", ident=2)]
    assert resolve(records[0], records) == []


def test_chain_length_is_bounded():
    records = [record(f"c{i}", f"c{i+1}.example.com", ident=i+1) for i in range(20)]
    records.append(record("c20", "198.51.100.10", "A", ident=30))
    assert resolve(records[0], records) == []


def test_apex_alias_does_not_route_back_to_itself():
    alias = record("@", "example.com")
    assert resolve(alias, [alias], {"@": [{"host": "198.51.100.10"}]}) == []


class ConfigDB:
    """SQL-aware read-only fixture: respects the DNS type selection predicate."""
    def __init__(self, records):
        self.records = records

    async def execute(self, query):
        model = query.column_descriptions[0]["entity"]
        params = query.compile().params
        rows = []
        if model is Domain:
            rows = [SimpleNamespace(id=2, name="example.com")]
        elif model is DNSRecord:
            kinds = params["type_1"]
            kinds = kinds if isinstance(kinds, list) else [kinds]
            rows = [r for r in self.records if r.type in kinds]
        elif model is Origin:
            rows = []
        elif model is Certificate:
            cert_id = {"example.com": 1, "www.example.com": 2}.get(params["common_name_1"])
            rows = [SimpleNamespace(id=cert_id)] if cert_id else []
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        result.scalar_one_or_none.return_value = rows[0] if rows else None
        return result


@pytest.mark.asyncio
async def test_full_config_includes_alias_and_its_own_certificate_without_changing_apex():
    apex = record("@", "198.51.100.10", "A", ident=1)
    www = record("www", "example.com", ident=66)
    dns_only = record("direct", "example.com", proxied=False, ident=67)
    external = record("mail", "mail.external.test.", ident=68)
    node = SimpleNamespace(id=6, name="test-edge", location_code="TEST", config_version=8)

    config = await get_edge_config(node=node, db=ConfigDB([apex, www, dns_only, external]))
    domains = {d["name"]: d for d in config["domains"]}
    assert set(domains) == {"example.com", "www.example.com"}
    assert domains["example.com"]["origins"] == [_dns_origin(apex)]
    assert domains["www.example.com"]["origins"] == domains["example.com"]["origins"]
    assert domains["example.com"]["tls"]["certificate_id"] == 1
    assert domains["www.example.com"]["tls"]["certificate_id"] == 2
    assert domains["www.example.com"]["tls"]["enabled"] is True


@pytest.mark.asyncio
async def test_same_version_still_skips_configuration_regeneration():
    node = SimpleNamespace(config_version=8)
    assert await get_edge_config(version=8, node=node, db=None) == {
        "version": 8, "changed": False,
    }
