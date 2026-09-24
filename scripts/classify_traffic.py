#!/usr/bin/env python3
"""Разметить классом трафика строки сырых логов, у которых его ещё нет.

Приём логов с 24.09.2026 ставит класс и ASN сам (app/api/internal_logs.py),
а свод раз в 5 минут досказывает VPN и сканеры за последние часы. Строки,
записанные раньше, этот скрипт размечает один раз после миграции 0009:

    cd /root/cdn_waf && venv/bin/python scripts/classify_traffic.py

С ``--all`` размечает заново все строки — после правки правил в
app/services/traffic_class.py или ip_networks.py.

Скачивает GeoLite2-ASN, если её нет, проставляет asn и client_class пачками
по id, затем проходит пересмотр (``refine_traffic_classes``) окнами по 4
часа за весь срок хранения сырых логов. Повторный запуск безвреден: он
трогает только строки без класса и заново пересматривает окна.
"""
import asyncio
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import bindparam, select  # noqa: E402

from app.models.log import RequestLog  # noqa: E402
from app.services import ip_networks, traffic_class  # noqa: E402
from app.services.analytics_aggregation import refine_traffic_classes  # noqa: E402
from app.tasks.utils import create_task_db_session  # noqa: E402

BATCH = 5000
WINDOW = timedelta(hours=4)


async def main(everything: bool = False) -> None:
    if not ip_networks.DB_PATH.exists():
        print("GeoLite2-ASN:", ip_networks.download_database())
    engine, Session = create_task_db_session()
    table = RequestLog.__table__
    update = (
        table.update()
        .where(table.c.id == bindparam("row_id"))
        .values(asn=bindparam("new_asn"), client_class=bindparam("new_class"))
    )
    started = time.monotonic()
    done, last_id = 0, 0
    try:
        async with Session() as db:
            while True:
                rows = (await db.execute(
                    select(RequestLog.id, RequestLog.client_ip, RequestLog.user_agent,
                           RequestLog.path, RequestLog.status_code)
                    .where(RequestLog.id > last_id,
                           *(() if everything else (RequestLog.client_class.is_(None),)))
                    .order_by(RequestLog.id).limit(BATCH)
                )).all()
                if not rows:
                    break
                params = []
                for r in rows:
                    asn, org = ip_networks.lookup(r.client_ip)
                    cls = traffic_class.classify(
                        r.user_agent, r.path, r.status_code, ip_networks.is_hosting(asn, org)
                    )
                    params.append({"row_id": r.id, "new_asn": asn, "new_class": cls})
                await db.execute(update, params)
                await db.commit()
                done += len(rows)
                last_id = rows[-1].id
                print(f"classified {done} rows", flush=True)

            oldest = (await db.execute(select(RequestLog.timestamp).order_by(RequestLog.timestamp).limit(1))).scalar()
            end = datetime.utcnow()
            start = oldest.replace(minute=0, second=0, microsecond=0) if oldest else end
            totals = {"scanner_rows": 0, "vpn_rows": 0}
            while start < end:
                result = await refine_traffic_classes(db, start, min(start + WINDOW, end))
                for key in totals:
                    totals[key] += result[key]
                start += WINDOW
            print("refined:", totals)
    finally:
        await engine.dispose()
    print(f"done in {time.monotonic() - started:.0f} s")


if __name__ == "__main__":
    asyncio.run(main(everything="--all" in sys.argv[1:]))
