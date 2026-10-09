# [OMS5-INT-0001] QA: Kafka-событие изменения статуса смены в OMS5

## Назначение

Проверка задачи `[OMS5-INT-0001][back/integration] Kafka-событие изменения статуса смены в OMS5`.

Цель: убедиться, что `OMS5` публикует Kafka-событие `operations.shift.status_changed` при каждом валидном переходе статуса смены, а `OMS3` и `OMS4` корректно обрабатывают событие идемпотентно по `event_id`.

## Проверяемая функциональность

- `OMS5` публикует `operations.shift.status_changed`.
- Kafka key равен `shift_id`.
- Payload соответствует контракту.
- Событие публикуется только при валидном переходе статуса.
- Событие не публикуется при невалидном переходе.
- `OMS3` получает событие и помечает internal report cache marker как stale.
- `OMS4` получает событие и принимает решение о необходимости уведомления.
- Повторная доставка события с тем же `event_id` не создает повторный бизнес-эффект.

## Настройка Тестового Стенда

На тестовом стенде должны быть запущены:

- Kafka.
- Topic `operations.shift.status_changed`.
- `OMS5`.
- `OMS3`.
- `OMS4`.
- Kafka consumer `OMS3` для `operations.shift.status_changed`.
- Kafka consumer `OMS4` для `operations.shift.status_changed`.
- Admin problem events endpoints `OMS3` и `OMS4` для проверки ошибок контракта.
- Postman collection, сгенерированная из актуального `openapi_oms_microservices.json`.

Проверить переменные окружения:

```text
OMS5:
SERVICE_NAME=OMS5
KAFKA_BOOTSTRAP_SERVERS=<test-kafka-bootstrap>

OMS3:
SERVICE_NAME=OMS3
KAFKA_BOOTSTRAP_SERVERS=<test-kafka-bootstrap>
KAFKA_SHIFT_STATUS_GROUP_ID=oms3.shift-status-cache

OMS4:
SERVICE_NAME=OMS4
KAFKA_BOOTSTRAP_SERVERS=<test-kafka-bootstrap>
KAFKA_SHIFT_STATUS_GROUP_ID=oms4.shift-status-notifications
```

Проверить наличие Kafka topic:

```text
operations.shift.status_changed
```

Если topic отсутствует, создать его стандартным способом, принятым на тестовом стенде.

## Настройка Production

На production должны быть запущены:

- Kafka.
- Topic `operations.shift.status_changed`.
- `OMS5`.
- `OMS3`.
- `OMS4`.
- Kafka consumer `OMS3`.
- Kafka consumer `OMS4`.

На production тестовые данные создавать нельзя.

Production-проверка ограничивается:

- проверкой наличия topic;
- проверкой consumer groups;
- проверкой логов запуска producer/consumer;
- smoke-check без создания искусственных смен, если нет согласованного production test client / sandbox data.

## Подготовка Тестовых Данных

Создать клиента:

```http
POST {{oms5_base_url}}/clients
Content-Type: application/json

{
  "name": "QA Client OMS5-INT-0001",
  "external_id": "QA-CLIENT-OMS5-INT-0001"
}
```

Сохранить `client_id = $.id`.

Создать смену:

```http
POST {{oms5_base_url}}/shifts
Content-Type: application/json

{
  "client_id": "{{client_id}}",
  "starts_at": "2027-01-20T09:00:00Z",
  "ends_at": "2027-01-20T18:00:00Z",
  "location": "QA location OMS5-INT-0001"
}
```

Сохранить `shift_id = $.id`.

Начальный статус должен быть `A00_DRAFT`.

## Kafka Contract

Topic:

```text
operations.shift.status_changed
```

Kafka key:

```text
shift_id
```

Payload:

```json
{
  "event_id": "uuid",
  "event_type": "operations.shift.status_changed",
  "schema_version": 1,
  "occurred_at": "2026-10-05T12:00:00Z",
  "correlation_id": "uuid",
  "producer": "OMS5",
  "shift_id": "uuid",
  "previous_status": "A20_SOURCING",
  "new_status": "A30_CHOICE",
  "reason": "performer_assigned"
}
```

## Тест-Кейсы

### TC-01. Валидный переход статуса публикует Kafka-событие

Шаги:

1. Выполнить переход:

```http
POST {{oms5_base_url}}/shifts/{{shift_id}}/transition
Content-Type: application/json

{
  "new_status": "A10_CONFIRM",
  "reason": "qa_confirmed",
  "actor_user_id": "qa-user"
}
```

2. Проверить сообщение в Kafka topic `operations.shift.status_changed`.

Ожидаемый результат:

- HTTP response `200`.
- В Kafka появилось одно событие.
- `event_type = operations.shift.status_changed`.
- `schema_version = 1`.
- `producer = OMS5`.
- `shift_id = {{shift_id}}`.
- `previous_status = A00_DRAFT`.
- `new_status = A10_CONFIRM`.
- `reason = qa_confirmed`.
- `event_id` заполнен UUID.
- `correlation_id` заполнен UUID.
- `occurred_at` заполнен UTC datetime.
- Kafka key равен `shift_id`.

### TC-02. Kafka key равен `shift_id`

Шаги:

1. Использовать событие из TC-01.
2. Проверить Kafka message key через Kafka UI / CLI / consumer logs.

