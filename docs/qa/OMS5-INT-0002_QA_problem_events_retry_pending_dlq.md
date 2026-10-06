# [OMS5-INT-0002] QA: Retry, Pending И DLQ Для Ошибок Обработки Kafka-Событий Смен

## Назначение

Проверка задачи `[OMS5-INT-0002][back/admin/integration] Retry, pending и DLQ для ошибок обработки Kafka-событий смен`.

Цель: убедиться, что ошибки обработки Kafka-событий смен сохраняются в `problem_events`, технические ошибки проходят RabbitMQ DLX/TTL retry, бизнес-ошибки доступны операционному отделу, ошибки контракта переводятся в `dlq`, а события можно направлять на ручную повторную обработку.

## Проверяемая Функциональность

- `problem_events`.
- RabbitMQ DLX/TTL retry queues.
- Статусы `pending`, `retry_scheduled`, `retrying`, `resolved`, `dlq`, `ignored`, `manual_review`.
- Admin endpoints для операционного отдела.
- Доступ по `X-Operational-Role: operations`.
- Ручной reprocess.
- Аудит ручных действий.
- Идемпотентность.
- Порядок reprocess по одной смене через `source_partition` и `source_offset`.

## Настройка Тестового Стенда

На тестовом стенде должны быть запущены:

- Kafka.
- RabbitMQ.
- `OMS3`.
- `OMS4`.
- Kafka consumers `OMS3` и `OMS4`.
- Problem event worker `OMS3`.
- Problem event worker `OMS4`.
- Postman collection из актуального OpenAPI.

Проверить переменные окружения:

```text
OMS3:
SERVICE_NAME=OMS3
KAFKA_BOOTSTRAP_SERVERS=<test-kafka-bootstrap>
KAFKA_SHIFT_STATUS_GROUP_ID=oms3.shift-status-cache
RABBITMQ_URL=<test-rabbitmq-url>
PROBLEM_EVENTS_RETRY_EXCHANGE=problem-events.retry.exchange
PROBLEM_EVENTS_REPROCESS_EXCHANGE=problem-events.reprocess.exchange
PROBLEM_EVENTS_RETRY_5M_QUEUE=problem-events.retry.5m
PROBLEM_EVENTS_RETRY_15M_QUEUE=problem-events.retry.15m
PROBLEM_EVENTS_RETRY_1H_QUEUE=problem-events.retry.1h
PROBLEM_EVENTS_REPROCESS_QUEUE=problem-events.reprocess
PROBLEM_EVENTS_MANUAL_REPROCESS_QUEUE=problem-events.reprocess.manual

OMS4:
SERVICE_NAME=OMS4
KAFKA_BOOTSTRAP_SERVERS=<test-kafka-bootstrap>
KAFKA_SHIFT_STATUS_GROUP_ID=oms4.shift-status-notifications
RABBITMQ_URL=<test-rabbitmq-url>
PROBLEM_EVENTS_RETRY_EXCHANGE=problem-events.retry.exchange
PROBLEM_EVENTS_REPROCESS_EXCHANGE=problem-events.reprocess.exchange
PROBLEM_EVENTS_RETRY_5M_QUEUE=problem-events.retry.5m
PROBLEM_EVENTS_RETRY_15M_QUEUE=problem-events.retry.15m
PROBLEM_EVENTS_RETRY_1H_QUEUE=problem-events.retry.1h
PROBLEM_EVENTS_REPROCESS_QUEUE=problem-events.reprocess
PROBLEM_EVENTS_MANUAL_REPROCESS_QUEUE=problem-events.reprocess.manual
```

## Создание RabbitMQ Очередей На Тестовом Контуре

Очереди создаются автоматически приложением при запуске problem event worker или при первой ошибке/reprocess.

Для предварительного создания topology запустить worker.

Для `OMS3`:

```powershell
D:\ProjectsDocker\extrawork\.venv\Scripts\python -m app.problem_event_worker
```

Рабочая директория:

```text
D:\ProjectsDocker\extrawork\OMS3
```

Для `OMS4`:

```powershell
D:\ProjectsDocker\extrawork\.venv\Scripts\python -m app.problem_event_worker
```

Рабочая директория:

```text
D:\ProjectsDocker\extrawork\OMS4
```

