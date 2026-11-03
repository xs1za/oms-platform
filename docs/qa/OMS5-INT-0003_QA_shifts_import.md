# [OMS5-INT-0003] QA: сброс dev-контура и импорт операторов, исполнителей и смен

## Проверяемое требование

Инструкция покрывает приёмочную проверку QA-контура после перехода на новую модель:

- сброс схем OMS1, OMS2 и OMS5 и пересоздание topic-ов Kafka;
- 5 операторов в OMS1 с периодами найма, назначениями на `operator_software` и ролями; `person_id` у операторов пустой;
- 20 исполнителей в OMS2 с контактами, паспортами, ИНН, СНИЛС, адресами, периодами работы и стадиями воронки;
- 70 клиентов и 780 смен ноября 2026 в OMS5;
- 20 строк `performers` в OMS5, собранных consumer-ом `people.performer.v1` из событий OMS2;
- повторный импорт не создаёт дубликатов.

## Состав поставки

| Артефакт | Путь | Назначение |
| --- | --- | --- |
| Сброс dev-контура | `platform/docs/qa/reset_dev_data.py` | Пересоздаёт схемы OMS1, OMS2, OMS5 и topic-и Kafka |
| Генератор и импортёр | `platform/docs/qa/generate_and_import.py` | Генерирует отчёт и пишет данные в OMS1, OMS2, OMS5 |
| Mock-отчёт | `platform/docs/qa/report_shifts.csv` | Входной файл импорта, 780 строк за ноябрь 2026 |
| Пример состояния | `platform/docs/qa/import_state.example.json` | Структура state-файла без персональных данных |
| Манифест Kafka | `platform/k8s/kafka-dev.yaml` | Создаёт `people.access.v1`, `people.performer.v1`, `operations.performer.v1` |

## Предусловия

Кластер Kind `oms-cluster`, namespace `oms`. Развёрнуты `oms1`, `oms2`, `oms2-outbox-worker`, `oms5`, их базы, Kafka и Job `kafka-topics-init`.

```powershell
kubectl -n oms get pods | Select-String "oms1|oms2|oms5|kafka"
```

Версии образов должны соответствовать связанным задачам:

- OMS1 содержит миграции `OMS1-BACK-0003` (периоды найма, назначения, роли) и `0004_bigint_person_ids`;
- OMS2 содержит `OMS2-BACK-0002`: таблицы `PerformerProfile`, `PerformerWorkPeriod`, `PersonDocument`, `PersonIdentifier`, `PersonAddress`, модули `apps/employees/funnel.py` и `apps/employees/operations_consumer.py`. Без этого модуля импорт завершается `ModuleNotFoundError: No module named 'apps.employees.funnel'`, а миграция `0004_performer_domain` не применяется;
- OMS5 содержит миграцию `002_performer_funnel_and_outbox`;
- deployment `oms2-operations-consumer` создаётся задачей `OMS2-BACK-0002`. Пока его нет, сквозной сценарий стадий `PERFORMER_FIRST_SHIFT_COMPLETED` выполняется командой `manage.py consume_operations_performer`, см. шаг 7.

Проверить, что старые таблицы OMS2 удалены миграцией:

```powershell
kubectl -n oms exec deploy/oms2 -- python manage.py showmigrations employees
```

Ожидается, что `0004_performer_domain` отмечен `[X]`.

## Порядок запуска

```text
1. reset_dev_data.py
2. OMS1 seed (admin и service clients) — выполняет init-контейнер deployment/oms1
3. import OMS1 (5 операторов)
4. import OMS2 (20 исполнителей)
5. import OMS5 (70 клиентов, 780 смен)
6. ожидание проекции 20 performers
7. проверки
```

Шаги 3 и 4 независимы. OMS5 не зависит от OMS2, но проекция появляется только после шага 4: события `people.performer_profile.changed` публикует `oms2-outbox-worker`, их читает consumer OMS5 `people.performer.v1`.

## Шаг 1. Сброс dev-контура

Скрипт требует Python 3.11 и `kubectl`. Внешние пакеты не нужны.

```powershell
cd D:\ProjectsDocker\extrawork
$env:ALLOW_DEV_RESET="yes"
python platform\docs\qa\reset_dev_data.py
```

Скрипт выводит цели сброса и ждёт подтверждение:

