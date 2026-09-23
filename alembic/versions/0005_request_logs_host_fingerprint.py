"""request_logs: хост, отпечаток против дублей, индекс домен+время.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-23

Приём сырых логов выключили 03.09.2026: нода повторяла партию, которую панель
уже записала, и таблица росла лавиной. В оставшихся строках за 1–3.09 21% —
точные дубли. Отпечаток с уникальным индексом делает повтор безвредным.

Хост нужен, потому что нода пишет $host (app.example.com), а зона в панели —
example.com: по точному совпадению поддомены теряли домен целиком.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("request_logs", sa.Column("host", sa.String(255), nullable=True))
    op.add_column("request_logs", sa.Column("fingerprint", sa.BigInteger(), nullable=True))

    # Дубли, накопленные до отпечатка: оставляем первую строку каждой группы.
    op.execute(
        """
        DELETE FROM request_logs r
        USING (
            SELECT id, row_number() OVER (
                PARTITION BY edge_node_id, timestamp, client_ip, method, path,
                             coalesce(query_string, ''), status_code, bytes_sent,
                             coalesce(request_time, -1), coalesce(user_agent, '')
                ORDER BY id
            ) AS n
            FROM request_logs
        ) d
        WHERE r.id = d.id AND d.n > 1
        """
    )

    op.create_index(
        "uq_request_logs_fingerprint", "request_logs", ["fingerprint"], unique=True
    )
    # Все выборки аналитики — «домен за период».
    op.create_index(
        "ix_request_logs_domain_ts", "request_logs", ["domain_id", "timestamp"]
    )


def downgrade():
    op.drop_index("ix_request_logs_domain_ts", table_name="request_logs")
    op.drop_index("uq_request_logs_fingerprint", table_name="request_logs")
    op.drop_column("request_logs", "fingerprint")
    op.drop_column("request_logs", "host")
