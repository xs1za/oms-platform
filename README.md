# OMS Platform

`oms-platform` содержит общую инфраструктуру и документацию для локального запуска OMS1-OMS5 в Kubernetes/kind.

Сервисный код хранится в отдельных репозиториях:

```text
oms1-auth-service
oms2-employee-service
oms3-report-service
oms4-notification-service
oms5-operations-service
```

## Структура

```text
contracts/   OpenAPI source of truth и Postman collection
docs/        инструкции по Kubernetes, Swagger, Postman, OpenLens/Freelens и versioning
k8s/         namespace, Kafka, RabbitMQ, Prometheus, Ingress и kind cluster config
scripts/     генерация Postman collection из OpenAPI
```

## Integration Tests

Запускать integration tests нужно через workspace virtualenv, чтобы не использовать системный Python без зависимостей сервисов:

```powershell
.\platform\scripts\test_integration.ps1
```

Скрипт вызывает `.venv\Scripts\python.exe` и по умолчанию запускает `unittest discover -s platform\tests\integration`.

## Запуск Существующего Кластера И Создание Нового Кластера

- `docs/K8S_FULL_SETUP.md` - управление Kubernetes/kind.

## OpenAPI И Postman

Source of truth:

```text
contracts/openapi_oms_microservices.json
```

Postman collection:

```text
contracts/postman_oms_microservices_collection.json
```

Сгенерировать Postman collection:

```powershell
python scripts/generate_postman_collection.py
```

```

## Основные Документы

- `docs/K8S_FULL_SETUP.md` - полный локальный запуск Kubernetes/kind.
- `docs/POSTMAN_OPENAPI_WORKFLOW.md` - OpenAPI и Postman workflow.
- `docs/SWAGGER_UPDATE_GUIDE.md` - публикация OpenAPI в Swagger UI.
- `docs/API_VERSIONING_AND_REPO_COMMITS.md` - API versioning и multi-repo workflow.
- `docs/OMS5_SHIFT_DESIGN.md` - legacy OMS5 Shift Domain Design.
- `docs/OPENLENS_GUIDE.md` - OpenLens/Freelens для kind-кластера.
- `docs/kafka_interservice_sequence.puml` - Kafka sequence diagram.
