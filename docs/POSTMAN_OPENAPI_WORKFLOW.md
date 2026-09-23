# Workflow: OpenAPI и Postman Collection

Файлы лежат в `platform/`:

- `platform/contracts/openapi_oms_microservices.json`
- `platform/contracts/postman_oms_microservices_collection.json`
- `platform/scripts/generate_postman_collection.py`

## Главный принцип

`platform/contracts/openapi_oms_microservices.json` - source of truth для API-контрактов.

`platform/contracts/postman_oms_microservices_collection.json` - сценарная Postman collection, которая хранит examples, mock responses, scripts и удобную структуру папок.

## Что менять в OpenAPI

Меняйте `platform/contracts/openapi_oms_microservices.json`, если изменились:

- URL endpoint;
- HTTP method;
- request body;
- JSON Schema;
- response schema;
- status codes;
- API description;
- request examples, которые должны быть источником истины.

Именно из OpenAPI Postman корректно отображает `Body -> Schema`.

## Что менять в Postman Collection

Меняйте `platform/contracts/postman_oms_microservices_collection.json`, если нужно изменить:

- Postman examples для mock server;
- test scripts;
- pre-request scripts;
- collection variables;
- порядок или названия папок;
- сценарии вроде async polling;
- mock-specific responses.

Не используйте collection как source of truth для JSON Schema. Postman не гарантирует отображение таких схем в UI `Body -> Schema` для обычной collection.

## Порядок внесения изменений

1. Измените API-контракт в `platform/contracts/openapi_oms_microservices.json`.
2. Если нужны новые examples/scripts, добавьте или поправьте их в `platform/contracts/postman_oms_microservices_collection.json`.
3. Запустите генератор в обычном overlay-режиме:

```powershell
python platform/scripts/generate_postman_collection.py
```

4. Проверьте JSON-файлы:

```powershell
python -m json.tool platform/contracts/openapi_oms_microservices.json > $null
python -m json.tool platform/contracts/postman_oms_microservices_collection.json > $null
```

5. Импортируйте или обновите файлы в Postman.

## Как работает генератор

`platform/scripts/generate_postman_collection.py` берет:

- схемы, описания и request examples из `platform/contracts/openapi_oms_microservices.json`;
- examples, mock responses, scripts и структуру из `platform/contracts/postman_oms_microservices_collection.json`.

После генерации:

- `request.description` в collection обновляется из OpenAPI;
- JSON Schema добавляется в описание request;
- raw JSON body получает пример из OpenAPI;
- existing examples и scripts сохраняются.
- OpenAPI operations, которых нет в collection, добавляются автоматически;
- дубли по `method + path` удаляются с учетом того, что `{taskId}` и `{{reportTaskId}}` считаются одним path-параметром.

## Режимы генерации

### Overlay-режим

Используйте по умолчанию, когда `platform/contracts/postman_oms_microservices_collection.json` уже существует и в нем есть ручные Postman-сценарии, examples, mock responses или scripts.

```powershell
python platform/scripts/generate_postman_collection.py
```

Полная форма команды:

```powershell
python platform/scripts/generate_postman_collection.py `
  --openapi platform/contracts/openapi_oms_microservices.json `
  --overlay platform/contracts/postman_oms_microservices_collection.json `
  --output platform/contracts/postman_oms_microservices_collection.json
```

Этот режим:

- берет API-контракт из OpenAPI;
- сохраняет ручные Postman examples/scripts/mock responses из overlay collection;
- добавляет отсутствующие requests из OpenAPI;
- удаляет дубли endpoint-ов.

### From-Scratch Режим

Используйте, если нужно создать `platform/contracts/postman_oms_microservices_collection.json` с нуля только из OpenAPI.

```powershell
python platform/scripts/generate_postman_collection.py `
  --from-scratch `
  --openapi platform/contracts/openapi_oms_microservices.json `
  --output platform/contracts/postman_oms_microservices_collection.json
```

Этот режим:

- игнорирует `--overlay`;
- создает базовую Postman collection v2.1;
- добавляет service folders `OMS1`-`OMS5`;
- добавляет requests, descriptions, JSON body examples и mock-ready response examples из OpenAPI;
- добавляет переменные `oms1_base_url`-`oms5_base_url` и `access_token`.

Ограничение: from-scratch режим не может восстановить ручные Postman scripts, сложные сценарии polling и custom mock examples, если они не описаны в OpenAPI. Для сохранения таких вещей используйте overlay-режим.

## Проверка После Генерации

```powershell
python -m json.tool platform/contracts/openapi_oms_microservices.json > $null
python -m json.tool platform/contracts/postman_oms_microservices_collection.json > $null
python -m compileall -q platform/scripts
```

## Почему два файла

OpenAPI нужен для строгого API-контракта и корректного отображения `Body -> Schema` в Postman.

Postman Collection нужна для рабочих сценариев, mocks и scripts.

## Плюсы такого разделения

- OpenAPI остается чистым контрактом.
- Postman collection сохраняет удобные сценарии тестирования.
- Можно создавать mock server на основе examples.
- Можно генерировать collection повторно без потери scripts/examples.

## Минусы

- Есть два файла.
- Нужно соблюдать порядок изменений.
- После изменения OpenAPI нужно запускать генератор.

## Рекомендуемое правило

Если вопрос касается контракта API - сначала меняйте OpenAPI.

Если вопрос касается поведения Postman - меняйте collection.

После любых изменений запускайте генератор и проверку JSON.
