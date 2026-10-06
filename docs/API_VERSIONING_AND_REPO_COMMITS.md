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

Не используйте Kafka как универсальную замену task queue. Для командных jobs с retry, delayed retry, DLQ и обработкой одним worker используйте RabbitMQ как shared command queue и lightweight Python workers без Celery.

Для Kafka consumer-ов, которые обрабатывают domain events, действуют отдельные правила:

- consumer должен быть идемпотентным по `event_id`;
- основной Kafka topic не используется как бесконечное хранилище долгоживущих бизнес-ошибок;
- при временной технической ошибке событие должно быть сохранено в `problem_events`, а повторная обработка должна планироваться через RabbitMQ DLX/TTL retry queues;
- при бизнес-ошибке, требующей действий операционного отдела, событие должно быть сохранено в `problem_events` со статусом `pending`;
- при ошибке контракта событие должно быть сохранено в `problem_events` со статусом `dlq`;
- Kafka offset основного topic можно коммитить только после безопасного сохранения проблемного события в `problem_events`;
- RabbitMQ-сообщение retry/reprocess должно содержать только `problem_event_id`, а полный payload хранится в `problem_events`.

Реализованный пример для смен:

- `OMS5` публикует Kafka event `operations.shift.status_changed` после успешного валидного перехода статуса смены;
- Kafka key события: `shift_id`, чтобы сохранить порядок событий по одной смене внутри partition;
- `OMS3` слушает событие и помечает report cache по `shift_id` как stale;
- `OMS4` слушает событие и принимает решение о необходимости уведомления;
- `OMS3` и `OMS4` используют `problem_events` для ошибок обработки Kafka-событий;
- автоматический retry для технических ошибок выполняется через RabbitMQ DLX/TTL queues: `5m -> 15m -> 1h`;
- после неуспешной попытки через `1h` событие переводится в `manual_review`;
- бизнес-ошибки, например `store_not_found`, переводятся в `pending`;
- ошибки контракта, например неподдерживаемый `schema_version`, переводятся в `dlq`;
- операционный доступ к problem events предоставляется через admin endpoints с заголовком `X-Operational-Role: operations`.

RabbitMQ topology для problem events:

| Exchange / Queue | Назначение |
| --- | --- |
| `problem-events.retry.exchange` | Direct exchange для публикации retry-сообщений |
| `problem-events.reprocess.exchange` | Direct exchange для сообщений повторной обработки |
| `problem-events.retry.5m` | TTL queue на 5 минут с DLX в `problem-events.reprocess.exchange` |
| `problem-events.retry.15m` | TTL queue на 15 минут с DLX в `problem-events.reprocess.exchange` |
| `problem-events.retry.1h` | TTL queue на 1 час с DLX в `problem-events.reprocess.exchange` |
| `problem-events.reprocess` | Очередь автоматической повторной обработки после TTL |
| `problem-events.reprocess.manual` | Очередь ручной повторной обработки после действия операционного пользователя |

RabbitMQ delayed message exchange plugin не используется. Задержка retry реализуется только через dead-letter exchange + TTL queues.

Для текущего MVP RabbitMQ добавляется как shared platform component для production-like background jobs: отправка email с retry, построение тяжелых отчетов, импорт/экспорт файлов, webhook processing или другие задачи, где потеря команды влияет на бизнес-сценарий.

Рекомендуемая эволюция после подтверждения бизнес-гипотезы:

| Этап | Решение | Обоснование |
| --- | --- | --- |
| Учебный прототип | Kafka only | Меньше инфраструктуры, достаточно для domain events |
| MVP в production-like окружении | Kafka + явные границы command tasks в коде | Не усложняем систему до появления реальной нагрузки, но не смешиваем events и commands |
| Первые критичные background jobs | RabbitMQ + lightweight workers | Получаем retry, delayed retry, DLQ и one-worker processing без Celery runtime |
| Рост нагрузки | Раздельное масштабирование API, workers, Kafka consumers | API остается быстрым, фоновые задачи масштабируются отдельно |
| Зрелый продукт | Observability, DLQ tooling, idempotency keys, worker autoscaling | Снижаем операционные риски и стоимость сопровождения |

Сравнение вариантов:

