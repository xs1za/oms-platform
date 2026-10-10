# Проектирование OMS Microservices

Документ фиксирует актуальную целевую структуру проекта после перехода на multi-repo подход и выделения общей platform-зоны.

## Рабочая Среда

- Рабочий каталог: `D:/ProjectsDocker/extrawork`
- ОС: Windows 11 PRO
- IDE: PyCharm 2023.1 PRO
- Python: 3.11
- Docker Desktop: 28.5.2
- Kubernetes: локальный kind-кластер `oms-cluster`
- Ingress host: `oms.local`

## Целевая Модель Репозиториев

Выбран вариант `Multi-Repo`.

Каждая команда владеет отдельным репозиторием своего микросервиса:

- `oms1-auth-service`
- `oms2-employee-service`
- `oms3-report-service`
- `oms4-notification-service`
- `oms5-operations-service`
- `oms-platform`

Текущий workspace `extrawork` используется как интеграционная сборка перед разносом по отдельным GitHub repositories.

## Текущая Структура Workspace

```text
extrawork/
  OMS1/
  OMS2/
  OMS3/
  OMS4/
  OMS5/
  platform/
    contracts/
    docs/
    k8s/
    scripts/
  README.md
  .gitignore
```

## Platform Зона

Папка `platform/` содержит общие артефакты, которые должны перейти в repository `oms-platform`.

```text
platform/k8s/
platform/contracts/
platform/scripts/
platform/docs/
```

### `platform/k8s/`

Содержит общие Kubernetes/kind manifests:

- `kind-cluster.yaml` - конфигурация kind-кластера.
- `namespace.yaml` - namespace `oms`.
- `kafka-dev.yaml` - single-node Kafka для локальной разработки.
- `ingress.yaml` - ingress routing `/oms1`-`/oms5` через `oms.local`.

### `platform/contracts/`

Содержит API-контракты и Postman collection:

- `openapi_oms_microservices.json` - source of truth для API.
- `postman_oms_microservices_collection.json` - Postman collection, генерируется из OpenAPI плюс overlay.

### `platform/scripts/`

Содержит automation scripts:

- `generate_postman_collection.py` - генератор Postman collection из OpenAPI и overlay.

### `platform/docs/`

Содержит эксплуатационную и архитектурную документацию:

- `K8S_FULL_SETUP.md`
- `POSTMAN_OPENAPI_WORKFLOW.md`
- `SWAGGER_UPDATE_GUIDE.md`
- `API_VERSIONING_AND_REPO_COMMITS.md`
- `проектирование.md`

## Микросервисы

### OMS1 Auth Service

Назначение:

- пользовательская авторизация;
- сервисная авторизация;
- выдача JWT;
- проверка токенов;
- публикация auth-событий в Kafka.

Основные endpoints:

- `POST /auth/token`
- `POST /auth/service-token`
- `GET /auth/verify`
- `GET /health`
- `GET /health/live`
- `GET /health/ready`

### OMS2 Employee Service

Назначение:

- Django-сервис сотрудников;
- перенос домена Employee из старого монолита;
- работа с PostGIS/PostgreSQL;
- Kafka event `employee.created`.

Особенности:

- `OMS2/manage.py` находится внутри папки `OMS2/`;
- старый корневой `manage.py` удален;
- `OMS2/k8s/postgres.yaml` использует PVC `oms2-postgres-data`;
- данные Postgres переживают пересоздание pod.

Основные endpoints:

- `GET /api/employees/`
- `POST /api/employees/`
- `GET /api/employees/{employee_id}/`
- `GET /health/`
- `GET /health/live/`
- `GET /health/ready/`

### OMS3 Report Service

Назначение:

- асинхронное создание отчетов;
- хранение статусов `ReportTask` пока остается в стартовом in-memory хранилище;
- публикация событий жизненного цикла отчетов в Kafka.

Основные endpoints:

- `POST /api/v1/report-tasks`
- `GET /api/v1/report-tasks/{task_id}`
- `GET /api/v1/report-tasks/{task_id}/download`
- `DELETE /api/v1/report-tasks/{task_id}`
- `GET /health`
- `GET /health/`
- `GET /health/live`
- `GET /health/live/`
- `GET /health/ready`
- `GET /health/ready/`

### OMS4 Notification Service

Назначение:

