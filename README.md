# FlowRun

**FlowRun** — распределенная платформа для планирования и выполнения фоновых задач. Она предназначена для автоматизации повторяющихся операций, распределения задач между исполнителями и отслеживания результатов.

## Архитектура

В текущей версии Task API поддерживает CRUD задач с хранением в PostgreSQL и кэшированием в Redis. Для каждой задачи можно создать отдельный запуск и получить его статус и результат.

Scheduler находит ожидающие запуски и отправляет их в RabbitMQ. Worker получает задания типа `demo`, выполняет их и сохраняет результат в PostgreSQL. Проверено, что при остановленном Worker задание остается в очереди и обрабатывается после его запуска.

Docker Compose запускает Task API, Scheduler, Worker, PostgreSQL, Redis и RabbitMQ. 

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

[C1 System Context](docs/c1.md)

[C2 Container Diagram](docs/c2.md)

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

При первом запуске следует подготовить таблицы PostgreSQL.

```powershell
docker compose up -d --wait postgres
docker compose cp ./infrastructure/postgres/schema.sql postgres:/tmp/flowrun-schema.sql
docker compose exec -T postgres psql -U flowrun -d flowrun -v ON_ERROR_STOP=1 -f /tmp/flowrun-schema.sql
```

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

[Тестовый эндпоинт `/hello`](http://localhost:8000/hello)

[Проверка состояния API `/health`](http://localhost:8000/health)

[Документация API `/docs`](http://localhost:8000/docs)

[Панель RabbitMQ](http://127.0.0.1:15672) — логин `flowrun`, пароль из `RABBITMQ_PASSWORD` в `.env`.

Чтобы остановить сервисы, следует выполнить команду:

```powershell
docker compose down
```

## Сеть и безопасность

Сервисы распределены по сетевым зонам `edge`, `app`, `data` и `management`. Веб-интерфейс доступен через Nginx API Gateway по адресу http://localhost:8080.

PostgreSQL использует общее сетевое пространство с контейнером `postgres-firewall`. Правила iptables разрешают подключения к TCP/5432 от Task API, Scheduler и Worker.

Проверены разрешенный доступ к базе, блокировка постороннего контейнера, ошибка приложения при временном запрете необходимого соединения и восстановление после снятия запрета.

[Схема сети, правила и команды проверки](docs/network.md)


## Roadmap

- [x] Базовый FastAPI-сервис
- [x] Контейнеризация Docker
- [x] Запуск PostgreSQL, Redis и RabbitMQ в Docker Compose
- [x] CRUD для задач с хранением в PostgreSQL
- [x] Кэширование в Redis
- [x] Постановка заданий в очередь RabbitMQ
- [x] Планировщик задач (Scheduler)
- [x] Распределённое выполнение задач (Workers)
- [x] Веб-интерфейс
- [x] Сегментация сети и Firewall для PostgreSQL
- [ ] Отказоустойчивость и резервное копирование
- [ ] Мониторинг и наблюдаемость