Ожидаемый результат:

```text
message.key = {{shift_id}}
```

### TC-03. Невалидный переход не публикует событие

Шаги:

1. Для смены в статусе `A10_CONFIRM` выполнить невалидный переход:

```http
POST {{oms5_base_url}}/shifts/{{shift_id}}/transition
Content-Type: application/json

{
  "new_status": "A40_EXECUTION",
  "reason": "qa_invalid_transition",
  "actor_user_id": "qa-user"
}
```

2. Проверить Kafka topic.

Ожидаемый результат:

- HTTP response `409`.
- Новое событие `operations.shift.status_changed` для этого перехода не опубликовано.
- Статус смены не изменился.

### TC-04. Последовательные валидные переходы публикуются в правильном порядке

Шаги:

1. Выполнить переход в `A20_SOURCING`.

```http
POST {{oms5_base_url}}/shifts/{{shift_id}}/transition
Content-Type: application/json

{
  "new_status": "A20_SOURCING",
  "reason": "qa_sourcing",
  "actor_user_id": "qa-user"
}
```

2. Выполнить переход в `A30_CHOICE`.

```http
POST {{oms5_base_url}}/shifts/{{shift_id}}/transition
Content-Type: application/json

{
  "new_status": "A30_CHOICE",
  "reason": "qa_choice",
  "actor_user_id": "qa-user"
}
```

3. Проверить Kafka-события по `shift_id`.

Ожидаемый результат:

- Оба события имеют Kafka key = `shift_id`.
- События одной смены попали в одну Kafka partition.
- Порядок событий: `A10_CONFIRM -> A20_SOURCING`, затем `A20_SOURCING -> A30_CHOICE`.

### TC-05. OMS3 обрабатывает событие и помечает internal report cache marker как stale

Пояснение: этот тест проверяет Kafka consumer `OMS3` для `operations.shift.status_changed`. XLSX-отчет по сменам в актуальной реализации получает данные напрямую из `OMS5` через `GET /internal/shifts`; stale marker не является источником данных для XLSX-отчета.

Шаги:

1. Использовать валидное событие перехода статуса.
2. Проверить логи `OMS3`.

Ожидаемый результат:

- `OMS3` получил событие.
- В логах есть `event_id`, `correlation_id`, `shift_id`.
- В логах есть сообщение `Marked report cache as stale`.
- Internal stale marker по `shift_id` обновлен без повторного бизнес-эффекта для уже обработанного `event_id`.

### TC-06. OMS4 обрабатывает событие и принимает решение по уведомлению

Шаги:

1. Использовать событие перехода в статус `A30_CHOICE`.
2. Проверить логи `OMS4`.

Ожидаемый результат:

- `OMS4` получил событие.
- В логах есть `event_id`, `correlation_id`, `shift_id`.
- Зафиксировано решение о необходимости уведомления.
- Для статуса `A30_CHOICE` `notification_required = true`.

### TC-07. Идемпотентность OMS3 по `event_id`

Шаги:

1. Повторно отправить в Kafka то же событие с тем же `event_id`.
2. Проверить логи `OMS3`.

Ожидаемый результат:

- `OMS3` распознал дубль.
- Повторный бизнес-эффект не создан.
- Нет повторной инвалидации как нового события.

### TC-08. Идемпотентность OMS4 по `event_id`

Шаги:

1. Повторно отправить в Kafka то же событие с тем же `event_id`.
2. Проверить логи `OMS4`.

Ожидаемый результат:

- `OMS4` распознал дубль.
- Дубль notification decision не создан.
- Уведомление не дублируется.

### TC-09. Неподдерживаемая версия схемы отклоняется consumer-ом

Шаги:

1. Отправить в Kafka событие:

```json
{
  "event_id": "11111111-1111-1111-1111-111111111901",
  "event_type": "operations.shift.status_changed",
  "schema_version": 999,
  "occurred_at": "2026-10-05T12:00:00Z",
  "correlation_id": "22222222-2222-2222-2222-222222222901",
  "producer": "OMS5",
  "shift_id": "33333333-3333-3333-3333-333333333901",
  "previous_status": "A20_SOURCING",
  "new_status": "A30_CHOICE",
  "reason": "qa_invalid_schema"
}
```

2. Проверить problem events в `OMS3` и `OMS4`:

```http
GET {{oms3_base_url}}/admin/problem-events?event_type=operations.shift.status_changed
X-Operational-Role: operations
```

```http
GET {{oms4_base_url}}/admin/problem-events?event_type=operations.shift.status_changed
X-Operational-Role: operations
```

Ожидаемый результат:

- Consumers не применяют штатный бизнес-эффект.
- Ошибка обработки зафиксирована в `problem_events`.
- Событие попадает в `problem_events` со статусом `dlq` и `error_code = unsupported_schema_version`.

## Production Smoke Checklist

- Topic `operations.shift.status_changed` существует.
- Producer `OMS5` стартует без ошибок Kafka.
- Consumer group `oms3.shift-status-cache` существует или создается при старте `OMS3`.
- Consumer group `oms4.shift-status-notifications` существует или создается при старте `OMS4`.
- В логах нет ошибок подключения к Kafka.
- OpenAPI/Postman актуальны.
- Тестовые события на production не отправлять без отдельного согласования.