- отправка уведомлений;
- стартовый канал email;
- email-команды обрабатываются через RabbitMQ-backed lightweight worker;
- templates и delivery statuses пока не имеют постоянного хранилища;
- проверка Kafka и SMTP readiness;
- SMTP является soft dependency.

Основные endpoints:

- `POST /notifications/email`
- `GET /health`
- `GET /health/`
- `GET /health/live`
- `GET /health/live/`
- `GET /health/ready`
- `GET /health/ready/`

### OMS5 Operations Service

Назначение:

- операционные сущности;
- клиенты;
- смены;
- задачи;
- табели;
- сводка операций.

Текущее ограничение:

- операционное состояние пока хранится в in-memory структурах процесса;
- правило `first accepted wins` защищено только process-local lock и должно быть перенесено на транзакции и блокировки БД.

Основные endpoints:

- `POST /clients`
- `POST /shifts`
- `POST /tasks`
- `POST /timesheets`
- `GET /operations/summary`
- `GET /health`
- `GET /health/`
- `GET /health/live`
- `GET /health/live/`
- `GET /health/ready`
- `GET /health/ready/`

## Удаленный Legacy Django

Старый Django-монолит из корня workspace удален:

- `manage.py`
- `apps/`
- `root/`
- `templates/`
- `static/`
- `Dockerfile`
- `docker-compose.yaml`
- `requirements.txt`
- `postgres/`

Причина: старый проект уже есть в отдельном GitHub repository. Связь с ним в текущем workspace разорвана полностью. При необходимости он восстанавливается из старого repository отдельно.

## Runtime Data

Runtime-данные СУБД не хранятся в Git.

Удалена старая папка:

```text
postgres/
```

Для OMS2 в Kubernetes используется PVC:

```text
oms2-postgres-data
```

Физический каталог на host:

```text
D:/ProjectsDocker/extrawork/.runtime/oms2-postgres-data
```

Mount в kind node:

```text
/mnt/oms-data/oms2-postgres-data
```

Mount в Postgres pod:

```text
/var/lib/postgresql/data
```

Проверка PVC:

```powershell
kubectl -n oms get pvc oms2-postgres-data
```

## Отказ От In-Memory Хранилищ

Архитектурное решение: все бизнес-значимые состояния сервисов должны храниться в постоянном хранилище с миграциями. In-memory структуры допустимы только для локального cache/derived state, потеря которого не влияет на корректность бизнес-сценариев.

Основная СУБД для сервисов OMS: PostgreSQL.

Причины выбора PostgreSQL:

- сервисам нужны транзакции, миграции, индексы и консистентное хранение статусов;
- `OMS5` требует row-level locking для сценария `first accepted wins`;
- `OMS2` уже использует PostgreSQL/PostGIS и Django migrations;
- единая СУБД снижает эксплуатационную сложность MVP;
- PostgreSQL закрывает текущие потребности без преждевременного внедрения разных storage engines.

Специфичные хранилища можно добавлять только под отдельную подтвержденную нагрузку:

- object storage для файлов отчетов `OMS3`, но не вместо БД для `ReportTask` metadata;
- Redis для cache/rate limit/коротких distributed locks, но не как source of truth;
- OpenSearch для поиска и логов, но не для операционного состояния;
- ClickHouse для аналитики, если появится отдельная аналитическая нагрузка.

Правило владения данными:

- каждый сервис владеет своей БД или схемой и своими миграциями;
- прямой доступ одного сервиса к таблицам другого сервиса запрещен;
- межсервисная интеграция идет через HTTP API и Kafka/RabbitMQ;
- миграции запускаются отдельно для каждого сервиса в рамках его deployment lifecycle.

### Уже Реализовано

- `OMS2` уже использует PostgreSQL/PostGIS и Django migrations для employee/master data.
- `OMS4` уже использует RabbitMQ-backed lightweight email worker для команд отправки email; это не заменяет постоянное хранилище templates и delivery statuses.

### Актуальные Задачи

#### OMS1: Перенести Пользователей И Сервисных Клиентов В PostgreSQL

Заменить словари `users` и `service_clients` в `OMS1` на постоянное хранилище. Добавить таблицы пользователей и сервисных клиентов, хранить пароли и service secrets только в виде hash, добавить миграции и seed-данные для `admin`, `OMS2`, `OMS3`, `OMS4`, `OMS5`.

Затрагиваемые сервисы:

- `OMS1` как владелец auth-данных;
- `OMS2`, `OMS3`, `OMS4`, `OMS5` как service clients;
- `platform` для env/k8s/contract/docs обновлений.