```text
Введите RESET для продолжения:
```

Что делает сброс:

1. Проверяет `kubectl config current-context`: контекст должен содержать `kind` или `oms-cluster`.
2. Берёт namespace из контекста (`oms` по умолчанию). Другой namespace принимается только с флагом `--namespace`.
3. Масштабирует в 0 `oms1`, `oms2`, `oms2-outbox-worker`, `oms5` и ждёт завершения подов. `oms2-operations-consumer` пропускается, если deployment ещё не создан.
4. Пересоздаёт схему `public` в базах OMS1, OMS2 и OMS5. Для OMS2 дополнительно выполняется `CREATE EXTENSION IF NOT EXISTS postgis`: без него миграции не создадут `PointField` в `Address.location`.
5. Удаляет topic-и `people.access.v1`, `people.performer.v1`, `operations.performer.v1` и ждёт завершения удаления.
6. Удаляет consumer groups `oms1.people.access`, `oms5.people.performer`, `oms2.operations.performer` и проверяет, что их нет.
7. Удаляет Job `kafka-topics-init` (и legacy-имя `kafka-topic-init`, если оно есть), применяет `platform/k8s/kafka-dev.yaml`, ждёт завершения Job и проверяет наличие трёх topic-ов.
8. Масштабирует сервисы в 1, ждёт `kubectl rollout status` и проверяет `/health/ready/` у OMS1, OMS2 и OMS5.

Скрипт не удаляет secrets, PVC, deployments, services и ingress, не трогает базы OMS3 и OMS4 и не переносит старые данные. Повторный запуск безопасен: пустая схема и отсутствующий topic не считаются ошибкой.

Код возврата:

| Ситуация | Код |
| --- | --- |
| Успешный сброс | 0 |
| Нет `ALLOW_DEV_RESET=yes` | 2 |
| Чужой context, чужой namespace без флага, отказ от подтверждения, ошибка шага | 1 |

Сброс без переменной `ALLOW_DEV_RESET` не выполняет ни одного изменения:

```powershell
Remove-Item Env:\ALLOW_DEV_RESET
python platform\docs\qa\reset_dev_data.py
"exit=$LASTEXITCODE"
```

Ожидается `exit=2`.

## Доступ к базам

Импорт пишет напрямую в PostgreSQL. Ingress публикует только HTTP, TCP-маршрутов для портов 5432 нет.

### Вариант A. В кластере

OMS2 использует Django ORM и требует GDAL/GEOS, поэтому шаг OMS2 выполняется в образе `oms2`. Шагу OMS1 нужен `bcrypt`, он есть в образе `oms1`. OMS5 использует `psycopg` и работает в обоих образах.

Пароль OMS5 для DSN берётся из секрета:

```powershell
cd D:\ProjectsDocker\extrawork\platform\docs\qa

$oms5Pass = kubectl -n oms get secret oms5-secret -o jsonpath='{.data.POSTGRES_PASSWORD}' | % { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }
$oms5Dsn  = "postgresql://oms5:$oms5Pass@oms5-postgres:5432/oms5"
$oms2Pod  = kubectl -n oms get pod -l app=oms2 -o jsonpath='{.items[0].metadata.name}'

Get-Content -Raw .\generate_and_import.py |
  kubectl -n oms exec -i $oms2Pod -- env "OMS5_DATABASE_URL=$oms5Dsn" "OMS2_PROJECT_DIR=/app" sh -c 'OMS2_DATABASE_URL="$DATABASE_URL" python - --from 2026-11-01 --to 2026-11-30 --report /tmp/report_shifts.csv --state /tmp/import_state.json'
```

`OMS2_DATABASE_URL` берётся из переменной `DATABASE_URL` пода, ключи `PERSON_DATA_ENCRYPTION_KEY` и `PERSON_IDENTIFIER_HMAC_KEY` — из `oms2-secret`, они уже в окружении пода.

Шаг OMS1 выполняется отдельно, в поде OMS1:

```powershell
$oms1Pass = kubectl -n oms get secret oms1-secret -o jsonpath='{.data.POSTGRES_PASSWORD}' | % { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }
$oms1Dsn  = "postgresql://oms1:$oms1Pass@oms1-postgres:5432/oms1"
$oms1Pod  = kubectl -n oms get pod -l app=oms1 -o jsonpath='{.items[0].metadata.name}'

Get-Content -Raw .\generate_and_import.py |
  kubectl -n oms exec -i $oms1Pod -- env "OMS1_DATABASE_URL=$oms1Dsn" python - --import-only --from 2026-11-01 --to 2026-11-30 --state /tmp/import_state.json
```