Проверить в RabbitMQ Management UI exchanges:

```text
problem-events.retry.exchange
problem-events.reprocess.exchange
```

Проверить queues:

```text
problem-events.retry.5m
problem-events.retry.15m
problem-events.retry.1h
problem-events.reprocess
problem-events.reprocess.manual
```

Проверить arguments:

| Queue | x-message-ttl | x-dead-letter-exchange | x-dead-letter-routing-key |
| --- | ---: | --- | --- |
| `problem-events.retry.5m` | `300000` | `problem-events.reprocess.exchange` | `problem-events.reprocess` |
| `problem-events.retry.15m` | `900000` | `problem-events.reprocess.exchange` | `problem-events.reprocess` |
| `problem-events.retry.1h` | `3600000` | `problem-events.reprocess.exchange` | `problem-events.reprocess` |

RabbitMQ delayed message exchange plugin не используется.

## Настройка Production

На production должны быть запущены:

- Kafka.
- RabbitMQ.
- `OMS3`.
- `OMS4`.
- Kafka consumers.
- Problem event workers.
- RabbitMQ topology.

На production тестовые данные не создаются.

Production-проверка:

- проверить наличие exchanges;
- проверить наличие queues;
- проверить TTL/DLX arguments;
- проверить, что problem event workers запущены;
- проверить логи подключения к RabbitMQ;
- проверить логи подключения к Kafka;
- проверить доступность admin endpoints только для авторизованного операционного доступа;
- не публиковать тестовые Kafka-события без согласования.

## Подготовка Тестовых Данных

Для проверки используются тестовые Kafka-события в topic:

```text
operations.shift.status_changed
```

Базовый валидный payload:

```json
{
  "event_id": "11111111-1111-1111-1111-111111111000",
  "event_type": "operations.shift.status_changed",
  "schema_version": 1,
  "occurred_at": "2026-10-05T12:00:00Z",
  "correlation_id": "22222222-2222-2222-2222-222222222000",
  "producer": "OMS5",
  "shift_id": "33333333-3333-3333-3333-333333333000",
  "previous_status": "A20_SOURCING",
  "new_status": "A30_CHOICE",
  "reason": "performer_assigned"
}
```

Для вызова admin endpoints использовать header:

```http
X-Operational-Role: operations
```

## Тест-Кейсы

### TC-01. Бизнес-ошибка `store_not_found` сохраняется в `pending`

Шаги:

1. Отправить в Kafka:

```json
{
  "event_id": "11111111-1111-1111-1111-111111112001",
  "event_type": "operations.shift.status_changed",
  "schema_version": 1,
  "occurred_at": "2026-10-05T12:00:00Z",
  "correlation_id": "22222222-2222-2222-2222-222222222001",
  "producer": "OMS5",
  "shift_id": "33333333-3333-3333-3333-333333333001",
  "previous_status": "A20_SOURCING",
  "new_status": "A30_CHOICE",
  "reason": "performer_assigned",
  "external_store_id": "missing"
}
```

2. Выполнить:

```http
GET {{oms4_base_url}}/admin/problem-events?error_code=store_not_found
X-Operational-Role: operations
```

Ожидаемый результат:

- `status = pending`.
- `error_type = business`.
- `error_code = store_not_found`.
- `attempt_count = 0`.
- `next_retry_at = null`.
- Retry queue не используется.

Повторить для `OMS3`.

### TC-02. Ошибка контракта сохраняется в `dlq`

Шаги:

1. Отправить событие с `schema_version = 999`.

```json
{
  "event_id": "11111111-1111-1111-1111-111111112002",
  "event_type": "operations.shift.status_changed",
  "schema_version": 999,
  "occurred_at": "2026-10-05T12:00:00Z",
  "correlation_id": "22222222-2222-2222-2222-222222222002",
  "producer": "OMS5",
  "shift_id": "33333333-3333-3333-3333-333333333002",
  "previous_status": "A20_SOURCING",
  "new_status": "A30_CHOICE",
  "reason": "qa_invalid_schema"
}
```

2. Проверить `GET {{oms4_base_url}}/admin/problem-events?error_code=unsupported_schema_version`.

Ожидаемый результат:

- `status = dlq`.
- `error_type = contract`.
- Автоматический retry не создается.

