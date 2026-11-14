# Сеть и Firewall FlowRun с PostgreSQL HA

## Сетевые зоны

| Зона | Подсеть | Компоненты |
|---|---|---|
| edge | 172.28.10.0/24 | Gateway, Frontend |
| app | 172.28.20.0/24 | Gateway, Task API, Scheduler, Worker |
| data | 172.28.30.0/24 | Task API, Scheduler, Worker, Redis, RabbitMQ, SQL-точка входа |
| management | Назначается Docker | RabbitMQ, публикация веб-панели |
| pg-ha | 172.28.40.0/24 | postgres-1, postgres-2, etcd, HAProxy |

Сети data и pg-ha внутренние. RabbitMQ подключён также к обычной bridge-сети management для публикации панели на ноутбук.

На ноутбуке опубликованы Gateway на `127.0.0.1:8080`, Task API и Swagger на `127.0.0.1:8000`, RabbitMQ Management на `127.0.0.1:15672`.

## SQL-точка входа

Сервис postgres запускает HAProxy в сетевом пространстве контейнера postgres-firewall. В сети data этому пространству назначены адрес `172.28.30.100` и DNS-псевдоним postgres. В сети pg-ha используется адрес `172.28.40.100`.

Приложение подключается к postgres:5432. HAProxy открывает соединение с текущим primary в pg-ha. Узлы PostgreSQL и etcd подключены только к pg-ha.

| Адрес узла | Компонент |
|---|---|
| 172.28.30.10 | Task API |
| 172.28.30.20 | Worker |
| 172.28.30.30 | Scheduler |
| 172.28.40.10 | etcd |
| 172.28.40.11 | postgres-1 |
| 172.28.40.12 | postgres-2 |

Фиксированные IP используются в ACL и настройках кластера. Текущая конфигурация рассчитана на один экземпляр каждого сервиса. Дополнительные Worker требуют отдельных адресов и разрешающих правил.

## Правила INPUT SQL-точки входа

| Трафик | Решение |
|---|---|
| Loopback | ACCEPT |
| ESTABLISHED, RELATED | ACCEPT |
| Task API → TCP/5432 | ACCEPT |
| Worker → TCP/5432 | ACCEPT |
| Scheduler → TCP/5432 | ACCEPT |
| Остальной входящий IPv4-трафик | DROP |

Capability NET_ADMIN назначена контейнеру postgres-firewall. Правила загружаются до запуска HAProxy. OUTPUT разрешает исходящие соединения прокси к primary, проверки REST API и DNS. FORWARD закрыт, поскольку HAProxy передаёт данные через собственные TCP-соединения.

## Статус проверок

13 ноября 2026 года для предшествующей конфигурации с одиночным PostgreSQL подтверждены следующие результаты.

- Task API получил список задач из базы.
- Диагностический контейнер в data получил timeout при обращении к postgres:5432. Счётчик DROP вырос с 0 до 3 пакетов.
- Временный REJECT для Task API привёл к HTTP 500.
- После удаления REJECT список задач снова стал доступен.
- Demo-задача выполнилась после сегментации.
- После подключения RabbitMQ к management открылась веб-панель и восстановился consumer.

После перехода на PostgreSQL HA эти проверки нужно повторить для SQL-точки входа HAProxy. Их успешность для новой конфигурации будет зафиксирована после запуска на ноутбуке.

## Команды проверки после перехода

Проверка разрешённого доступа и счётчиков.

```powershell
Invoke-RestMethod http://localhost:8080/api/tasks | ConvertTo-Json -Depth 10
docker compose exec -T postgres-firewall iptables -L INPUT -n -v
```

Проверка запрещённого соединения из временного контейнера.

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

Ожидается BLOCKED и увеличение счётчика DROP. Ошибка DNS не подтверждает фильтрацию.

Временную блокировку необходимого соединения выполняй после проверки кластера.

```powershell
docker compose exec -T postgres-firewall iptables -I INPUT 1 -s 172.28.30.10 -p tcp --dport 5432 -j REJECT --reject-with tcp-reset
```

После успешного добавления правила выполни блок проверки и автоматического удаления правила.

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
Invoke-RestMethod http://localhost:8080/api/tasks | ConvertTo-Json -Depth 10
```

Ожидается ошибка приложения во время блокировки и успешное чтение после удаления правила. При прерывании до finally отдельно выполни указанную команду удаления правила.

Переход на HA, восстановление данных и откат описаны в [reliability.md](reliability.md).
