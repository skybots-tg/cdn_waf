"""Shared SSH connection utilities for edge and DNS node management"""
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

import asyncssh

logger = logging.getLogger(__name__)


@dataclass
class SSHCredentials:
    host: str
    port: int = 22
    user: str = "root"
    key: Optional[str] = None
    password: Optional[str] = None

    @staticmethod
    def from_node(node) -> "SSHCredentials":
        return SSHCredentials(
            host=node.ssh_host or node.ip_address,
            port=node.ssh_port or 22,
            user=node.ssh_user or "root",
            key=node.ssh_key,
            password=node.ssh_password,
        )


@dataclass
class CommandResult:
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    execution_time: float


def _build_connect_kwargs(creds: SSHCredentials) -> dict:
    kwargs = {
        "host": creds.host,
        "port": creds.port,
        "username": creds.user,
        "known_hosts": None,
        "client_keys": None,
    }
    if creds.key:
        kwargs["client_keys"] = [asyncssh.import_private_key(creds.key)]
    elif creds.password:
        kwargs["password"] = creds.password
    return kwargs


async def ssh_execute(
    creds: SSHCredentials,
    command: str,
    timeout: int = 30,
) -> CommandResult:
    """Execute a command on a remote host via SSH."""
    if not creds.key and not creds.password:
        return CommandResult(
            success=False,
            stdout="",
            stderr="SSH credentials (key or password) not configured",
            exit_code=1,
            execution_time=0.0,
        )

    try:
        start = datetime.utcnow()
        connect_kwargs = _build_connect_kwargs(creds)

        async with asyncssh.connect(**connect_kwargs) as conn:
            result = await conn.run(command, timeout=timeout)
            elapsed = (datetime.utcnow() - start).total_seconds()
            return CommandResult(
                success=result.exit_status == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.exit_status,
                execution_time=elapsed,
            )

    except Exception as e:
        logger.error(f"SSH command failed on {creds.host}: {e}")
        return CommandResult(
            success=False,
            stdout="",
            stderr=str(e),
            exit_code=1,
            execution_time=0.0,
        )


async def ssh_upload(
    creds: SSHCredentials,
    local_path: str,
    remote_path: str,
) -> Tuple[bool, str]:
    """Upload a file to a remote host via SCP, using a temp path + move."""
    if not creds.key and not creds.password:
        return False, "SSH credentials not configured"

    try:
        connect_kwargs = _build_connect_kwargs(creds)
        tmp_remote = f"/tmp/{os.path.basename(local_path)}_{secrets.token_hex(4)}"

        async with asyncssh.connect(**connect_kwargs) as conn:
            await asyncssh.scp(local_path, (conn, tmp_remote))

            cmd = f"mv {tmp_remote} {remote_path}"
            if creds.user != "root":
                cmd = f"sudo mv {tmp_remote} {remote_path}"

            result = await conn.run(cmd)
            if result.exit_status != 0:
                logger.error(f"Failed to move file to {remote_path}: {result.stderr}")
                await conn.run(f"rm -f {tmp_remote}")
                return False, result.stderr

            return True, ""

    except Exception as e:
        logger.error(f"SCP upload to {creds.host} failed: {e}")
        return False, str(e)
