"""Тесты разного ответа DNS для России и мира (app/geo_split.py).

Главное, что здесь сторожится: российский клиент получает ноды, как раньше;
в сомнительных случаях — тоже ноды; имена вне GEO_SPLIT_NAMES не трогаются; и
если ответ зависел от подсети клиента, ECS возвращается с областью — иначе
Google закэшировал бы «зарубежный» ответ для всей России.
"""
import ipaddress

import pytest
from dnslib import EDNS0, EDNSOption, QTYPE, DNSRecord

from app import geo_split

RU_ISP = "95.24.0.1"        # Билайн, Москва
RU_MTS = "83.149.0.10"      # МТС
FOREIGN = "149.154.161.246"  # Telegram, робот превью
GOOGLE_NL = "74.125.47.1"    # резолвер Google вне России


@pytest.fixture(autouse=True)
def split_names(monkeypatch):
    monkeypatch.setenv("GEO_SPLIT_NAMES", "perek.us, www.perek.us.")


def query(name="perek.us", ecs=None):
    q = DNSRecord.question(name, "A")
    if ecs is not None:
        net = ipaddress.ip_network(ecs, strict=False)
        family = 1 if net.version == 4 else 2
        packed = net.network_address.packed[: (net.prefixlen + 7) // 8]
        q.add_ar(EDNS0(opts=[EDNSOption(8, family.to_bytes(2, "big") + bytes([net.prefixlen, 0]) + packed)]))
    return DNSRecord.parse(q.pack())


def test_table_knows_russia():
    assert geo_split.is_russia(RU_ISP) is True
    assert geo_split.is_russia(RU_MTS) is True
    assert geo_split.is_russia(FOREIGN) is False
    assert geo_split.is_russia("10.0.0.1") is None       # частный — не знаем
    assert geo_split.is_russia("не адрес") is None


def test_names_from_env():
    assert geo_split.names() == {"perek.us", "www.perek.us"}


def test_other_names_untouched():
    assert geo_split.decide("app.perek.us", query("app.perek.us"), FOREIGN) is None
    assert geo_split.decide("skybots.ru", query("skybots.ru"), FOREIGN) is None


def test_ecs_roundtrip_v4():
    ecs = geo_split.parse_ecs(query(ecs="95.24.0.0/24"))
    assert (ecs.family, ecs.source, ecs.address) == (1, 24, "95.24.0.0")
    opt = ecs.reply_option()
    assert opt.code == 8 and bytes(opt.data) == bytes([0, 1, 24, 24, 95, 24, 0])


def test_ecs_v6_and_zero_source():
    ecs = geo_split.parse_ecs(query(ecs="2a02:6b8::/56"))
    assert ecs.family == 2 and ecs.source == 56
    zero = geo_split.parse_ecs(query(ecs="0.0.0.0/0"))
    assert zero.source == 0 and bytes(zero.reply_option().data) == bytes([0, 1, 0, 0])


def test_russian_client_behind_foreign_google_gets_edges():
    d = geo_split.decide("perek.us", query(ecs="95.24.0.0/24"), GOOGLE_NL)
    assert d.russia is True and d.ecs is not None


def test_foreign_client_by_ecs_gets_origin():
    d = geo_split.decide("perek.us", query(ecs="149.154.160.0/24"), GOOGLE_NL)
    assert d.russia is False


def test_foreign_resolver_without_ecs_gets_origin():
    assert geo_split.decide("www.perek.us", query("www.perek.us"), FOREIGN).russia is False


def test_russian_resolver_without_ecs_gets_edges():
    assert geo_split.decide("perek.us", query(), RU_MTS).russia is True


def test_unknown_goes_to_edges():
    assert geo_split.decide("perek.us", query(), None).russia is True
    assert geo_split.decide("perek.us", query(), "127.0.0.1").russia is True


def test_zero_source_ecs_falls_back_to_resolver():
    assert geo_split.decide("perek.us", query(ecs="0.0.0.0/0"), FOREIGN).russia is False
    assert geo_split.decide("perek.us", query(ecs="0.0.0.0/0"), RU_ISP).russia is True


def test_reply_carries_ecs_scope():
    q = query(ecs="95.24.0.0/24")
    reply = q.reply()
    geo_split.add_ecs(reply, geo_split.decide("perek.us", q, GOOGLE_NL))
    parsed = DNSRecord.parse(reply.pack())
    opts = [o for rr in parsed.ar if rr.rtype == QTYPE.OPT for o in rr.rdata]
    assert [bytes(o.data) for o in opts if o.code == 8] == [bytes([0, 1, 24, 24, 95, 24, 0])]


def test_no_ecs_no_opt_in_reply():
    q = query()
    reply = q.reply()
    geo_split.add_ecs(reply, geo_split.decide("perek.us", q, FOREIGN))
    assert not DNSRecord.parse(reply.pack()).ar


def test_empty_setting_changes_nothing(monkeypatch):
    monkeypatch.setenv("GEO_SPLIT_NAMES", "")
    assert geo_split.decide("perek.us", query(), FOREIGN) is None


def test_echo_ecs_scope_zero_for_any_name():
    q = query("skybots.ru", ecs="95.24.0.0/24")
    reply = q.reply()
    geo_split.echo_ecs(q, reply)
    opts = [o for rr in DNSRecord.parse(reply.pack()).ar if rr.rtype == QTYPE.OPT for o in rr.rdata]
    assert [bytes(o.data) for o in opts if o.code == 8] == [bytes([0, 1, 24, 0, 95, 24, 0])]


def test_echo_keeps_split_scope():
    q = query(ecs="95.24.0.0/24")
    reply = q.reply()
    geo_split.add_ecs(reply, geo_split.decide("perek.us", q, GOOGLE_NL))
    geo_split.echo_ecs(q, reply)
    opts = [o for rr in DNSRecord.parse(reply.pack()).ar if rr.rtype == QTYPE.OPT for o in rr.rdata]
    assert [bytes(o.data) for o in opts if o.code == 8] == [bytes([0, 1, 24, 24, 95, 24, 0])]


def test_echo_without_ecs_adds_nothing():
    q = query("skybots.ru")
    reply = q.reply()
    geo_split.echo_ecs(q, reply)
    assert not DNSRecord.parse(reply.pack()).ar
