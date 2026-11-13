# Сеть и Firewall FlowRun

## Сетевые зоны

| Зона | Подсеть | Подключённые компоненты |
|---|---|---|
| edge | 172.28.10.0/24 | Gateway, Frontend |
| app | 172.28.20.0/24 | Gateway, Task API, Scheduler, Worker |
| data | 172.28.30.0/24 | Task API, Scheduler, Worker, Redis, RabbitMQ, PostgreSQL через postgres-firewall |
| management | Выделяется Docker автоматически | RabbitMQ, публикация панели на 127.0.0.1:15672 |

Сеть `data` создаётся с `internal: true`. RabbitMQ дополнительно подключён к обычной bridge-сети `management`, через которую публикуется веб-панель на ноутбук. Прикладные сервисы обращаются к хранилищам по DNS-именам `postgres`, `redis` и `rabbitmq`.

| Компонент | IPv4 в data |
|---|---|
| Task API | 172.28.30.10 |
| Worker | 172.28.30.20 |
| Scheduler | 172.28.30.30 |
| PostgreSQL / postgres-firewall | 172.28.30.100 |
| Redis | 172.28.30.101 |
| RabbitMQ | 172.28.30.102 |

Для воспроизводимых ACL назначены фиксированные IPv4-адреса. Эта конфигурация рассчитана на один экземпляр каждого сервиса. Для дополнительных Worker понадобятся отдельные адреса и соответствующие разрешающие правила.

На ноутбуке опубликованы `127.0.0.1:8080` для Gateway, `127.0.0.1:8000` для прямой проверки API и Swagger, `127.0.0.1:15672` для панели RabbitMQ.

## Действующая фильтрация PostgreSQL

Контейнер `postgres-firewall` получает capability `NET_ADMIN` и применяет `iptables` в своём сетевом пространстве. PostgreSQL запускается с `network_mode: service:postgres-firewall` и использует то же сетевое пространство. Правила начинают действовать до запуска PostgreSQL, поскольку база зависит от healthcheck контейнера Firewall.

| Трафик на входе PostgreSQL | Решение |
|---|---|
| Loopback | ACCEPT |
| Ответный трафик ESTABLISHED, RELATED | ACCEPT |
| Task API → TCP/5432 | ACCEPT |
| Worker → TCP/5432 | ACCEPT |
| Scheduler → TCP/5432 | ACCEPT |
| Остальной входящий IPv4-трафик | DROP |

`OUTPUT` разрешён для ответов и DNS. Правила загружаются через `iptables-restore`. Они действуют в сетевом пространстве PostgreSQL. Redis и RabbitMQ размещены в зоне data и используют сетевую изоляцию Docker. Отдельные правила INPUT для этих двух сервисов в этот пакет не входят.

## Применение

Команды выполняются в PowerShell из `C:\Projects\flowrun`.

Перед заменой Compose сохрани исходную конфигурацию.

```powershell
Copy-Item docker-compose.yml "$env:TEMP\flowrun-compose-before-network.yml"
```

Распакуй содержимое архива в корень проекта с заменой `docker-compose.yml`. В архиве четыре файла, включая этот документ.

Проверь конфигурацию.

```powershell
docker compose config --quiet
```

Затем пересоздай стек с новыми сетями. Именованные тома PostgreSQL и RabbitMQ сохраняются при выполнении этих команд.

```powershell
docker compose down
docker compose up -d --build --wait
docker compose ps
docker compose logs --tail 30 postgres-firewall
```

В логе Firewall ожидается `PostgreSQL firewall rules applied`. Если Docker сообщает о пересечении подсетей, остановись на этом результате. Нужно выбрать свободные подсети и согласованно изменить адреса в Compose и entrypoint.sh.

## Проверка разрешённого доступа

Список задач читается из PostgreSQL через Task API.

```powershell
Invoke-RestMethod http://localhost:8080/api/tasks | ConvertTo-Json -Depth 10
docker compose exec -T postgres-firewall iptables -L INPUT -n -v
```

Ожидается список задач. Счётчик разрешающего правила для `172.28.30.10` должен увеличиваться при создании новых соединений. У уже открытых соединений увеличивается счётчик ESTABLISHED.

Открой `http://localhost:8080`, создай задачу demo и выполни её. Результат `succeeded` также проверит соединения Scheduler и Worker с базой.

## Проверка запрещённого доступа

