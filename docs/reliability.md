# Надёжность FlowRun

## Проверенное резервное копирование и восстановление

14 ноября 2026 года пользователь создал custom-format архив PostgreSQL 16 утилитой pg_dump, скопировал его на ноутбук и затем перенёс обратно в контейнер для восстановления.

Архив размером 5281 байт восстановлен через pg_restore с `--exit-on-error --single-transaction` в отдельную базу `flowrun_restore_<timestamp>`.

| Проверка | Рабочая база | Восстановленная база |
|---|---|---|
| Записи tasks | 4 | 4 |
| Записи task_runs | 4 | 4 |
| Результаты запусков | Сохранены | Доступны через SELECT |

Сравнение количества строк и чтение результатов подтверждены выводом PostgreSQL. Полное побайтовое сравнение всех данных отдельно не выполнялось.

## Архитектура переключения PostgreSQL

| Компонент | Назначение |
|---|---|
| postgres-1 | PostgreSQL 16 под управлением Patroni |
| postgres-2 | Второй узел PostgreSQL 16 под управлением Patroni |
| etcd | Хранение состояния кластера и блокировки лидера |
| postgres | HAProxy, направляющий SQL-подключения на primary |
| postgres-firewall | INPUT ACL перед SQL-точкой входа |

Patroni управляет репликацией и выбором primary. HAProxy проверяет `/primary` на REST API обоих узлов. Этот endpoint возвращает HTTP 200 для primary с блокировкой лидера. При отказе primary его активные проксируемые сессии закрываются, а новые подключения направляются на нового primary.

Новая сеть `pg-ha` с подсетью `172.28.40.0/24` объединяет узлы PostgreSQL, etcd и сетевое пространство HAProxy. Базы используют адреса `.11` и `.12`, etcd `.10`, HAProxy `.100`. Прикладные сервисы обращаются к `postgres:5432` через существующий вход в сети data.

Используются два узла PostgreSQL, один etcd и один HAProxy на одном ноутбуке. Этот стенд предназначен для демонстрации отказа одного узла PostgreSQL. etcd, HAProxy, Redis, RabbitMQ и сам ноутбук остаются отдельными точками отказа. Кластер RabbitMQ реализуется следующим этапом.

Patroni включает синхронный режим с одной синхронной репликой. При недоступности всех реплик допускается работа единственного primary, поскольку `synchronous_mode_strict` отключён. Для проверки сохранности подтверждённых записей перед отказом нужно дождаться синхронной реплики.

## Подготовка перехода

Команды выполняются в PowerShell из `C:\Projects\flowrun`. Переход создаёт новые тома `postgres-1-data`, `postgres-2-data` и `etcd-data`. Исходный том `postgres-data` сохраняется для отката. В рабочее приложение данные попадут после восстановления дампа в новый кластер.

Перед заменой Compose сохрани текущую конфигурацию и останови текущий стек.

```powershell
Copy-Item docker-compose.yml "$env:TEMP\flowrun-compose-before-pg-ha.yml"
docker compose down
```

Распакуй файлы пакета в корень проекта с заменой docker-compose.yml.

В `.env` добавь два разных пароля, заменив значения примера своими.

```dotenv
POSTGRES_REPLICATION_PASSWORD=change-this-replication-password
PATRONI_API_PASSWORD=change-this-patroni-password
```

В `.env.example` добавь те же имена с заглушками `change-me`. Файл `.env` должен игнорироваться Git.

Проверь Compose и собери образ.

```powershell
docker compose config --quiet
docker compose build postgres-1
```

Если проверка или сборка завершилась ошибкой, исправь её перед запуском.

## Первый запуск кластера

Запусти компоненты PostgreSQL.

```powershell
docker compose up -d --wait --wait-timeout 240 etcd postgres-1 postgres-2 postgres
docker compose ps
docker compose exec -T postgres-1 patronictl -c /etc/patroni/patroni.yml list
```