### TC-03. Техническая ошибка создает retry на 5 минут

Шаги:

1. Отправить событие с `reason = force_technical_error`.

```json
{
  "event_id": "11111111-1111-1111-1111-111111112003",
  "event_type": "operations.shift.status_changed",
  "schema_version": 1,
  "occurred_at": "2026-10-05T12:00:00Z",
  "correlation_id": "22222222-2222-2222-2222-222222222003",
  "producer": "OMS5",
  "shift_id": "33333333-3333-3333-3333-333333333003",
  "previous_status": "A20_SOURCING",
  "new_status": "A30_CHOICE",
  "reason": "force_technical_error"
}
```

2. Проверить `GET {{oms4_base_url}}/admin/problem-events?error_code=temporary_dependency_error`.
3. Проверить RabbitMQ queue `problem-events.retry.5m`.

Ожидаемый результат:

- `status = retry_scheduled`.
- `error_type = technical`.
- `attempt_count = 1`.
- `last_retry_interval = 5m`.
- `next_retry_at` заполнен.
- В `problem-events.retry.5m` есть сообщение.
- Сообщение содержит только `problem_event_id`.

### TC-04. Повторная техническая ошибка переводит retry на 15 минут

Шаги:

1. Дождаться TTL 5 минут или вручную перенаправить сообщение в `problem-events.reprocess`.
2. Проверить карточку события.

Ожидаемый результат:

- `attempt_count = 2`.
- `status = retry_scheduled`.
- `last_retry_interval = 15m`.
- Сообщение появилось в `problem-events.retry.15m`.

### TC-05. Третья техническая ошибка переводит retry на 1 час

Шаги:

1. Дождаться TTL 15 минут или вручную перенаправить сообщение в `problem-events.reprocess`.
2. Проверить карточку события.

Ожидаемый результат:

- `attempt_count = 3`.
- `status = retry_scheduled`.
- `last_retry_interval = 1h`.
- Сообщение появилось в `problem-events.retry.1h`.

### TC-06. После неуспешной попытки через 1 час событие переходит в `manual_review`

Шаги:

1. Дождаться TTL 1 час или вручную перенаправить сообщение в `problem-events.reprocess`.
2. Проверить карточку события.

Ожидаемый результат:

- `attempt_count = 4`.
- `status = manual_review`.
- `next_retry_at = null`.
- Новые retry-сообщения не создаются.

### TC-07. Kafka consumer не блокирует partition

Шаги:

1. Отправить technical error event.
2. Сразу отправить валидное событие с другим `shift_id`.

Ожидаемый результат:

- Первое событие попало в `problem_events`.
- Второе событие обработано штатно.
- Consumer продолжил читать Kafka.

### TC-08. Пользователь без прав не видит problem events

Шаги:

```http
GET {{oms4_base_url}}/admin/problem-events
```

И:

```http
GET {{oms4_base_url}}/admin/problem-events
X-Operational-Role: user
```

Ожидаемый результат: `403 Forbidden`.

### TC-09. Операционный пользователь видит problem events

Шаги:

```http
GET {{oms4_base_url}}/admin/problem-events
X-Operational-Role: operations
```

Ожидаемый результат:

- `200 OK`.
- Возвращается список.
- Есть поля `id`, `event_id`, `payload`, `error_type`, `error_code`, `status`, `attempt_count`.

### TC-10. Карточка problem event открывается по `problemEventId`

Шаги:

1. Получить список problem events.
2. Скопировать `id`.
3. Выполнить `GET {{oms4_base_url}}/admin/problem-events/{{param}}` с header `X-Operational-Role: operations`.

Ожидаемый результат:

- Возвращается карточка события.
- Есть `payload`.
- Есть Kafka metadata.
- Есть error details.
- Есть retry и audit fields.

### TC-11. Ручная повторная обработка создает RabbitMQ-сообщение

Шаги:

```http
POST {{oms4_base_url}}/admin/problem-events/{{param}}/reprocess
X-Operational-Role: operations
Content-Type: application/json

{
  "comment": "Первопричина устранена, повторить обработку"
}
```

Ожидаемый результат:

- `status = retry_scheduled`.
- `last_manual_action_by = operations`.
- `last_manual_comment` заполнен.
- В `problem-events.reprocess.manual` появилось сообщение.
- Сообщение содержит только `problem_event_id`.

