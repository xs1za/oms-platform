# OMS5 Shift Domain Design

> Статус: legacy design baseline. Документ подготовлен к удалению после проверки переноса остаточных задач в `BACKLOG.md` соответствующих проектов.

Актуальное описание уже реализованной модели OMS5 находится в `OMS5/README.md`: термины, границы владения, FSM смен, offer flow, public token endpoints, reporting period, auto-close endpoint, Kafka/RabbitMQ boundary и текущие API.

Актуальные задачи больше не ведутся в этом файле. Они распределены по backlog владельцев:

- `OMS3/BACKLOG.md` - report worker, постоянное хранилище `ReportTask`, результаты отчетов и report events.
- `OMS4/BACKLOG.md` - email templates, статусы доставки, обработка событий OMS5 и DLQ/requeue procedure.
- `OMS5/BACKLOG.md` - БД, Kafka consumers, shift status event contract, auth, UI boundaries, auto-close, absence flow, timesheet rules и projection conflicts.
- `platform/BACKLOG.md` - RabbitMQ production-hardening, worker manifests, CronJob и multi-repo UI repositories.

## Остаточные Решения

### OMS5 Persistence

Текущая OMS5-реализация использует in-memory состояние. Для production нужно перенести операционное состояние в БД с миграциями и транзакциями.

Критичные требования:

- атомарный `first accepted wins` через DB transaction и блокировку смены;
- персистентная `ShiftStatusHistory`;
- персистентные `ShiftOffer`, `ShiftOfferView`, `ShiftAssignment`, `Timesheet`;
- идемпотентность команд, где повтор запроса может создать дубликаты.

### Performer Projection Sync

Сейчас синхронизация исполнителя доступна через ручной endpoint `/performers/sync`. Production-вариант должен использовать Kafka consumer событий `OMS2`:

- `employee.created`;
- `employee.updated`;
- `employee.deactivated`.

Для projection нужно определить обработку конфликтов версий и устаревших событий.

### Shift Status Event Contract

Базовое событие `operations.shift.status_changed` публикуется `OMS5` после каждого успешного валидного перехода статуса смены. Kafka key сообщения: `shift_id`.

- `schema_version`: `1`;
- `event_id`: UUID, idempotency key для consumer-ов;
- `correlation_id`: UUID бизнес-операции;
- `occurred_at`: UTC ISO 8601;
- consumer `OMS3`: помечает report cache как stale;
- consumer `OMS4`: принимает решение о необходимости уведомления.

### Auth And Roles

OMS5 должен проверять JWT через `OMS1` и поддерживать роли:

- администратор;
- супервайзер;
- менеджер.

### UI Boundaries

Нужны отдельные UI repositories:

- `oms-admin-ui` - CRUD смен, импорт смен, подбор исполнителей, запуск offer campaigns, ручное назначение/снятие исполнителя, проверка табеля, обработка `absence`, просмотр `ShiftStatusHistory`.
- `oms-portal-ui` - public offer pages, просмотр деталей смены, `viewed`, `accept`, `decline` через одноразовый token, будущий личный кабинет исполнителя.

UI не владеет операционными данными и работает как API client к `OMS5`.

### Absence Flow

Нужно реализовать отдельный flow для подозрения на прогул:

```text
A40_EXECUTION -> A50_VERIFY
```

Смена остается в `A50_VERIFY` до ручной проверки менеджером.

Поля:

```text
verification_required = true
verification_reason = absence_suspected
```

После ручного подтверждения:

```text
A50_VERIFY -> A80_CLOSED
close_reason = failed
failure_reason = absence
```

Уведомление менеджеру должно идти через `OMS4` email template `shift_absence_review_required`.

### Auto Close CronJob

В OMS5 есть internal endpoint авто-закрытия незаполненных смен. Platform должна добавить Kubernetes CronJob, который запускает этот сценарий в конце 10-го числа месяца после отчетного периода.

### Timesheet Rules

Для табеля нужно добавить production-правила:

- пересечения смен;
- лимиты часов;
- статусы согласования;
- проверка отчетного периода;
- событие `operations.timesheet.verified`.

### Additional Events

Нужно добавить события:

- `operations.shift.assignment_cancelled`;
- `operations.timesheet.verified`.

### Future Offer Competition

MVP использует правило `first accepted wins`. Будущий конкурс между откликами исполнителей остается backlog-задачей после стабилизации MVP.

## Plan / Fact Checklist

| Item | Planned | Implemented | Owner backlog |
| --- | --- | --- | --- |
| Replace OMS5 in-memory state with DB, migrations and transactions | Yes | No | `OMS5/BACKLOG.md` |
| Add OMS5 Kafka consumer for `employee.created`, `employee.updated`, `employee.deactivated` | Yes | No | `OMS5/BACKLOG.md` |
| Stabilize `operations.shift.status_changed` event contract | Yes | Partial | `OMS5/BACKLOG.md` |
| Add OMS5 authorization and role checks through OMS1 | Yes | No | `OMS5/BACKLOG.md` |
| Add production absence flow | Yes | No | `OMS5/BACKLOG.md` |
| Add production timesheet rules | Yes | No | `OMS5/BACKLOG.md` |
| Add `operations.shift.assignment_cancelled` and `operations.timesheet.verified` | Yes | No | `OMS5/BACKLOG.md` |
| Add lightweight OMS3 report worker | Yes | No | `OMS3/BACKLOG.md`, `platform/BACKLOG.md` |
| Add OMS4 email templates in DB | Yes | No | `OMS4/BACKLOG.md` |
| Add Kubernetes CronJob for OMS5 auto-close | Yes | No | `platform/BACKLOG.md` |
| Add `oms-admin-ui` repo | Yes | No | `OMS5/BACKLOG.md`, `platform/BACKLOG.md` |
| Add `oms-portal-ui` repo | Yes | No | `OMS5/BACKLOG.md`, `platform/BACKLOG.md` |
