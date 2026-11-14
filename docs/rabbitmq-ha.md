# RabbitMQ HA в FlowRun

## Компоненты

Новый кластер использует три брокера RabbitMQ одной версии и отдельные тома. Erlang cookie берётся из локального файла `.secrets/rabbitmq-cookie`. Cookie подготовлен пользователем из исходного брокера, его размер составляет 20 байт, а путь исключён из Git.

| Компонент | IPv4 в data | Назначение |
|---|---|---|
| rabbitmq-1 | 172.28.30.103 | Первый узел кластера |
| rabbitmq-2 | 172.28.30.104 | Второй узел кластера |
| rabbitmq-3 | 172.28.30.105 | Третий узел кластера |
| rabbitmq-proxy | 172.28.30.106 | AMQP и HTTP Management через HAProxy |

Scheduler и Worker подключаются к `rabbitmq-proxy:5672`. Веб-панель публикуется прокси на `127.0.0.1:15672`. HAProxy предпочитает первый доступный узел и закрывает сессии с сервером, признанным недоступным. Клиенты aio-pika переподключаются через connect_robust.

Каждый брокер получает копию общего cookie с правами 0600 и владельцем rabbitmq. Секрет не включён в архив конфигурации. Файлы .env и .secrets предназначены для локальной настройки.

Для очереди flowrun.tasks используется тип quorum. Стандартный начальный размер группы равен трём при наличии трёх доступных узлов в кластере. Все узлы нужно объединить до первого запуска Scheduler и Worker. После создания очереди реальное число реплик проверяется командой quorum_status.

## Предварительная проверка

Команды выполняются в PowerShell из `C:\Projects\flowrun` до замены текущего Compose.

Останови отправку и обработку заданий.

```powershell
docker compose stop scheduler worker
docker compose exec -T rabbitmq rabbitmqctl list_queues name type messages_ready messages_unacknowledged
```

Для flowrun.tasks ожидается quorum, messages_ready 0 и messages_unacknowledged 0.

Проверь незавершённые запуски в PostgreSQL через HAProxy.

```powershell
@'
from main import engine
from sqlalchemy import text

with engine.connect() as connection:
    count = connection.execute(text(
        "SELECT COUNT(*) FROM task_runs "
        "WHERE status IN ('pending', 'queued', 'running')"
    )).scalar_one()
    print("unfinished_runs:", count)
'@ | docker compose exec -T task-api python
```

Ожидается unfinished_runs 0. При наличии заданий запусти Scheduler и Worker, дождись их обработки и повтори проверку после остановки клиентов.

```powershell
docker compose start scheduler worker
```

Переход на новые тома выполняется после подтверждения пустой очереди и отсутствия незавершённых запусков. База PostgreSQL хранит историю завершённых задач. Исходный том rabbitmq-data сохраняется для отката.

## Подготовка Compose и образов

Сохрани текущий Compose и останови одиночный брокер.

```powershell
Copy-Item docker-compose.yml "$env:TEMP\flowrun-compose-before-rabbit-ha.yml"
docker compose stop rabbitmq
```

Распакуй пакет в корень проекта с заменой docker-compose.yml. Секрет должен находиться по пути `.secrets/rabbitmq-cookie`.

```powershell
docker compose config --quiet
```

Если проверка успешна, собери два образа.

```powershell
docker compose build rabbitmq-1 rabbitmq-proxy
```

## Первоначальное объединение узлов

Для первого развёртывания используй последовательность из этого раздела. Начни с трёх брокеров.

```powershell
docker compose up -d --wait --wait-timeout 240 rabbitmq-1 rabbitmq-2 rabbitmq-3
docker compose ps
```

Объедини новые узлы. Для RabbitMQ 4.1 и новее join_cluster выполняет подготовку узла самостоятельно.

```powershell
docker compose exec -T rabbitmq-2 rabbitmqctl join_cluster rabbit@rabbitmq-1
docker compose exec -T rabbitmq-3 rabbitmqctl join_cluster rabbit@rabbitmq-1
docker compose exec -T rabbitmq-1 rabbitmqctl cluster_status
```

Ожидаются три работающих участника с именами rabbit@rabbitmq-1, rabbit@rabbitmq-2 и rabbit@rabbitmq-3. После первого объединения кластер хранит состав в своих томах, а следующий запуск существующего стенда выполняется обычной командой docker compose up.

Команды первоначального join предназначены для новых узлов. При повторной настройке сначала посмотри cluster_status и выполняй join только для ещё не присоединённого пустого узла.

При ошибке посмотри логи.

```powershell
docker compose logs --tail 80 rabbitmq-1 rabbitmq-2 rabbitmq-3
```

## Запуск клиентов и проверка реплик очереди

После подтверждения трёх участников запусти прокси.

```powershell
docker compose up -d --wait --wait-timeout 120 rabbitmq-proxy
```

Пересоздай Scheduler и Worker с новым адресом брокера.

```powershell
docker compose up -d --no-deps --force-recreate --wait scheduler worker
docker compose logs --tail 40 scheduler worker
```

