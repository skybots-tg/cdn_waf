"""Tenant-input validation: valid values pass, injection/traversal is rejected."""
import pytest
from pydantic import ValidationError

from app.schemas.domain import DomainCreate
from app.schemas.cdn import OriginCreate, CacheRuleCreate
from app.schemas.dns import DNSRecordCreate
from app.schemas.waf import WAFRuleCreate, IPAccessRuleCreate


def test_valid_inputs_accepted():
    assert DomainCreate(name="Example.COM").name == "example.com"
    assert OriginCreate(name="o", origin_host="1.2.3.4").origin_host == "1.2.3.4"
    OriginCreate(name="o", origin_host="backend.example.com", health_check_url="/healthz")
    CacheRuleCreate(pattern="/static/*")
    DNSRecordCreate(type="A", name="@", content="1.2.3.4")
    DNSRecordCreate(type="CNAME", name="www", content="example.com")
    WAFRuleCreate(name="r", conditions={"path": "/admin"})
    IPAccessRuleCreate(rule_type="blacklist", ip_address="10.0.0.0/8")


@pytest.mark.parametrize("factory", [
    lambda: DomainCreate(name="e.com; }\nlocation / { proxy_pass http://x; }"),
    lambda: OriginCreate(name="o", origin_host="1.2.3.4; } location /r { root /; }"),
    lambda: OriginCreate(name="o", origin_host="x.com", health_check_url="/a\nadd_header e v;"),
    lambda: OriginCreate(name="o", origin_host="x.com", health_check_url="../../etc/passwd"),
    lambda: CacheRuleCreate(pattern="^/a$ { proxy_pass http://127.0.0.1:5432; }"),
    lambda: DNSRecordCreate(type="A", name="../../ssl/cdn/victim", content="1.2.3.4"),
    lambda: DNSRecordCreate(type="TXT", name="@", content="x\ninjected"),
    lambda: WAFRuleCreate(name="r", conditions={"path": "/a\n}\n"}),
    lambda: IPAccessRuleCreate(rule_type="blacklist", ip_address="not-an-ip"),
])
def test_injection_and_traversal_rejected(factory):
    with pytest.raises(ValidationError):
        factory()