В списке ожидаются один Leader и одна работающая реплика. Для проверки отказа с сохранением подтверждённых записей дождись роли `Sync Standby` у второй ноды. Если кластер не собрался, сначала посмотри логи.

```powershell
docker compose logs --tail 80 etcd postgres-1 postgres-2 postgres
```

На этом этапе новая база flowrun создана пустой и готова к восстановлению. PostgreSQL и Patroni запускаются от системного пользователя postgres. Прикладной SQL-пользователь flowrun получает пароль из существующего POSTGRES_PASSWORD.

## Выбор текущего primary

Выполни блок в той же PowerShell-сессии, где будешь восстанавливать дамп. Он проверяет оба endpoint `/primary` и записывает имя primary в переменную.

```powershell
docker compose exec -T postgres-1 curl --fail --silent --max-time 3 -o /dev/null http://127.0.0.1:8008/primary
if ($LASTEXITCODE -eq 0) {
    $primary = "postgres-1"
    $replica = "postgres-2"
}
else {
    docker compose exec -T postgres-2 curl --fail --silent --max-time 3 -o /dev/null http://127.0.0.1:8008/primary
    if ($LASTEXITCODE -ne 0) {
        throw "No PostgreSQL primary is ready"
    }
    $primary = "postgres-2"
    $replica = "postgres-1"
}
Write-Host "Primary is $primary"
```

## Восстановление данных в новый кластер

Выбери проверенный дамп на ноутбуке. В выполненной проверке он назывался `flowrun_20261114_230437.dump`. Укажи своё фактическое имя файла, если оно отличается.

```powershell
$backupPath = ".\backups\flowrun_20261114_230437.dump"
Get-Item $backupPath
docker compose cp $backupPath "${primary}:/tmp/flowrun-migration.dump"
```

Выполни восстановление в новую пустую базу. Команда должна завершиться успешно перед запуском прикладных сервисов.

```powershell
docker compose exec -T $primary pg_restore -h 127.0.0.1 -U flowrun -d flowrun --exit-on-error --single-transaction --no-owner --no-privileges /tmp/flowrun-migration.dump
```

Этот шаг предназначен для первого восстановления в пустую базу. При повторном запуске уже выполненного восстановления возникнут конфликты существующих объектов. Сначала проверь, какие данные уже загружены.

Сравни данные на primary и реплике.

```powershell
docker compose exec -T $primary psql -h 127.0.0.1 -U flowrun -d flowrun -c "SELECT 'tasks' AS table_name, COUNT(*) FROM tasks UNION ALL SELECT 'task_runs', COUNT(*) FROM task_runs;"
docker compose exec -T $replica psql -h 127.0.0.1 -U flowrun -d flowrun -c "SELECT 'tasks' AS table_name, COUNT(*) FROM tasks UNION ALL SELECT 'task_runs', COUNT(*) FROM task_runs;"
docker compose exec -T $primary psql -h 127.0.0.1 -U flowrun -d flowrun -c "SELECT application_name, state, sync_state FROM pg_stat_replication;"
```

Ожидаются 4 задачи, 4 запуска на обоих узлах и соединение репликации в состоянии `streaming`, `sync`. Если во время подготовки были созданы новые записи, сравнивай с выбранным дампом.

После подтверждения данных запусти приложение.

```powershell
docker compose up -d --wait
Invoke-RestMethod http://localhost:8080/api/tasks | ConvertTo-Json -Depth 10
```

В браузере создай задачу demo, запусти её и получи succeeded.

## Демонстрация автоматического переключения

Перед каждым повторением заново определи primary блоком выше. Сначала проверь, что второй узел работает как Sync Standby. Создай через интерфейс тестовую задачу с узнаваемым названием и дождись завершения её запуска.

Начни измерение и останови текущий primary.

```powershell
$failoverTimer = [System.Diagnostics.Stopwatch]::StartNew()
docker compose stop $primary
```

Ожидай восстановления чтения через приложение максимум 90 секунд.