Состояние в подах разное: OMS2 пишет в свой `/tmp/import_state.json` исполнителей, OMS1 — операторов. Для отчёта о прогоне заберите оба файла на хост; в репозиторий их не коммитят.

```powershell
kubectl -n oms exec $oms2Pod -- cat /tmp/import_state.json | Set-Content C:\Temp\import_state_oms2.json -Encoding utf8
kubectl -n oms exec $oms1Pod -- cat /tmp/import_state.json | Set-Content C:\Temp\import_state_oms1.json -Encoding utf8
```

### Вариант B. С хоста

Сброс, генерация отчёта и шаг OMS1 работают с workspace venv:

```powershell
D:\ProjectsDocker\extrawork\.venv\Scripts\python.exe platform\docs\qa\reset_dev_data.py
```

Импорт OMS2 с хоста требует GDAL/GEOS, которых на Windows-хосте нет. Запускайте шаг OMS2 в контейнере, как в варианте A, даже если OMS1 и OMS5 выполняются локально.

Для локальных шагов нужны port-forward:

```powershell
kubectl -n oms port-forward deploy/oms1-postgres 5433:5432
kubectl -n oms port-forward deploy/oms5-postgres 5434:5432
```

## Шаг 2. Генерация отчёта

Генерация не требует БД. Период обязателен: `--from` и `--to` в формате `YYYY-MM-DD`.

```powershell
python generate_and_import.py --generate-only --from 2026-11-01 --to 2026-11-30
```

Ожидаемый вывод:

```text
[1/6] Отчёт сгенерирован: ...\report_shifts.csv (строк: 780, период 2026-11-01..2026-11-30)
[2/6] Отчёт проверен: 780 смен (2026-11-01..2026-11-30), дублей нет
```

Генератор детерминирован: повторный запуск даёт тот же SHA256.

## Шаг 3. Импорт операторов OMS1

Создаются пять учётных записей:

| Username | Display name | Роль | Период | Должность |
| --- | --- | --- | --- | --- |
| `qa.operator.1` | Иванов Пётр Сергеевич | `administrator` | `QA-OPS-001` | `operator_software` |
| `qa.operator.2` | Смирнова Ольга Андреевна | `manager` | `QA-OPS-002` | `operator_software` |
| `qa.operator.3` | Кузнецов Дмитрий Викторович | `supervisor` | `QA-OPS-003` | `operator_software` |
| `qa.operator.4` | Попова Елена Игоревна | `manager` | `QA-OPS-004` | `operator_software` |
| `qa.operator.5` | Соколов Артём Павлович | `supervisor` | `QA-OPS-005` | `operator_software` |

Правила:

- `users.person_id=null`, `users.scopes=["operations"]`, `users.is_active=true`;
- пароль из `QA_OPERATOR_PASSWORD`, по умолчанию `QaOperator!2026`; пароль записывается только при создании пользователя и не печатается;
- период и назначение начинаются `2026-10-01T00:00:00Z`, статус `active`;
- роль ссылается на `operator_employment_period_id` и `operator_position_assignment_id` OMS1, `valid_from=2026-10-01T00:00:00Z`;
- `admin` создаёт seed OMS1: период `ADMIN-001` и назначение на `operator_software`.

Повторный прогон ищет пользователя по `username`, период по `personnel_number`, назначение по `employment_period_id` и активному статусу, роль по `user_id`, `role_code` и `operator_employment_period_id`.

Ожидаемый первый прогон:

```text
[3/6] OMS1: операторы импортированы
  oms1: users_created=5, periods_created=5, assignments_created=5, roles_created=5
```

## Шаг 4. Импорт исполнителей OMS2

Создаются 20 персон `QA-EMP-006` … `QA-EMP-025` и профили `QA-PERF-001` … `QA-PERF-020`.

Распределение по стадиям:

