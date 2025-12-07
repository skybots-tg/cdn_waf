# Contributing to CDN WAF

Спасибо за интерес к проекту! Мы рады любым контрибуциям.

## Как внести вклад

### Сообщения об ошибках

Если вы нашли баг:

1. Проверьте, что такая проблема еще не заведена в Issues
2. Создайте новый Issue с подробным описанием:
   - Как воспроизвести
   - Ожидаемое поведение
   - Фактическое поведение
   - Версия Python, ОС и другие детали окружения

### Предложения по улучшению

Новые идеи всегда приветствуются! Создайте Issue с тегом "enhancement" и опишите:

- Зачем это нужно
- Как это должно работать
- Примеры использования

### Pull Requests

1. **Fork** репозиторий
2. Создайте **feature branch**: `git checkout -b feature/amazing-feature`
3. Внесите изменения с понятными commit сообщениями
4. Добавьте **тесты** для новой функциональности
5. Убедитесь, что все тесты проходят: `pytest`
6. Проверьте форматирование: `black app/` и `ruff check app/`
7. **Push** в ваш fork: `git push origin feature/amazing-feature`
8. Откройте **Pull Request**

## Стандарты кода

### Python

- Следуем **PEP 8**
- Используем **Black** для форматирования
- Используем **Ruff** для линтинга
- Используем **type hints** где возможно
- Docstrings в формате Google style

Пример:

```python
async def create_domain(
    domain_create: DomainCreate,
    db: AsyncSession
) -> Domain:
    """
    Create a new domain.
    
    Args:
        domain_create: Domain creation schema
        db: Database session
        
    Returns:
        Created domain object
        
    Raises:
        ValueError: If domain already exists
    """
    # implementation
```

### Commit Messages

Используем [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add WAF rule management API
fix: resolve cache purge issue
docs: update deployment guide
test: add tests for DNS records
refactor: simplify authentication flow
```

### Тесты

- Пишем тесты для новых фич
- Используем `pytest` и `pytest-asyncio`
- Стремимся к покрытию > 80%

```python
@pytest.mark.asyncio
async def test_create_domain():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post("/api/v1/domains", json={
            "name": "test.com"
        })
        assert response.status_code == 201
```

## Процесс ревью

1. Maintainer проверит ваш PR
2. Могут быть запрошены изменения
3. После одобрения PR будет смержен

## Вопросы?

Не стесняйтесь задавать вопросы в Issues или Discussions!

## Лицензия

Внося свой вклад, вы соглашаетесь, что ваши изменения будут лицензированы под MIT License.

