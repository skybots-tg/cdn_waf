-- Проверяем текущую версию миграции
SELECT * FROM alembic_version;

-- Удаляем текущую версию (если есть)
DELETE FROM alembic_version;

-- Отмечаем старые миграции как выполненные
INSERT INTO alembic_version (version_num) VALUES ('2024_12_08_00_01_sync_schema');

-- Теперь можно применить новую миграцию через alembic upgrade head