| Индексы | Стадия | Тип оформления | Подтверждение | Медкнижка | Документы |
| --- | --- | --- | --- | --- | --- |
| 1-4 | `PERFORMER_PROFILE` | 2 `gph`, 2 `self_employed` | 2 `verified`, 1 `pending`, 1 `rejected` | `none` | нет |
| 5-8 | `PERFORMER_DOCS_PENDING` | 2 `gph`, 2 `self_employed` | `verified` | `none` | паспорт `pending`; у 5-6 ИНН `pending`, у 7-8 СНИЛС `pending` |
| 9-12 | `PERFORMER_READY_NON_MEDICAL` | 2 `gph`, 2 `self_employed` | `verified` | `none` | паспорт, ИНН, СНИЛС `verified` |
| 13-16 | `PERFORMER_READY_NON_FOOD` | 2 `gph`, 2 `self_employed` | `verified` | `non_food` | паспорт, ИНН, СНИЛС `verified` |
| 17-20 | `PERFORMER_READY_FOOD` | 2 `gph`, 2 `self_employed` | `verified` | `food` | паспорт, ИНН, СНИЛС `verified` |

Каждая персона импортируется в отдельной транзакции. Контакты, паспорт, ИНН, СНИЛС и адреса создаются с проверкой существующих записей по естественным ключам, поэтому повторный прогон не добавляет дочерние строки. Событие `people.performer_profile.changed` ставится в `IntegrationOutbox` внутри транзакции персоны и только при создании профиля.

Ожидаемый первый прогон:

```text
[4/6] OMS2: исполнители импортированы
  oms2: persons_created=20, profiles_created=20, work_periods_created=20, addresses_created=50, contacts_created=40, documents_created=16, identifiers_created=28
```

Персональные данные в логи не попадают: выводятся только `personnel_number` и стадия.

## Шаг 5. Импорт клиентов и смен OMS5

Импорт сохраняет прежнюю логику: 70 клиентов (11 головных, 33 дивизиона, 26 магазинов) и 780 смен ноября 2026 в статусе `A00_DRAFT`. Исполнители напрямую в OMS5 не пишутся.

Ожидаемый первый прогон:

```text
[5/6] OMS5: клиенты и смены импортированы
  oms5: clients_created=70, shifts_created=780, shifts_skipped=0
```

## Шаг 6. Проекция исполнителей

После импорта OMS2 в `employees_integrationoutbox` находится 20 неопубликованных событий `people.performer_profile.changed`. `oms2-outbox-worker` публикует их в `people.performer.v1`, consumer OMS5 создаёт 20 строк `performers`.

Скрипт ждёт не более 120 секунд (`--wait-seconds`), пока `performers` не достигнет 20, а неопубликованных событий OMS2 не останется. Флаг `--skip-wait` пропускает ожидание и проверки: он нужен, чтобы посмотреть промежуточное состояние, например 20 неопубликованных событий при остановленном outbox worker.

Ожидаемый вывод:

```text
[6/6] Проекция performers: готова
```

Если проекция не появилась:

1. Проверить `employees_integrationoutbox` в OMS2: `published_at` заполнен.
2. Проверить `person_event_inbox` и `person_consumer_state` в OMS5.
3. Проверить логи `oms2-outbox-worker` и `oms5`.
4. Проверить, что topic `people.performer.v1` создан.
5. Убедиться, что consumer group `oms5.people.performer` не осталась с offset-ами от удалённого topic-а: сброс удаляет её вместе с topic-ом.

## Шаг 7. Проверки

Скрипт выполняет проверки автоматически и завершает работу с кодом 1 при расхождении. SQL ниже нужен для ручной приёмки.

### OMS1

```sql
SELECT count(*) FROM users WHERE username LIKE 'qa.operator.%'; -- 5
SELECT count(*) FROM operator_employment_periods WHERE personnel_number LIKE 'QA-OPS-%'; -- 5
SELECT count(*) FROM operator_employment_periods; -- 6 с ADMIN-001
SELECT count(*) FROM operator_position_assignments; -- 6
SELECT count(*) FROM access_role_assignments WHERE role_code IN ('manager', 'supervisor', 'administrator'); -- 6
SELECT count(*) FROM users WHERE username LIKE 'qa.operator.%' AND person_id IS NOT NULL; -- 0
```

Связь ролей с OMS1:

