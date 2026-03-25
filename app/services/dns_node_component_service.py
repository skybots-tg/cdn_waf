"""DNS node component management — status checks, actions, and health."""
import logging
from typing import Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dns_node import DNSNode
from app.schemas.dns_node import DNSNodeCommandResult, DNSComponentStatus

logger = logging.getLogger(__name__)


class DNSNodeComponentService:
    """High-level component management for DNS nodes."""

    @staticmethod
    async def manage_component_action(
        node: DNSNode, component: str, action: str, db: AsyncSession = None
    ) -> DNSNodeCommandResult:
        from app.services.dns_node_service import DNSNodeService

        if action == "install":
            handler = {
                "dependencies": DNSNodeService.install_dependencies,
                "python_env": DNSNodeService.install_python_env,
                "app_code": DNSNodeService.update_app_code,
                "config": DNSNodeService.update_config,
                "dns_service": DNSNodeService.install_service,
                "certbot": DNSNodeService.install_certbot,
                "migrations": DNSNodeService.run_migrations,
            }.get(component)
            if handler:
                return await handler(node)
            if component in ("dns_server",):
                return await DNSNodeService.install_node(node)
            if component == "database" and db:
                return await DNSNodeService.sync_database(node, db)

        if component == "certbot" and action == "issue":
            return await DNSNodeService.issue_certificate(node)

        if component in ("dns_service", "dns_server"):
            cmd_map = {
                "start": "systemctl start cdn-waf-dns",
                "stop": "systemctl stop cdn-waf-dns",
                "restart": "systemctl restart cdn-waf-dns",
                "status": "systemctl status cdn-waf-dns",
            }
            if action in cmd_map:
                return await DNSNodeService.execute_command(node, cmd_map[action])

        if component == "database" and action == "sync" and db:
            return await DNSNodeService.sync_database(node, db)

        return DNSNodeCommandResult(
            success=False, stdout="",
            stderr=f"Unknown component or action: {component} {action}",
            exit_code=1, execution_time=0,
        )

    @staticmethod
    async def get_component_status(node: DNSNode, component: str) -> DNSComponentStatus:
        """Get component status by running remote checks."""
        from app.services.dns_node_service import DNSNodeService
        execute = DNSNodeService.execute_command

        if component in ("dns_server", "dns_service"):
            res_installed = await execute(node, "systemctl list-unit-files cdn-waf-dns.service")
            is_installed = res_installed.success and "cdn-waf-dns.service" in res_installed.stdout
            res = await execute(node, "systemctl is-active cdn-waf-dns")
            running = res.stdout.strip() == "active"
            status_text = "Active" if running else ("Inactive" if is_installed else "Not Installed")
            return DNSComponentStatus(
                component=component, installed=is_installed,
                running=running, status_text=status_text,
            )

        if component == "certbot":
            res = await execute(node, "certbot --version")
            installed = res.success
            version = res.stdout.strip().split()[-1] if installed and res.stdout else None
            return DNSComponentStatus(
                component=component, installed=installed,
                running=True, version=version,
                status_text="Installed" if installed else "Missing",
            )

        if component == "migrations":
            res = await execute(node, "[ -x /opt/cdn_waf/venv/bin/alembic ]")
            return DNSComponentStatus(
                component=component, installed=res.success,
                running=True, status_text="Ready" if res.success else "Missing Alembic",
            )

        if component == "database":
            res = await execute(
                node, "sudo -u postgres psql cdn_waf -c 'SELECT count(*) FROM domains'"
            )
            if res.success:
                try:
                    count = res.stdout.split('\n')[2].strip()
                    return DNSComponentStatus(
                        component=component, installed=True,
                        running=True, status_text=f"OK ({count} domains)",
                    )
                except Exception:
                    pass
            return DNSComponentStatus(
                component=component, installed=False,
                running=False, status_text="Error",
            )

        simple_checks = {
            "dependencies": ("which python3", "Installed", "Missing"),
            "python_env": ("[ -d /opt/cdn_waf/venv ]", "Installed", "Missing"),
            "app_code": ("[ -d /opt/cdn_waf/app ]", "Installed", "Missing"),
            "config": ("[ -f /opt/cdn_waf/.env ]", "Configured", "Missing"),
        }
        if component in simple_checks:
            cmd, ok_text, fail_text = simple_checks[component]
            res = await execute(node, cmd)
            return DNSComponentStatus(
                component=component, installed=res.success,
                running=True, status_text=ok_text if res.success else fail_text,
            )

        return DNSComponentStatus(
            component=component, installed=False,
            running=False, status_text="Unknown",
        )

    @staticmethod
    async def check_health(node: DNSNode, db: AsyncSession = None) -> Dict[str, Any]:
        """Check node health and update status."""
        res = await DNSNodeComponentService.get_component_status(node, "dns_service")
        status = "online" if res.running else ("offline" if res.installed else "unknown")

        if db:
            node.status = status
            node.last_heartbeat = datetime.utcnow()
            await db.commit()
            await db.refresh(node)

        return {"status": status, "service_active": res.running, "installed": res.installed}