### TC-12. Успешная повторная обработка переводит событие в `resolved`

Шаги:

1. Создать pending-событие.
2. Устранить причину ошибки.
3. Запустить ручной reprocess.
4. Дождаться обработки worker-ом.
5. Проверить карточку.

Ожидаемый результат:

- `status = resolved`.
- `resolved_at` заполнен.
- `resolved_by = reprocessor`.
- Дубль бизнес-эффекта не создан.

### TC-13. Повторная ошибка обновляет описание и счетчик попыток

Шаги:

1. Создать technical error event.
2. Запустить ручной reprocess.
3. Проверить карточку.

Ожидаемый результат:

- `attempt_count` увеличился.
- `last_failed_at` обновился.
- `error_code` актуален.
- `error_message` актуален.

### TC-14. Перевод в `ignored`

Шаги:

```http
POST {{oms4_base_url}}/admin/problem-events/{{param}}/ignore
X-Operational-Role: operations
Content-Type: application/json

{
  "comment": "Событие неактуально"
}
```

Ожидаемый результат:

- `status = ignored`.
- Заполнены поля аудита.

### TC-15. Перевод в `manual_review`

Шаги:

```http
POST {{oms4_base_url}}/admin/problem-events/{{param}}/manual-review
X-Operational-Role: operations
Content-Type: application/json

{
  "comment": "Нужен ручной разбор"
}
```

Ожидаемый результат:

- `status = manual_review`.
- `next_retry_at = null`.
- Заполнены поля аудита.

### TC-16. Перевод в `dlq`

Шаги:

```http
POST {{oms4_base_url}}/admin/problem-events/{{param}}/dlq
X-Operational-Role: operations
Content-Type: application/json

{
  "comment": "Событие некорректно"
}
```

Ожидаемый результат:

- `status = dlq`.
- `next_retry_at = null`.
- Заполнены поля аудита.

### TC-17. Повторная обработка не создает дубли

Шаги:

1. Отправить валидное событие.
2. Повторно отправить то же событие с тем же `event_id`.
3. Проверить бизнес-эффект.

Ожидаемый результат:

- Дубль не создан.
- Consumer пропустил повторную обработку по `event_id`.

### TC-18. Более позднее событие смены не обрабатывается раньше раннего нерешенного

Шаги:

1. Отправить первое проблемное событие по `shift_id`.
2. Отправить второе проблемное событие по тому же `shift_id`.
3. Попробовать reprocess второго события раньше первого.

Ожидаемый результат:

- Второе событие не становится `resolved`.
- У второго события фиксируется ожидание раннего события.
- `error_code = earlier_shift_event_unresolved`.

### TC-19. Фильтры problem events

Шаги:

```http
GET {{oms4_base_url}}/admin/problem-events?status=pending
X-Operational-Role: operations
```

```http
GET {{oms4_base_url}}/admin/problem-events?error_code=store_not_found
X-Operational-Role: operations
```

```http
GET {{oms4_base_url}}/admin/problem-events?error_type=business
X-Operational-Role: operations
```

```http
GET {{oms4_base_url}}/admin/problem-events?shift_id=33333333-3333-3333-3333-333333333001
X-Operational-Role: operations
```

```http
GET {{oms4_base_url}}/admin/problem-events?event_type=operations.shift.status_changed
X-Operational-Role: operations
```

Ожидаемый результат:

- Фильтры возвращают только подходящие записи.
- Пустой результат возвращается как `[]`.

### TC-20. RabbitMQ-сообщение содержит только `problem_event_id`

Шаги:

1. Создать technical error event.
2. Открыть RabbitMQ Management UI.
3. Посмотреть сообщение в `problem-events.retry.5m`.

Ожидаемый body:

```json
{
  "problem_event_id": "..."
}
```

Не должно быть полного payload события.

## Production Smoke Checklist

- Exchanges созданы.
- Queues созданы.
- TTL/DLX arguments корректны.
- Problem event workers запущены.
- Admin endpoints требуют `X-Operational-Role: operations`.
- OpenAPI/Postman актуальны.
- Kafka consumers подключены.
- RabbitMQ connection без ошибок.
- Тестовые Kafka-события не отправлять без отдельного согласования.