#### OMS3: Перенести Статусы `ReportTask` В PostgreSQL

Заменить `report_tasks: dict` на таблицу `report_tasks` с жизненным циклом задачи: `queued`, `running`, `completed`, `failed`, `cancelled`, `expired`. Сохранять параметры запроса, progress, status URL, report ID, ссылку/metadata результата, ошибку, timestamps и TTL. Обновить endpoints создания, получения статуса, отмены и скачивания отчета.

Границы задачи:

- БД хранит metadata и состояние `ReportTask`;
- файлы отчетов остаются в filesystem на MVP или выносятся в object storage отдельной задачей;
- Kafka остается для событий жизненного цикла отчета;
- RabbitMQ-backed report worker из backlog OMS3 проектируется отдельно и должен работать с тем же persistent `ReportTask` state.

#### OMS4: Добавить Persistent Templates И Delivery Statuses

Добавить PostgreSQL-хранилище для notification/email templates и статусов доставки. Хранить template code, channel, subject/body, version, active flag, timestamps. Для delivery records хранить notification ID, recipient, channel, payload/template variables, статус `queued/sent/failed/retry/dlq`, retry count, error message, correlation ID и timestamps.

Границы задачи:

- API `POST /notifications/email` должен создавать delivery record со статусом `queued`;
- email worker должен обновлять delivery status после отправки, retry или DLQ;
- Kafka `notification.email_status` остается integration event, но не является source of truth;
- текущий RabbitMQ worker не считается реализацией persistent storage и остается частью transport/processing layer.

#### OMS5: Перенести Операционное Состояние В PostgreSQL

Заменить in-memory структуры `clients`, `performers`, `performers_by_employee_id`, `shifts`, `shift_status_history`, `offer_campaigns`, `shift_offers`, `offer_views`, `assignments`, `timesheets` на таблицы PostgreSQL с миграциями. Сохранить текущие API-сценарии и доменные события.

Ключевые таблицы:

- `clients`;
- `performers`;
- `shifts`;
- `shift_status_history`;
- `offer_campaigns`;
- `shift_offers`;
- `offer_views`;
- `assignments`;
- `timesheets`.

#### OMS5: Реализовать Транзакционный `first accepted wins`

Перенести acceptance flow из process-local `state_lock` на транзакцию PostgreSQL. Внутри транзакции заблокировать смену или offer через row-level lock, проверить доступность смены, создать assignment, пометить winning offer, перевести остальные активные offers в `lost`, обновить статус смены и записать history item. При конкурентном принятии возвращать корректный `409 Conflict`.

Критерии приемки:

- два параллельных accept-запроса не могут создать два назначения на одну смену;
- повторный accept проигравшего offer возвращает `offer_lost` или другой стабильный conflict code;
- история статусов и события Kafka соответствуют фактически выигравшему offer;
- поведение не зависит от количества replicas `OMS5`.

#### Platform: Стандартизировать PostgreSQL И Миграции Для OMS-Сервисов

Зафиксировать единый стандарт подключения к PostgreSQL для FastAPI-сервисов, миграции через Alembic, env-переменные, k8s Secret/ConfigMap, порядок запуска миграций в local/dev/prod и rollback-подход. Для `OMS2` оставить Django migrations как уже реализованный механизм.

Границы задачи:

- добавить/обновить local/kind manifests для БД сервисов, которым нужна persistence;
- не объединять бизнес-данные разных сервисов в одну общую схему без явной причины;
- описать backup/restore policy для production-like окружения;
- обновить README и runbook после появления новых DB dependencies.

## OpenAPI И Postman

OpenAPI является source of truth:

```text
platform/contracts/openapi_oms_microservices.json
```

Postman collection:

```text
platform/contracts/postman_oms_microservices_collection.json
```

Генерация:

```powershell
python platform/scripts/generate_postman_collection.py
```

Проверка:

```powershell
python -m json.tool platform/contracts/openapi_oms_microservices.json > $null
python -m json.tool platform/contracts/postman_oms_microservices_collection.json > $null
```

## Swagger UI

Общая Swagger UI страница запускается отдельным контейнером:

```powershell
docker run --rm `
  --name oms-swagger-ui `
  -p 8088:8080 `
  -e SWAGGER_JSON=/spec/platform/contracts/openapi_oms_microservices.json `
  -v "D:/ProjectsDocker/extrawork:/spec" `
  swaggerapi/swagger-ui:v5.17.14