```sql
SELECT u.username, p.personnel_number, a.position_code, r.role_code,
       (r.operator_employment_period_id = p.id) AS period_link,
       (r.operator_position_assignment_id = a.id) AS position_link
FROM users u
JOIN operator_employment_periods p ON p.user_id = u.id
JOIN operator_position_assignments a ON a.employment_period_id = p.id
JOIN access_role_assignments r ON r.user_id = u.id AND r.operator_employment_period_id = p.id
ORDER BY u.username;
```

У всех шести строк `period_link` и `position_link` равны `t`.

Вход оператора и `/auth/verify`:

```powershell
kubectl -n oms exec deploy/oms1 -- python -c "import json, urllib.request; req=urllib.request.Request('http://127.0.0.1:8000/auth/token', data=json.dumps({'username':'qa.operator.1','password':'QaOperator!2026'}).encode(), headers={'Content-Type':'application/json'}); t=json.load(urllib.request.urlopen(req)); req=urllib.request.Request('http://127.0.0.1:8000/auth/verify', headers={'Authorization':'Bearer '+t['access_token']}); print(json.load(urllib.request.urlopen(req)))"
```

Ожидается `person_id: None` и роль `administrator`.

### OMS2

```sql
SELECT count(*) FROM employees_employeepersinfo; -- 20
SELECT count(*) FROM employees_performerprofile; -- 20
SELECT count(*) FROM employees_performerengagementtypechange; -- 20
SELECT count(*) FROM employees_performerworkperiod; -- 20
SELECT count(*) FROM employees_personaddress; -- 50
SELECT count(*) FROM employees_personcontact; -- 40
SELECT count(*) FROM employees_persondocument WHERE document_type = 'passport'; -- 16
SELECT count(*) FROM employees_personidentifier; -- 28
SELECT to_regclass('employees_employmentepisode'); -- NULL
SELECT to_regclass('employees_positionassignment'); -- NULL
SELECT to_regclass('employees_externalmembership'); -- NULL
SELECT count(*) FROM employees_integrationoutbox WHERE published_at IS NULL; -- 0 после публикации
```

Распределение стадий:

```sql
SELECT funnel_stage, count(*) FROM employees_performerprofile GROUP BY funnel_stage ORDER BY funnel_stage;
```

| Стадия | Количество |
| --- | --- |
| `PERFORMER_PROFILE` | 4 |
| `PERFORMER_DOCS_PENDING` | 4 |
| `PERFORMER_READY_NON_MEDICAL` | 4 |
| `PERFORMER_READY_NON_FOOD` | 4 |
| `PERFORMER_READY_FOOD` | 4 |

Документы и идентификаторы по статусам:

```sql
SELECT verification_status, count(*) FROM employees_persondocument GROUP BY 1;
-- pending 4, verified 12
SELECT verification_status, count(*) FROM employees_personidentifier GROUP BY 1;
-- pending 4, verified 24
```

Проверка до публикации. Останавливается outbox worker, затем выполняется импорт с `--skip-wait`: флаг пропускает ожидание проекции и проверки, поэтому события остаются в `employees_integrationoutbox` неопубликованными. Проверка имеет смысл только на первом прогоне после сброса: повторный импорт новых событий не создаёт.

```powershell
$oms5Pass = kubectl -n oms get secret oms5-secret -o jsonpath='{.data.POSTGRES_PASSWORD}' | % { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }
$oms5Dsn  = "postgresql://oms5:$oms5Pass@oms5-postgres:5432/oms5"
$oms2Pod  = kubectl -n oms get pod -l app=oms2 -o jsonpath='{.items[0].metadata.name}'

kubectl -n oms scale deployment/oms2-outbox-worker --replicas=0
kubectl -n oms rollout status deployment/oms2-outbox-worker --timeout=120s

Get-Content -Raw .\generate_and_import.py |
  kubectl -n oms exec -i $oms2Pod -- env "OMS5_DATABASE_URL=$oms5Dsn" "OMS2_PROJECT_DIR=/app" sh -c 'OMS2_DATABASE_URL="$DATABASE_URL" python - --from 2026-11-01 --to 2026-11-30 --report /tmp/report_shifts.csv --state /tmp/import_state.json --skip-wait'
```

Ожидаемый конец вывода:

```text
[6/6] Ожидание проекции и проверки пропущены (--skip-wait)
[6/6] Импорт завершён
  oms2: persons_created=20, profiles_created=20, work_periods_created=20, addresses_created=50, contacts_created=40, documents_created=16, identifiers_created=28
  oms5: clients_created=70, shifts_created=780, shifts_skipped=0
```