Эти сервисы объявляют flowrun.tasks после формирования трёхузлового кластера. Проверь группу очереди.

```powershell
docker compose exec -T rabbitmq-1 rabbitmq-queues quorum_status --vhost / flowrun.tasks
```

Ожидаются три участника группы очереди. Если группа содержит меньше трёх узлов, сначала проверь cluster_status. После подтверждения трёх работающих узлов можно добавить отсутствующий узел в группу командой add_member.

```powershell
docker compose exec -T rabbitmq-1 rabbitmq-queues add_member --vhost / flowrun.tasks rabbit@rabbitmq-2
docker compose exec -T rabbitmq-1 rabbitmq-queues add_member --vhost / flowrun.tasks rabbit@rabbitmq-3
```

Выполняй add_member только для отсутствующего участника, затем повтори quorum_status.

Открой `http://127.0.0.1:15672`. Логин flowrun, пароль из существующего RABBITMQ_PASSWORD. В интерфейсе FlowRun создай и выполни demo-задачу. Ожидается succeeded.

## Проверка отказа одного узла

Перед проверкой должны работать все три узла и все три реплики очереди. Проверь, какой узел является лидером группы, через quorum_status. Для демонстрации останови этот узел. В примере ниже выбран rabbitmq-1. Если лидер другой, используй его фактическое имя.

```powershell
docker compose stop rabbitmq-1
```

Через интерфейс FlowRun создай новую demo-задачу и запусти её. После переподключения клиентов и выбора лидера очереди ожидается succeeded. Сохрани ID запуска и результат.

Из работающего узла проверь кластер и группу очереди.

```powershell
docker compose exec -T rabbitmq-2 rabbitmqctl cluster_status
docker compose exec -T rabbitmq-2 rabbitmq-queues quorum_status --vhost / flowrun.tasks
```

Ожидается новый лидер очереди и два работающих брокера. Веб-панель доступна через тот же прокси. Публикация и подтверждение задания проверяются новым успешно завершённым запуском.

Верни остановленный узел.

```powershell
docker compose start rabbitmq-1
docker compose exec -T rabbitmq-2 rabbitmqctl cluster_status
docker compose exec -T rabbitmq-2 rabbitmq-queues quorum_status --vhost / flowrun.tasks
```

Дождись возврата третьего узла и синхронизации его реплики. Во время этой проверки изменения конфигурации клиентов не требуются. Они используют постоянную точку входа rabbitmq-proxy.

## Откат к одиночному RabbitMQ

Для отката к исходному пустому брокеру требуется сначала обработать задания нового кластера. Проверь messages_ready 0, messages_unacknowledged 0 и unfinished_runs 0, затем останови Scheduler и Worker. Если новый кластер ещё не принимал задания, исходная контрольная точка подходит для отката.

Останови компоненты нового кластера, восстанови сохранённый Compose и подними исходный брокер.

```powershell
docker compose stop scheduler worker rabbitmq-proxy rabbitmq-1 rabbitmq-2 rabbitmq-3
Copy-Item "$env:TEMP\flowrun-compose-before-rabbit-ha.yml" docker-compose.yml
docker compose up -d --no-deps --force-recreate --wait rabbitmq
docker compose up -d --no-deps --force-recreate --wait scheduler worker
```

Исходный Compose подключит одиночный брокер к его сохранённому тому rabbitmq-data. Новые тома кластера останутся доступными для последующей диагностики. История задач находится в PostgreSQL.

## Границы надёжности и статус проверки

Три реплики quorum queue позволяют обрабатывать сообщения при доступности большинства, то есть двух из трёх узлов. Все контейнеры работают на одном ноутбуке. HAProxy представлен одним экземпляром. Отказ хоста или прокси требует отдельного решения.

Этот пакет подготовлен после успешной проверки PostgreSQL HA. Локально проверены YAML, зависимости, адреса, отсутствие секретных файлов в архиве и shell-синтаксис. Docker Engine в среде подготовки отсутствует. Сборка, объединение узлов, состав группы очереди, переподключение клиентов и обработка задания при отказе узла должны быть подтверждены на ноутбуке.

## Документация

Формирование кластера описано в [RabbitMQ Clustering Guide](https://www.rabbitmq.com/docs/clustering).

Репликация очередей и большинство описаны в [RabbitMQ Quorum Queues](https://www.rabbitmq.com/docs/quorum-queues).

Команды проверки и изменения состава группы описаны в [rabbitmq-queues](https://www.rabbitmq.com/docs/man/rabbitmq-queues.8).


## Результаты проверки

Кластер объединён из трёх узлов RabbitMQ 4.4.0.

Очередь flowrun.tasks имеет три голосующие реплики.

До отказа запуск №39 завершился со статусом succeeded.

После принудительного завершения rabbitmq-1 новым лидером стал rabbitmq-3.

При недоступном rabbitmq-1 запуск №40 завершился со статусом succeeded.

После возврата rabbitmq-1 все три реплики синхронизировались.

Испытание проверяет отказ отдельного контейнера на одном хосте.