```

Открывать:

```text
http://localhost:8088
```

Для этого контейнера не используется `/docs`. URL `/docs` относится только к встроенной документации FastAPI-сервисов, если конкретный сервис запущен напрямую или через `kubectl port-forward`.

## Kubernetes Локальный Запуск

Базовая последовательность:

```powershell
kind create cluster --config platform/k8s/kind-cluster.yaml
kubectl config use-context kind-oms-cluster

kubectl apply -f platform/k8s/namespace.yaml
kubectl apply -f platform/k8s/kafka-dev.yaml
kubectl apply -f OMS1/k8s/
kubectl apply -f OMS2/k8s/
kubectl apply -f OMS3/k8s/
kubectl apply -f OMS4/k8s/
kubectl apply -f OMS5/k8s/
kubectl apply -f platform/k8s/ingress.yaml
```

Проверка:

```powershell
curl http://oms.local/oms1/health
curl http://oms.local/oms2/health/
curl http://oms.local/oms3/health/ready
curl http://oms.local/oms4/health/ready
curl http://oms.local/oms5/health/ready
```

## API Versioning

Правила версионирования API и коммитов описаны в:

```text
platform/docs/API_VERSIONING_AND_REPO_COMMITS.md
```

## Kafka Sequence Diagram

Диаграмма межсервисного взаимодействия через Kafka находится в файле:

```text
platform/docs/kafka_interservice_sequence.puml
```

Формат: PlantUML sequence diagram.

Диаграмма покрывает:

- auth события OMS1;
- `employee.created` из OMS2;
- async report workflow OMS3;
- consumption report/employee/operations events;
- notification status events OMS4;
- operations domain events OMS5.

## Kafka Event Model

Kafka хранит события как durable event log в пределах настроенной retention policy и используется для domain/integration events, а не как классическая очередь задач.

Модель:

```text
Producer -> Kafka topic -> one or many independent consumer groups
```

Сообщение может быть прочитано несколькими сервисами независимо, если они находятся в разных consumer groups. Это подходит для domain/integration events:

- `auth.user_logged_in`
- `auth.service_token_issued`
- `employee.created`
- `report.requested`
- `report.completed`
- `report.cancelled`
- `notification.email_status`
- `operations.*_created`

Kafka оправдана для:

- event-driven integration между независимыми сервисами;
- replay событий;
- аудита;
- интеграции нескольких команд;
- fan-out, когда одно событие нужно нескольким потребителям.

Kafka не должна использоваться как универсальная замена task queue. Если сообщение является командой `сделай работу`, требует retry policy, delayed retry, DLQ или обработки ровно одним worker, используем RabbitMQ как shared command queue и lightweight Python workers без Celery.

Практическое правило:

- Kafka - domain/integration events.
- RabbitMQ + lightweight workers - commands, jobs, retries, DLQ, background workers.

## Отдельная Очередь Команд Для MVP

Текущий учебный проект развивается как `OMSx + platform` с целью довести систему до MVP, опубликовать ее в production-like окружение и проверить бизнес-гипотезу. Поэтому решение по очередям должно быть не только учебным, но и пригодным для дальнейшего развития без полной переделки архитектуры.

Решение на текущий этап:

- Kafka оставить как durable event log для domain/integration events в пределах настроенной retention policy.
- Не внедрять отдельную очередь команд до появления реального command/job сценария.
- Запроектировать границу так, чтобы RabbitMQ и lightweight workers можно было развивать без изменения публичных API.

Причина: преждевременное усложнение worker-механизма увеличит операционную сложность MVP. При этом архитектурно мы уже отделяем события `что произошло` от команд `сделай работу`, а для команд выбран RabbitMQ как shared command queue.

### Когда Kafka Достаточно

Kafka достаточно для MVP, если сообщения являются фактами:

- `employee.created` - сотрудник создан;
- `report.requested` - запрос отчета зарегистрирован;
- `report.completed` - отчет построен;
- `notification.email_status` - попытка отправки завершена;
- `operations.client_created` - клиент создан.

Потребители таких событий могут быть независимыми. Одно событие может читать OMS3 для отчетности, OMS4 для уведомлений и OMS5 для операционной аналитики через разные consumer groups.

### Когда Нужна Отдельная Очередь

Отдельная command/task queue нужна, если появляются задачи вида `сделай работу`, а не `что-то произошло`:

- отправить email конкретному адресату с retry;
- построить тяжелый отчет в фоне;
- выполнить импорт/экспорт файла;
- обработать webhook с гарантированной повторной доставкой;
- выполнить задачу строго одним worker;
- иметь delayed retry, backoff, DLQ и ручной requeue.

В этих случаях Kafka можно оставить для публикации итоговых событий, например `report.completed` или `notification.email_status`, но саму команду нужно выполнять через RabbitMQ и lightweight worker.

### Сравнение Вариантов

| Вариант | Плюсы | Минусы | Когда Выбирать |
| --- | --- | --- | --- |
| Только Kafka | Меньше инфраструктуры; уже есть в platform; хорошо подходит для event-driven integration; replay и audit из коробки | Неудобна как command queue; retry/DLQ требуют дополнительной реализации; сложно моделировать delayed retry и one-worker commands | Текущий MVP, пока события являются фактами и нет тяжелых фоновых jobs |
| RabbitMQ | Хорошо подходит для command queue; routing, acknowledgements, retry и DLQ являются естественной моделью; проще контролировать one-worker processing | Добавляет новый broker и эксплуатационную нагрузку; нужны manifests, monitoring, backup/upgrade правила; еще один failure mode | Когда появятся реальные команды `send_email`, `build_report`, `import_file` с retry/DLQ |
| Lightweight workers + RabbitMQ | Прозрачный worker code; нет Celery runtime; явный контроль queues, retry и DLQ | Retry/backoff/DLQ нужно реализовать дисциплинированно; больше собственного кода, чем с Celery | Выбранный вариант для OMS3/OMS4 MVP |
| Celery + RabbitMQ | Готовые retry, countdown, scheduling patterns; привычная модель tasks/workers | Celery добавляет свой runtime и discipline: идемпотентность задач, сериализация, версии task signatures; не выбран для MVP | Возможный future option, если lightweight workers станут сложными |
| Собственный worker без broker | Минимум зависимостей; можно начать с polling по БД | Риск самописной очереди; сложнее retry, locks, visibility timeout, DLQ; быстро становится техническим долгом | Только для очень простых задач или временного решения |

### Рекомендация Для Развития Проекта

Для MVP RabbitMQ используется как shared platform component там, где уже есть command/job сценарии:

- OMS3: `ReportTask` остается API-ресурсом; выполнение тяжелого отчета должно быть вынесено в RabbitMQ-backed lightweight report worker без изменения endpoint `/api/v1/report-tasks`.
- OMS4: команда `send_email` уже обрабатывается RabbitMQ-backed lightweight email worker, а результат публикуется в Kafka как `notification.email_status`.
- Platform: RabbitMQ manifests уже присутствуют; отдельные worker deployments добавляются по мере появления соответствующих workers.

Критерий внедрения отдельной очереди:

- есть минимум одна бизнес-критичная background task;
- нужна повторная доставка после сбоя worker;
- нужна DLQ для ручного разбора ошибок;
- задача должна выполняться одним worker, а не всеми consumer groups;
- потеря задачи влияет на пользовательский сценарий или деньги.

Если бизнес-гипотеза подтвердится, сохраняем `RabbitMQ + lightweight workers` для Python-сервисов OMS3/OMS4 и Kafka как durable event log для межсервисных событий в пределах настроенной retention policy.

Кратко:

- `PATCH` - исправления описаний, examples, docs без изменения API поведения.
- `MINOR` - backward-compatible добавления endpoints или необязательных полей.
- `MAJOR` - breaking changes.

## Проверки После Изменений

```powershell
python -m compileall -q platform/scripts OMS1 OMS2 OMS3 OMS4 OMS5
python -m json.tool platform/contracts/openapi_oms_microservices.json > $null
python -m json.tool platform/contracts/postman_oms_microservices_collection.json > $null
kubectl apply --dry-run=client -f platform/k8s/namespace.yaml -f platform/k8s/kafka-dev.yaml -f platform/k8s/ingress.yaml -f OMS1/k8s -f OMS2/k8s -f OMS3/k8s -f OMS4/k8s -f OMS5/k8s
```

Важно: `platform/k8s/kind-cluster.yaml` проверяется командой `kind create cluster --config`, а не `kubectl apply`, потому что это конфигурация kind, а не Kubernetes manifest.
