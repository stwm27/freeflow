# FlowRun

**FlowRun** — распределенная платформа для планирования и выполнения фоновых задач. Она предназначена для автоматизации повторяющихся операций, распределения задач между исполнителями и отслеживания результатов.

## Архитектура

В текущей версии Docker Compose запускает базовый Task API, PostgreSQL, Redis и RabbitMQ. В таблице описана целевая архитектура FlowRun.

| Компонент | Назначение |
|-----------|------------|
| **Task API** | Создание задач, управление ими и получение статусов |
| **Scheduler** | Запуск задач по расписанию |
| **Worker** | Выполнение фоновых задач |
| **PostgreSQL** | Хранение задач и результатов выполнения |
| **Redis** | Кэширование и координация |
| **RabbitMQ** | Асинхронная передача заданий |
| **API Gateway** | Маршрутизация запросов |
| **Frontend** | Веб-интерфейс управления задачами |

### Архитектурные диаграммы

- [C1 System Context](docs/c1.md)
- [C2 Container Diagram](docs/c2.md)

## Технологии

| Категория | Технология |
|-----------|------------|
| **Backend** | Python 3.11, FastAPI |
| **Database** | PostgreSQL |
| **Cache** | Redis |
| **Message Broker** | RabbitMQ |
| **API Gateway** | Nginx |
| **Containerization** | Docker, Docker Compose |

## Запуск текущей версии

Для запуска нужен Docker Desktop. Команды выполняются в PowerShell из корня проекта.

Если файла `.env` еще нет, следует создать его из шаблона.

```powershell
Copy-Item .env.example .env
```

Далее следует открыть `.env` и задать свои значения для `POSTGRES_PASSWORD` и `RABBITMQ_PASSWORD`.

После чего следует запусть сервисы и проверь состояние контейнеров.

```powershell
docker compose up -d --build --wait
docker compose ps
```

После запуска доступны:

- [Тестовый эндпоинт `/hello`](http://localhost:8000/hello)
- [Проверка состояния API `/health`](http://localhost:8000/health)
- [Документация API `/docs`](http://localhost:8000/docs)
- [Панель RabbitMQ](http://127.0.0.1:15672) — логин `flowrun`, пароль из `RABBITMQ_PASSWORD` в `.env`.

Чтобы остановить сервисы, следует выполнить команду:

```powershell
docker compose down
```

## Roadmap

- [x] Базовый FastAPI-сервис
- [x] Контейнеризация Docker
- [x] Запуск PostgreSQL, Redis и RabbitMQ в Docker Compose
- [ ] CRUD для задач с хранением в PostgreSQL
- [ ] Кэширование в Redis
- [ ] Постановка заданий в очередь RabbitMQ
- [ ] Планировщик задач (Scheduler)
- [ ] Распределённое выполнение задач (Workers)
- [ ] Веб-интерфейс
- [ ] Сегментация сети и Firewall
- [ ] Отказоустойчивость и резервное копирование
- [ ] Мониторинг и наблюдаемость
