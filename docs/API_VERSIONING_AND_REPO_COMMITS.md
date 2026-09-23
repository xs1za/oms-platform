# API Versioning And Multi-Repo Commit Guide

Документ описывает правила версионирования API и рекомендуемые коммиты для выбранной схемы `Multi-Repo`: каждая команда владеет отдельным репозиторием своего сервиса, а общие контракты и инфраструктура живут в platform repo.

## Репозитории

Рекомендуемые GitHub repositories:

- `oms-platform` - общие Kubernetes манифесты, OpenAPI, Postman collection, генераторы и документация.
- `oms1-auth-service` - OMS1 Auth Service.
- `oms2-employee-service` - OMS2 Employee Service.
- `oms3-report-service` - OMS3 Report Service.
- `oms4-notification-service` - OMS4 Notification Service.
- `oms5-operations-service` - OMS5 Operations Service.

Старый Django-монолит не переносится в новые repositories. Связь с ним разорвана; при необходимости он восстанавливается из старого GitHub repository отдельно.

## Ownership

- Команда сервиса меняет только свой service repo.
- Команда platform меняет `oms-platform`.
- API-контракт меняется сначала в `oms-platform`, затем реализуется в service repo.
- Изменение public API без обновления `platform/contracts/openapi_oms_microservices.json` запрещено.

## Версионирование API

### Формат

Используем SemVer для общего API-контракта:

```text
MAJOR.MINOR.PATCH
```

Версия хранится в:

```text
platform/contracts/openapi_oms_microservices.json -> info.version
```

### PATCH

PATCH повышается при изменениях без изменения поведения API:

- исправление описаний;
- исправление examples;
- исправление Postman scripts/mock examples;
- уточнение документации;
- исправление неиспользуемых schemas без изменения requests/responses.

Пример:

```text
0.1.0 -> 0.1.1
```

### MINOR

MINOR повышается при backward-compatible изменениях:

- добавлен новый endpoint;
- добавлено необязательное поле request/response;
- добавлен новый response code без удаления старого поведения;
- добавлен новый enum value, если клиенты готовы к неизвестным значениям;
- добавлен новый service-specific health endpoint.

Пример:

```text
0.1.1 -> 0.2.0
```

### MAJOR

MAJOR повышается при breaking changes:

- удален endpoint;
- изменен URL или HTTP method;
- обязательное поле добавлено в request;
- поле удалено из response;
- тип поля изменен;
- response status изменен несовместимо;
- изменена схема авторизации.

Пример:

```text
0.2.0 -> 1.0.0
```

## Contract-First Workflow

1. Создать branch в `oms-platform`.
2. Изменить `platform/contracts/openapi_oms_microservices.json`.
3. Обновить generated Postman collection:

```powershell
python platform/scripts/generate_postman_collection.py
```

4. Проверить JSON:

```powershell
python -m json.tool platform/contracts/openapi_oms_microservices.json > $null
python -m json.tool platform/contracts/postman_oms_microservices_collection.json > $null
```

5. Открыть PR в `oms-platform` с описанием затронутых сервисов.
6. После принятия contract PR команда сервиса реализует изменение в своем repo.
7. Platform repo обновляет deployment manifests или docs, если изменились ports, env vars, probes или ingress routes.

## Kafka И Task Queue Boundaries

Kafka events в `platform/contracts` и service docs трактуются как domain/integration events, а не как команды на выполнение работы.

Используйте Kafka для:

- публикации фактов, которые уже произошли;
- независимых consumer groups;
- replay/audit;
- fan-out между сервисами.

Не используйте Kafka как универсальную замену task queue. Для командных jobs с retry, delayed retry, DLQ и обработкой одним worker используйте RabbitMQ/Celery или отдельный worker mechanism.

## Branch Naming

Для platform:

```text
contract/oms3-report-task-download
chore/k8s-pvc-oms2-postgres
docs/swagger-update-guide
```

Для service repos:

```text
feature/report-task-download
fix/health-trailing-slash
chore/k8s-probes
```

## Commit Style

Используем Conventional Commits:

```text
<type>(<scope>): <summary>
```

Типы:

- `feat` - новая функциональность.
- `fix` - исправление бага.
- `chore` - инфраструктура, build, зависимости, k8s без изменения business behavior.
- `docs` - документация.
- `test` - тесты.
- `refactor` - изменение кода без изменения поведения.
- `contract` - изменение API-контракта в platform repo.

## Рекомендуемые Коммиты По Репозиториям

### oms-platform

```text
chore(platform): add multi-repo workspace structure
contract(api): add OMS microservices OpenAPI contract
contract(api): add service-specific health endpoints
chore(postman): add OpenAPI-based Postman generator
chore(k8s): add kind, Kafka and ingress manifests
chore(k8s): add persistent volume claim for OMS2 Postgres
docs(k8s): document local Kubernetes operations
docs(api): document API versioning and repo commit workflow
docs(swagger): document Swagger UI publication flow
```

### oms1-auth-service

```text
feat(auth): add JWT user and service token endpoints
feat(auth): add token verification endpoint
feat(health): add liveness and readiness probes
chore(docker): add service Dockerfile
chore(k8s): add deployment, service, configmap and secret manifests
docs(oms1): document local, Docker and Kubernetes usage
```

### oms2-employee-service

```text
feat(employee): add Django employee API
feat(employee): add employee and address models
feat(health): add database and Kafka readiness checks
chore(db): add PostGIS deployment with persistent volume claim
chore(k8s): add deployment, service, configmap and secret manifests
docs(oms2): document Django and Kubernetes usage
```

### oms3-report-service

```text
feat(report): add asynchronous report task API
feat(report): add task status, download and cancel endpoints
feat(events): publish report lifecycle events to Kafka
feat(health): add slash and non-slash health endpoints
chore(k8s): add deployment, service and configmap manifests
docs(oms3): document async report workflow
```

### oms4-notification-service

```text
feat(notification): add email notification endpoint
feat(events): publish notification status events to Kafka
feat(health): add Kafka and SMTP readiness checks
feat(health): add slash and non-slash health endpoints
chore(k8s): add deployment, service, configmap and secret manifests
docs(oms4): document SMTP and MailHog usage
```

### oms5-operations-service

```text
feat(operations): add clients, shifts, tasks and timesheets APIs
feat(operations): add operations summary endpoint
feat(events): publish operations domain events to Kafka
feat(health): add slash and non-slash health endpoints
chore(k8s): add deployment, service and configmap manifests
docs(oms5): document operations API usage
```

## Cross-Repo Change Example

Если добавляется новый endpoint в OMS3:

1. `oms-platform`:

```text
contract(oms3): add report retry endpoint
chore(postman): regenerate collection from OpenAPI
```

2. `oms3-report-service`:

```text
feat(report): implement report retry endpoint
test(report): cover retry endpoint validation
```

3. `oms-platform`, если нужны deployment changes:

```text
chore(k8s): update OMS3 environment for retry endpoint
```

## Pull Request Checklist

Для platform PR:

- `platform/contracts/openapi_oms_microservices.json` обновлен.
- `platform/contracts/postman_oms_microservices_collection.json` перегенерирован.
- `python -m json.tool` прошел для обоих JSON файлов.
- Если изменились k8s manifests, выполнен `kubectl apply --dry-run=client`.
- Версия `info.version` повышена по SemVer.

Для service PR:

- Реализация соответствует принятому OpenAPI контракту.
- Health endpoints работают.
- Docker image собирается.
- K8s manifests валидны.
- README сервиса обновлен.