Проверка событий:

```sql
SELECT event_type, count(*) FROM employees_integrationoutbox
WHERE published_at IS NULL GROUP BY 1;
-- people.performer_profile.changed | 20
```

После проверки вернуть worker и повторить импорт уже без `--skip-wait`, чтобы дождаться проекции и выполнить проверки:

```powershell
kubectl -n oms scale deployment/oms2-outbox-worker --replicas=1
kubectl -n oms rollout status deployment/oms2-outbox-worker --timeout=120s

Get-Content -Raw .\generate_and_import.py |
  kubectl -n oms exec -i $oms2Pod -- env "OMS5_DATABASE_URL=$oms5Dsn" "OMS2_PROJECT_DIR=/app" sh -c 'OMS2_DATABASE_URL="$DATABASE_URL" python - --import-only --from 2026-11-01 --to 2026-11-30 --report /tmp/report_shifts.csv --state /tmp/import_state.json'
```

### OMS5

```sql
SELECT count(*) FROM clients; -- 70
SELECT count(*) FROM shifts; -- 780
SELECT count(*) FROM performers; -- 20
SELECT count(*) FROM performers WHERE engagement_type IS NULL; -- 0
SELECT count(*) FROM performers WHERE funnel_stage IS NULL; -- 0
SELECT count(*) FROM operations_outbox WHERE published_at IS NULL; -- 0
SELECT funnel_stage, count(*) FROM performers GROUP BY 1 ORDER BY 1;
```

Распределение стадий в проекции совпадает с OMS2: по 4 на каждую из пяти стадий.

## Шаг 8. Повторный импорт

Повторить шаги 3, 4 и 5 без сброса. Ожидается:

```text
oms1: users_created=0, periods_created=0, assignments_created=0, roles_created=0
oms2: persons_created=0, profiles_created=0, work_periods_created=0, addresses_created=0, contacts_created=0, documents_created=0, identifiers_created=0
oms5: clients_created=0, shifts_created=0, shifts_skipped=780
```

Дополнительно:

- число строк в `employees_personcontact`, `employees_persondocument`, `employees_personidentifier`, `employees_personaddress` не меняется;
- новых строк в `employees_integrationoutbox` нет;
- `performers` в OMS5 остаётся 20;
- state-файл обновляет `generated_at`, наборы `operators` и `performers` не меняются.

## Шаг 9. Сквозной сценарий стадий завершения

Стадии `PERFORMER_BOOKED_SHIFT`, `PERFORMER_FIRST_SHIFT_COMPLETED` и `PERFORMER_FIFTH_SHIFT_COMPLETED` импорт не создаёт: их формирует поток фактов `operations.performer.v1`.

Сценарий для одного исполнителя:

1. Создать смену в OMS5, перевести её в `A10_CONFIRM`, затем в `A20_SOURCING`.
2. Создать offer campaign на исполнителя со стадией `PERFORMER_READY_*` и принять оффер.
3. Перевести смену в `A40_EXECUTION`, `A50_VERIFY`, `A60_SETTLE`. Переход в `A60_SETTLE` создаёт один факт завершения.
4. Обработать событие consumer-ом OMS2 (`deployment/oms2-operations-consumer` или `python manage.py consume_operations_performer --once`).
5. После первой завершённой смены стадия исполнителя — `PERFORMER_FIRST_SHIFT_COMPLETED`, после пятой — `PERFORMER_FIFTH_SHIFT_COMPLETED`.

Проверка фактов:

```sql
SELECT fact_type, count(*) FROM employees_performershiftfact GROUP BY 1; -- assigned/completed
SELECT assignment_id, fact_type, count(*) FROM employees_performershiftfact
GROUP BY assignment_id, fact_type HAVING count(*) > 1; -- 0 строк
```

## State-файл

Файл состояния версии 3 содержит только идентификаторы:

```json
{
  "version": 3,
  "generated_at": "2026-11-01T09:00:00Z",
  "operators": {
    "QA-OPS-001": {
      "user_id": "d4e5f607-1a2b-4c3d-8e9f-0a1b2c3d4e66",
      "username": "qa.operator.1"
    }
  },
  "performers": {
    "QA-PERF-001": {
      "person_id": 6,
      "personnel_number": "QA-EMP-006"
    }
  }
}
```