Запусти временный диагностический контейнер в сети data. Docker выдаст ему свободный адрес, отличный от трёх разрешённых статических адресов.

```powershell
@'
import socket

try:
    with socket.create_connection(("postgres", 5432), timeout=3):
        print("UNEXPECTED: connection was allowed")
        raise SystemExit(1)
except TimeoutError:
    print("BLOCKED: connection timed out")
'@ | docker run --rm -i --network flowrun-data --entrypoint python flowrun-task-api
```

Ожидается `BLOCKED: connection timed out`. Ошибки DNS и отсутствующего образа требуют отдельного исправления и не подтверждают работу Firewall.

Посмотри счётчик пакетов политики DROP после проверки.

```powershell
docker compose exec -T postgres-firewall iptables -L INPUT -n -v
```

Счётчик DROP должен увеличиться относительно значения перед тестом.

## Временная блокировка необходимого соединения

Для этой проверки используется `/api/tasks`. Этот эндпоинт читает список из PostgreSQL. `/health` проверяет доступность процесса API.

Добавь правило REJECT перед правилом ESTABLISHED, чтобы блокировка затронула и существующие соединения пула Task API.

```powershell
docker compose exec -T postgres-firewall iptables -I INPUT 1 -s 172.28.30.10 -p tcp --dport 5432 -j REJECT --reject-with tcp-reset
```

После успешного добавления правила выполни весь блок. `finally` удалит временное правило после запроса.

```powershell
try {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 20 -ErrorAction Stop http://localhost:8080/api/tasks
        Write-Host "UNEXPECTED: HTTP $($response.StatusCode)"
    }
    catch {
        if ($null -ne $_.Exception.Response) {
            Write-Host "Blocked request returned HTTP $([int]$_.Exception.Response.StatusCode)"
        }
        else {
            Write-Host $_.Exception.Message
        }
    }
}
finally {
    docker compose exec -T postgres-firewall iptables -D INPUT -s 172.28.30.10 -p tcp --dport 5432 -j REJECT --reject-with tcp-reset
}
```

Во время блокировки ожидается ошибка приложения, обычно HTTP 500. После восстановления повтори запрос.

```powershell
Invoke-RestMethod http://localhost:8080/api/tasks | ConvertTo-Json -Depth 10
```

Ожидается успешное чтение списка задач. Если проверку пришлось прервать до выполнения `finally`, отдельно выполни команду удаления правила из этого блока.

## Возврат к исходному Compose

Если после изменения сетей потребуется вернуть исходную конфигурацию, выполни команды из корня проекта.

```powershell
docker compose down
Copy-Item "$env:TEMP\flowrun-compose-before-network.yml" docker-compose.yml
docker compose up -d --build --wait
```

## Границы проверки

Пакет подготовлен по docker-compose.yml пользователя. Локально проверены YAML, соответствие адресов ACL и shell-синтаксис.

13 ноября 2026 года пользователь выполнил проверки на Docker Desktop и предоставил результаты.

| Проверка | Наблюдаемый результат |
|---|---|
| Запуск контейнеров и загрузка правил | Все девять контейнеров запущены, в логе Firewall есть подтверждение загрузки |
| API читает PostgreSQL | Получен список задач |
| Диагностический контейнер обращается к PostgreSQL | Timeout, счётчик DROP увеличился с 0 до 3 пакетов |
| Временный REJECT для Task API | Запрос списка задач вернул HTTP 500 |
| Удаление временного правила | Список задач снова доступен |
| Выполнение demo после сегментации | Запуск №4 завершился со статусом succeeded |
| Панель RabbitMQ после добавления management | Открылась, отображается один consumer |

Для воспроизведения используй команды из разделов выше. Результаты относятся к проверенной конфигурации ноутбука.

Разделение контейнеров на зоны и ACL PostgreSQL покрывают сетевой этап. Отказоустойчивые кластеры, backup/restore, запуск по расписанию и HTTP-check остаются отдельными задачами проекта.

## Документация

Сетевые псевдонимы, `network_mode` и capabilities описаны в [Compose services reference](https://docs.docker.com/reference/compose-file/services/).

Взаимодействие контейнеров и сетей описано в [Networking in Compose](https://docs.docker.com/compose/how-tos/networking/).

Назначение `NET_ADMIN` описано в [Running containers](https://docs.docker.com/engine/containers/run/).