| Вариант | Плюсы | Минусы |
| --- | --- | --- |
| Kafka для всего | Простая инфраструктура на старте; replay/audit; fan-out | Неестественная модель для commands; retry/DLQ придется строить самостоятельно |
| RabbitMQ | Хорошая command queue; acknowledgements; routing; DLQ | Еще один broker в эксплуатации |
| Lightweight workers + RabbitMQ | Прозрачная реализация без Celery; явный контроль retry/DLQ; меньше runtime-магии | Retry/backoff/DLQ нужно реализовать дисциплинированно в worker code и RabbitMQ topology |
| Celery + RabbitMQ | Готовые retry/backoff patterns | Не выбран для MVP, добавляет Celery runtime и task-signature discipline |

Правило для PR: если изменение добавляет командную background task, PR должен явно указать RabbitMQ queue, retry/DLQ поведение и worker ownership.

Правило для PR: если изменение добавляет Kafka consumer, PR должен явно указать идемпотентность, обработку ошибок, `problem_events` поведение и влияние на commit Kafka offset.

## Task Codes

Для задач, инструкций, тест-кейсов, pull requests и коммитов используется единый формат кода:

```text
{PROJECT}-{AREA}-{NNNN}
```

Где:

- `PROJECT` - сервис или область владения;
- `AREA` - тип задачи;
- `NNNN` - номер внутри пары `PROJECT + AREA`.

Коды проектов:

| Код | Назначение |
| --- | --- |
| `OMS1` | OMS1 Auth Service |
| `OMS2` | OMS2 Employee Service |
| `OMS3` | OMS3 Report Service |
| `OMS4` | OMS4 Notification Service |
| `OMS5` | OMS5 Operations Service |
| `OMS` | Общие кросс-сервисные задачи и epics |
| `INFRA` | Инфраструктура: Kafka, RabbitMQ, Kubernetes, ingress, brokers |
| `QA` | Тест-планы и тест-кейсы |
| `DOC` | Документация, инструкции, OpenAPI/Postman |

Коды областей:

| Код | Назначение |
| --- | --- |
| `INT` | Интеграции, Kafka events, producer/consumer, межсервисные контракты |
| `BACK` | Backend business logic |
| `ADMIN` | Admin endpoints и операционные функции |
| `OPS` | Эксплуатация, стенды, deployment, topology |
| `API` | OpenAPI, Postman, API contracts |
| `QA` | Тестирование |
| `FIX` | Исправление дефектов |
| `SEC` | Безопасность и доступы |

Примеры кодов для текущей инициативы:

| Код | Название |
| --- | --- |
| `OMS-INT-0001` | Epic: интеграция событий изменения статуса смены |
| `OMS5-INT-0001` | Kafka-событие изменения статуса смены в OMS5 |
| `OMS3-INT-0001` | Consumer `operations.shift.status_changed` в OMS3 и stale report cache |
| `OMS4-INT-0001` | Consumer `operations.shift.status_changed` в OMS4 и решение по уведомлениям |
| `OMS3-ADMIN-0001` | `problem_events` и admin endpoints в OMS3 |
| `OMS4-ADMIN-0001` | `problem_events` и admin endpoints в OMS4 |
| `OMS3-INT-0002` | Retry/reprocess Kafka-событий через RabbitMQ в OMS3 |
| `OMS4-INT-0002` | Retry/reprocess Kafka-событий через RabbitMQ в OMS4 |
| `INFRA-OPS-0001` | RabbitMQ DLX/TTL topology для `problem_events` |
| `DOC-API-0001` | OpenAPI/Postman для `problem_events` |
| `QA-INT-0001` | Тест-план Kafka-события изменения статуса смены |
| `QA-INT-0002` | Тест-план retry/pending/DLQ для problem events |
| `QA-OPS-0001` | Тест-кейсы RabbitMQ DLX/TTL topology |
| `QA-ADMIN-0001` | Тест-кейсы admin endpoints `problem_events` |

Если GitHub Issue затрагивает несколько сервисов, предпочтительно разбить ее на сервисные задачи и инфраструктурную задачу. Если дробление временно нецелесообразно, используйте общий код `OMS-*` и перечислите сервисные коды в разделе связей.

Формат заголовка GitHub Issue:

```text
[OMS5-INT-0001][back/integration] Kafka-событие изменения статуса смены в OMS5
```

Формат блока связей:

```markdown
### Связанные задачи

- Epic: `OMS-INT-0001`
- Service tasks: `OMS3-INT-0001`, `OMS4-INT-0001`
- Infra: `INFRA-OPS-0001`
- Contract: `DOC-API-0001`
- QA: `QA-INT-0002`, `QA-OPS-0001`, `QA-ADMIN-0001`
```

Формат ссылки в коммите:

```text
Refs: OMS5-INT-0001
```

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