```powershell
$recovered = $false
do {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop http://localhost:8080/api/tasks
        if ($response.StatusCode -eq 200) {
            $recovered = $true
        }
    }
    catch {
        Write-Host "Waiting for PostgreSQL failover..."
    }
    if (-not $recovered) {
        Start-Sleep -Seconds 2
    }
} while (-not $recovered -and $failoverTimer.Elapsed.TotalSeconds -lt 90)
$failoverTimer.Stop()
Write-Host "Recovered: $recovered; elapsed seconds: $($failoverTimer.Elapsed.TotalSeconds)"
```

Проверь нового лидера через работающий узел.

```powershell
docker compose exec -T $replica patronictl -c /etc/patroni/patroni.yml list
```

Ожидается смена Leader. Убедись, что ранее созданная тестовая задача и результат доступны. Затем создай и выполни новую задачу demo через браузер, чтобы проверить запись после переключения.

Верни остановленный узел.

```powershell
docker compose start $primary
docker compose exec -T $replica patronictl -c /etc/patroni/patroni.yml list
```

Дождись возврата второго узла в состояние работающей реплики. При расхождении timeline Patroni использует pg_rewind. В конфигурации включены checksums и wal_log_hints для этой процедуры. Автоматическое удаление каталогов данных при ошибке rewind отключено настройками по умолчанию. При ошибке изучи логи узла.

## Резервное копирование после перехода

Сначала определи текущий primary блоком выше. Затем создай архив и скопируй его на ноутбук.

```powershell
$backupFile = "flowrun_ha_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".dump"
docker compose exec -T $primary pg_dump -h 127.0.0.1 -U flowrun -d flowrun -Fc -f /tmp/flowrun-ha-backup.dump
docker compose cp "${primary}:/tmp/flowrun-ha-backup.dump" "./backups/$backupFile"
```

Для проверки восстановления этого архива используй отдельную базу на primary и ранее проверенные команды createdb и pg_restore. Такую базу тоже будет реплицировать standby.

## Откат к исходной базе

Эти команды возвращают исходный Compose и исходный том postgres-data. При откате появится состояние старой базы на момент перехода. Для переноса новых записей из HA-кластера сначала нужен новый дамп и отдельное согласованное восстановление.

```powershell
docker compose down
Copy-Item "$env:TEMP\flowrun-compose-before-pg-ha.yml" docker-compose.yml
docker compose up -d --build --wait
```

## Параметры обслуживания

MTTR для демонстрации измеряется от команды остановки primary до успешного чтения списка задач через API. Отдельно проверяется создание новой задачи после переключения. Учебный целевой порог для этого сценария составляет 60 секунд. Он выбран с запасом к ttl 30 секунд, циклу Patroni 5 секунд, проверкам прокси и переподключению клиента. Фактическое время нужно записать после выполнения теста.

MTBF рассчитывается как суммарное время нормальной работы, делённое на число эксплуатационных отказов. Накопленных эксплуатационных данных для оценки MTBF сейчас недостаточно. Плановые отключения в демонстрации позволяют измерить восстановление. Частота реальных отказов оценивается по эксплуатационной статистике.

Учебный целевой SLO доступности API установлен в 99% за 30 дней. Для окна ровно 30 дней это соответствует бюджету недоступности 7 часов 12 минут. Доступность считается по успешным проверкам операции с PostgreSQL. Этот SLO является выбранной целью и ещё не подтверждён длительными измерениями.

В штатном синхронном режиме целевой RPO для подтверждённых записей равен нулю при отказе одного узла PostgreSQL. Когда primary работает без синхронной реплики, сохранность записей при его последующем отказе зависит от доступности его данных.

## Результаты проверки PostgreSQL HA

- Дамп восстановлен в новый кластер, данные появились на обоих узлах.
- После остановки postgres-2 роль Leader автоматически перешла к postgres-1.
- Контрольное время до успешного чтения API составило 31,28 секунды, включая ручные паузы между командами.
- После переключения новый запуск №38 завершился со статусом succeeded.
- После возврата postgres-2 он присоединился как Sync Standby с отставанием 0.