Правила:

- запись атомарная: временный файл рядом, затем `os.replace`;
- состояние сливается с предыдущим, а не перезаписывается;
- пароли, телефоны, email и номера документов в файл не попадают;
- state-файл конкретного прогона в Git не коммитится, в репозитории лежит только `import_state.example.json`.

## Тест-кейсы

| ID | Сценарий | Ожидание |
| --- | --- | --- |
| TC-01 | Сброс без `ALLOW_DEV_RESET` | код 2, базы не меняются |
| TC-02 | Сброс с namespace из контекста, отличным от `oms` | отказ, код 1 |
| TC-03 | Подтверждение, отличное от `RESET` | код 1, изменений нет |
| TC-04 | Успешный сброс | схемы пусты, topics созданы, readiness 200 |
| TC-05 | OMS2 после сброса | расширение `postgis`, колонка `employees_address.location` |
| TC-06 | Первый импорт | счётчики из шагов 3-5 |
| TC-07 | Вход `qa.operator.1` | 200, `/auth/verify` возвращает `person_id=null` |
| TC-08 | Роли операторов | ссылаются на OMS1 period и assignment |
| TC-09 | OMS2 | 20 персон, нет `operator_software`, стадии по 4 |
| TC-10 | OMS5 | 70 клиентов, 780 смен, 20 исполнителей |
| TC-11 | Outbox до публикации | 20 неопубликованных `people.performer_profile.changed` |
| TC-12 | Повторный импорт | все `created=0`, `shifts_skipped=780` |
| TC-13 | State-файл и логи | нет паролей, телефонов, email и номеров документов |
| TC-14 | Первая завершённая смена | `PERFORMER_FIRST_SHIFT_COMPLETED` |
| TC-15 | Пятая завершённая смена | `PERFORMER_FIFTH_SHIFT_COMPLETED` |

## Ограничения

- Сброс удаляет topic-и и старые события Kafka. Для dev-контура это допустимо, для production скрипт не предназначен.
- OMS3 и OMS4 не сбрасываются: их данные предыдущих прогонов остаются.
- Импорт не переносит старые QA-данные: после сброса набор создаётся заново.
- Импорт OMS2 требует GDAL/GEOS, поэтому с Windows-хоста шаг выполняется в контейнере `oms2`.
- Пароль операторов общий, задаётся `QA_OPERATOR_PASSWORD`; для общих стендов нужно отдельное значение.
- Импорт не удаляет данные: чтобы пересоздать период смен, нужен сброс.

## Критерии приёмки

- сброс без `ALLOW_DEV_RESET` завершается с кодом 2 и не меняет базы;
- после сброса схемы OMS1, OMS2 и OMS5 пусты, deployments запущены, readiness 200;
- topic-и `people.access.v1`, `people.performer.v1` и `operations.performer.v1` существуют;
- consumer groups `oms1.people.access`, `oms5.people.performer` и `oms2.operations.performer` удалены до запуска consumer-ов;
- в OMS1 5 QA-операторов и `admin`: 6 периодов, 6 назначений, 6 ролей; у QA-операторов `person_id=null`;
- в OMS2 20 персон, 20 профилей, 20 записей аудита, 20 периодов работы, 50 адресов, 40 контактов, 16 паспортов и 28 идентификаторов; записей `operator_software` нет;
- стадии воронки распределены по 4 на каждую из пяти стадий;
- в OMS5 70 клиентов и 780 смен; после проекции 20 исполнителей с заполненными `engagement_type` и `funnel_stage`;
- в `employees_integrationoutbox` 20 неопубликованных событий профиля до публикации и 0 после;
- в `operations_outbox` нет неопубликованных строк;
- повторный импорт даёт `created=0` по всем счётчикам и не меняет дочерние таблицы OMS2;
- state-файл и логи не содержат паролей, телефонов, email и номеров документов.

## Что приложить к отчёту

- Вывод сброса и вывод первого и повторного импорта по каждому шагу.
- `SHA256` файла `report_shifts.csv` до и после повторной генерации.
- Результаты SQL-проверок OMS1, OMS2 и OMS5.
- Содержимое state-файлов после первого прогона.
- Версии образов `oms1`, `oms2` и `oms5`.
