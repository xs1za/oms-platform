# OMS Platform

`oms-platform` содержит общую инфраструктуру, API-контракты и документацию для локальной работы с OMS1-OMS5 в Kubernetes/kind.

Репозитории сервисов:

```text
oms1-auth-service
oms2-employee-service
oms3-report-service
oms4-notification-service
oms5-operations-service
```

## Структура

```text
contracts/          OpenAPI source of truth и Postman collection
docs/               инструкции, архитектура и runbooks
k8s/                kind, Kafka, RabbitMQ, Prometheus, Ingress и production manifests
scripts/            генерация Postman collection и запуск integration tests
tests/integration/  межсервисные integration tests
```

## Integration Tests

Запускать из корня workspace через virtualenv:

```powershell
./platform/scripts/test_integration.ps1
```

Скрипт использует `.venv/Scripts/python.exe` и по умолчанию запускает `unittest discover -s platform/tests/integration`.

## OpenAPI и Postman

Source of truth: `platform/contracts/openapi_oms_microservices.json`.
Postman collection: `platform/contracts/postman_oms_microservices_collection.json`.

Сгенерировать коллекцию из корня workspace:

```powershell
python platform/scripts/generate_postman_collection.py
```

Генератор обновляет коллекцию из OpenAPI, сохраняя примеры и скрипты Postman.

## Основные документы

- `docs/K8S_FULL_SETUP.md` - локальный запуск Kubernetes/kind.
- `docs/PROBLEM_EVENT_WORKERS_PRODUCTION_RUNBOOK.md` - production-развертывание workers OMS3/OMS4.
- `docs/POSTMAN_OPENAPI_WORKFLOW.md` - OpenAPI и Postman workflow.
- `docs/SWAGGER_UPDATE_GUIDE.md` - публикация OpenAPI в Swagger UI.
- `docs/API_VERSIONING_AND_REPO_COMMITS.md` - API versioning и multi-repo workflow.
- `docs/ARCHITECTURAL DESIGN.md` - архитектурное описание платформы.
- `docs/OMS5_SHIFT_DESIGN.md` - legacy OMS5 Shift Domain Design.
- `docs/OPENLENS_GUIDE.md` - OpenLens/Freelens для kind-кластера.
- `docs/kafka_interservice_sequence.puml` - Kafka topic inventory and interservice flows for OMS1-OMS5.
