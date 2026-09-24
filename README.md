# OMS Platform

`oms-platform` содержит общую инфраструктуру и документацию для локального запуска OMS1-OMS5 в Kubernetes/kind.

Этот репозиторий является главным входом в portfolio-проект `extrawork`: здесь описана архитектура, Kubernetes-инфраструктура, API-контракты, workflow запуска и правила развития multi-repo системы.

## Project Overview

`extrawork` - учебный OMS/MVP-проект, который моделирует микросервисную систему для проверки бизнес-гипотезы и дальнейшего развития до production-ready решения.

Система состоит из пяти сервисов и общей platform-зоны:

```text
OMS1  Auth Service
OMS2  Employee Service
OMS3  Report Service
OMS4  Notification Service
OMS5  Operations Service
```

Ключевые технологии:

```text
Python 3.11, FastAPI, Django, PostgreSQL/PostGIS, Kafka, Docker, Kubernetes/kind, ingress-nginx, OpenAPI, Postman, Swagger UI
```

## GitHub Repositories

- `oms-platform`: https://github.com/xs1za/oms-platform
- `oms1-auth-service`: https://github.com/xs1za/oms1-auth-service
- `oms2-employee-service`: https://github.com/xs1za/oms2-employee-service
- `oms3-report-service`: https://github.com/xs1za/oms3-report-service
- `oms4-notification-service`: https://github.com/xs1za/oms4-notification-service
- `oms5-operations-service`: https://github.com/xs1za/oms5-operations-service

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
docs/        инструкции по Kubernetes, Swagger, Postman, OpenLens и versioning
k8s/         namespace, Kafka, Ingress и kind cluster config
scripts/     генерация Postman collection из OpenAPI
```

## Быстрый Запуск Существующего Кластера

Если kind-кластер `oms-cluster` уже создан, запустить Docker Desktop и поднять kind node:

```powershell
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
docker version

if (-not (docker ps --filter "name=oms-cluster-control-plane" --format "{{.Names}}")) { docker start oms-cluster-control-plane }
kubectl config use-context kind-oms-cluster
kubectl get nodes
```

Поднять workloads:

```powershell
kubectl -n oms scale deployment/kafka deployment/oms2-postgres --replicas=1
kubectl -n oms scale deployment/oms1 deployment/oms2 deployment/oms3 deployment/oms4 deployment/oms5 --replicas=1
kubectl -n oms get pods -w
```

Создание кластера с нуля описано в `docs/K8S_FULL_SETUP.md`.

Ожидаемый вывод команды запуска kind node зависит от состояния контейнера:

```text
# Если Docker Desktop уже запустил oms-cluster-control-plane автоматически:
# команда ничего не выводит

# Если oms-cluster-control-plane был остановлен:
oms-cluster-control-plane
```

Если перед этим кластер был корректно остановлен, `kubectl -n oms get pods` сначала может показать `No resources found in oms namespace.` Это нормально: deployments были scaled to 0. Команды `kubectl -n oms scale ... --replicas=1` поднимут pods обратно.

Если контейнера `oms-cluster-control-plane` нет, кластер нужно создать заново: см. `docs/K8S_FULL_SETUP.md`, пункты 4-11.

Если после запуска нужно пересобрать images или применить изменения кода, см. `docs/K8S_FULL_SETUP.md`, пункт 16.

## Корректное Завершение Работы

Перед `Quit` Docker Desktop или перезагрузкой Windows сначала остановите kind-кластер, иначе Docker Desktop может зависнуть при остановке WSL/backend, kind node, mounts и контейнеров. Подробный порядок: `docs/K8S_FULL_SETUP.md`, пункт 16.1.

Короткий вариант с сохранением kind-кластера:

```powershell
kubectl config use-context kind-oms-cluster
kubectl -n oms scale deployment/oms1 deployment/oms2 deployment/oms3 deployment/oms4 deployment/oms5 --replicas=0
kubectl -n oms scale deployment/kafka deployment/oms2-postgres --replicas=0
docker stop oms-cluster-control-plane
```

Полное удаление кластера перед перезагрузкой, если кластер не нужно сохранять:

```powershell
kind delete cluster --name oms-cluster
```

Данные OMS2 Postgres сохраняются в `../.runtime/oms2-postgres-data`, если эту папку не удалять. Восстановление после перезагрузки описано в `docs/K8S_FULL_SETUP.md`, пункт 17.

## Проверка Ingress

В `C:\Windows\System32\drivers\etc\hosts` должна быть запись:

```text
127.0.0.1 oms.local
```

Проверить сервисы:

```powershell
curl http://oms.local/oms1/health
curl http://oms.local/oms2/health/
curl http://oms.local/oms3/health
curl http://oms.local/oms4/health
curl http://oms.local/oms5/health
```

Swagger UI FastAPI-сервисов:

```text
http://oms.local/oms1/docs
http://oms.local/oms3/docs
http://oms.local/oms4/docs
http://oms.local/oms5/docs
```

OMS2 Django admin:

```text
http://oms.local/oms2/admin/
```

Браузер открывает URL методом `GET`. Endpoints создания ресурсов нужно вызывать из Swagger UI, Postman или `curl`, потому что они используют `POST`.

GET endpoints, которые можно открыть в браузере:

```text
http://oms.local/oms1/health
http://oms.local/oms2/health/
http://oms.local/oms2/employees/
http://oms.local/oms3/health
http://oms.local/oms4/health
http://oms.local/oms5/health
http://oms.local/oms5/operations/summary
```

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

## Kafka Event Model

Kafka используется как durable publish/subscribe event log для domain/integration events, а не как классическая очередь задач.

Примеры Kafka events:

- `employee.created`
- `report.requested`
- `report.completed`
- `notification.email_status`
- `operations.*_created`

Для командных задач с retry, delayed retry, DLQ и обработкой одним worker лучше использовать RabbitMQ/Celery или отдельный worker mechanism. Подробное обоснование: `docs/проектирование.md`.

## Persistent Data

OMS2 Postgres в Kubernetes использует PVC:

```text
oms2-postgres-data
```

Физически данные лежат на host в папке:

```text
../.runtime/oms2-postgres-data
```

Эта папка монтируется в kind node через `k8s/kind-cluster.yaml`, поэтому данные переживают пересоздание pod и пересоздание kind-кластера, если папку `../.runtime/oms2-postgres-data` не удалять. Runtime data не хранится в Git.

## Основные Документы

- `docs/K8S_FULL_SETUP.md` - полный локальный запуск Kubernetes/kind.
- `docs/POSTMAN_OPENAPI_WORKFLOW.md` - OpenAPI и Postman workflow.
- `docs/SWAGGER_UPDATE_GUIDE.md` - публикация OpenAPI в Swagger UI.
- `docs/API_VERSIONING_AND_REPO_COMMITS.md` - API versioning и multi-repo workflow.
- `docs/OPENLENS_GUIDE.md` - OpenLens/Freelens для kind-кластера.
- `docs/kafka_interservice_sequence.puml` - Kafka sequence diagram.
