# Development Guide

## Локальная разработка

### Быстрый старт с Docker

Самый простой способ начать разработку:

```bash
# Клонирование
git clone https://github.com/yourusername/cdn_waf.git
cd cdn_waf

# Запуск с Docker
docker-compose up -d

# Применение миграций
docker-compose exec app alembic upgrade head

# Открыть в браузере
open http://localhost:8000
```

### Ручная установка

1. **Установка зависимостей**

```bash
# PostgreSQL
# macOS
brew install postgresql@15
brew services start postgresql@15

# Ubuntu
sudo apt install postgresql postgresql-contrib

# Redis
# macOS
brew install redis
brew services start redis

# Ubuntu
sudo apt install redis-server
```

2. **Настройка проекта**

```bash
# Виртуальное окружение
python3.11 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Установка пакетов
pip install -r requirements.txt

# Настройка .env
cp .env.example .env
```

3. **Настройка БД**

```bash
# Создание БД
createdb cdn_waf

# Миграции
alembic upgrade head
```

4. **Запуск**

```bash
# API сервер
uvicorn app.main:app --reload

# Celery worker (в отдельном терминале)
celery -A app.tasks.celery_app worker -l info

# Celery beat (в отдельном терминале)
celery -A app.tasks.celery_app beat -l info
```

## Структура проекта

```
cdn_waf/
├── app/
│   ├── api/              # API endpoints
│   │   ├── v1/           # API v1
│   │   │   ├── auth.py
│   │   │   ├── domains.py
│   │   │   ├── dns.py
│   │   │   └── ...
│   │   └── web.py        # Web UI routes
│   ├── core/             # Ядро
│   │   ├── config.py     # Конфигурация
│   │   ├── database.py   # БД
│   │   ├── security.py   # Безопасность
│   │   └── redis.py      # Redis
│   ├── models/           # SQLAlchemy модели
│   ├── schemas/          # Pydantic схемы
│   ├── services/         # Бизнес-логика
│   ├── tasks/            # Celery задачи
│   ├── templates/        # Jinja2 шаблоны
│   ├── static/           # Статика
│   │   ├── css/
│   │   ├── js/
│   │   └── fonts/
│   └── main.py           # Главный файл
├── alembic/              # Миграции
├── edge_node/            # Edge node код
├── docs/                 # Документация
├── tests/                # Тесты
└── docker-compose.yml
```

## Создание новой фичи

### 1. Создание модели

```python
# app/models/your_model.py
from sqlalchemy import Column, Integer, String
from app.core.database import Base

class YourModel(Base):
    __tablename__ = "your_table"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
```

### 2. Создание миграции

```bash
alembic revision --autogenerate -m "Add your_table"
alembic upgrade head
```

### 3. Создание схемы

```python
# app/schemas/your_schema.py
from pydantic import BaseModel

class YourModelCreate(BaseModel):
    name: str

class YourModelResponse(BaseModel):
    id: int
    name: str
    
    class Config:
        from_attributes = True
```

### 4. Создание сервиса

```python
# app/services/your_service.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.your_model import YourModel

class YourService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create(self, data):
        obj = YourModel(**data)
        self.db.add(obj)
        await self.db.flush()
        return obj
```

### 5. Создание endpoint

```python
# app/api/v1/your_endpoint.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db

router = APIRouter()

@router.post("/")
async def create_item(
    data: YourModelCreate,
    db: AsyncSession = Depends(get_db)
):
    service = YourService(db)
    item = await service.create(data.model_dump())
    await db.commit()
    return item
```

### 6. Регистрация роутера

```python
# app/main.py
from app.api.v1 import your_endpoint

app.include_router(
    your_endpoint.router,
    prefix="/api/v1/items",
    tags=["items"]
)
```

## Тестирование

### Запуск тестов

```bash
# Все тесты
pytest

# С покрытием
pytest --cov=app tests/

# Конкретный файл
pytest tests/test_auth.py

# Verbose mode
pytest -v
```

### Написание тестов

```python
# tests/test_your_feature.py
import pytest
from httpx import AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_create_item():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/items",
            json={"name": "Test Item"}
        )
        assert response.status_code == 201
        assert response.json()["name"] == "Test Item"
```

## Code Style

### Форматирование

```bash
# Black
black app/

# Ruff
ruff check app/
```

### Pre-commit hooks (рекомендуется)

```bash
# Установка
pip install pre-commit
pre-commit install

# Теперь при каждом commit будут запускаться проверки
```

## Debugging

### VS Code launch.json

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "FastAPI",
            "type": "python",
            "request": "launch",
            "module": "uvicorn",
            "args": [
                "app.main:app",
                "--reload"
            ],
            "jinja": true,
            "justMyCode": true
        }
    ]
}
```

### PyCharm

1. Run → Edit Configurations
2. Add new Python configuration
3. Script path: path to uvicorn
4. Parameters: `app.main:app --reload`

## База данных

### Просмотр схемы

```bash
psql -U cdn_user cdn_waf

\dt              # Список таблиц
\d users         # Описание таблицы
\q               # Выход
```

### Reset БД

```bash
# Осторожно! Удалит все данные
alembic downgrade base
alembic upgrade head
```

## Redis

### Просмотр данных

```bash
redis-cli

KEYS *           # Все ключи
GET key_name     # Значение
FLUSHALL         # Очистить всё (осторожно!)
```

## Полезные команды

```bash
# Логи в realtime
docker-compose logs -f app

# Выполнение команды в контейнере
docker-compose exec app python script.py

# Shell в контейнере
docker-compose exec app bash

# Пересборка контейнеров
docker-compose build --no-cache

# Остановка и удаление всего
docker-compose down -v
```

## Contributing

1. Fork репозиторий
2. Создайте feature branch: `git checkout -b feature/amazing-feature`
3. Commit изменения: `git commit -m 'Add amazing feature'`
4. Push в branch: `git push origin feature/amazing-feature`
5. Откройте Pull Request

## Troubleshooting

### Порт уже занят

```bash
# Найти процесс
lsof -i :8000

# Убить процесс
kill -9 <PID>
```

### Ошибки миграций

```bash
# Откат последней миграции
alembic downgrade -1

# Просмотр истории
alembic history

# Применение конкретной миграции
alembic upgrade <revision_id>
```

### Проблемы с зависимостями

```bash
# Переустановка
pip install -r requirements.txt --force-reinstall

# Очистка кэша
pip cache purge
```

