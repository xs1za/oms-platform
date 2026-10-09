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
kubectl -n oms scale deployment/kafka deployment/rabbitmq deployment/akhq deployment/prometheus deployment/kube-state-metrics deployment/oms2-postgres --replicas=1
kubectl -n oms scale deployment/oms1 deployment/oms2 deployment/oms3 deployment/oms4 deployment/oms5 --replicas=1
kubectl -n oms get pods -w
```

Создание кластера с нуля описано в `docs/K8S_FULL_SETUP.md`.

## Проверка Ingress

В `C:\Windows\System32\drivers\etc\hosts` должны быть записи:

```text
127.0.0.1 oms.local
127.0.0.1 prometheus.oms.local
127.0.0.1 kafka.oms.local
127.0.0.1 rabbitmq.oms.local
```

Проверить сервисы:

```powershell
curl http://oms.local/oms1/health
curl http://oms.local/oms2/health/
curl http://oms.local/oms3/health
curl http://oms.local/oms4/health
curl http://oms.local/oms5/health
curl http://prometheus.oms.local/-/ready
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

Инфраструктурные UI:

```text
http://prometheus.oms.local
http://kafka.oms.local
http://rabbitmq.oms.local
```

## Проверка Prometheus Для Freelens

Prometheus разворачивается из Kubernetes manifest `k8s/prometheus.yaml`.

```powershell
kubectl apply -f k8s/prometheus.yaml
kubectl -n oms rollout status deployment/prometheus
kubectl -n oms rollout status deployment/kube-state-metrics
```

Через Ingress Prometheus доступен для проверки по адресу:

```text
http://prometheus.oms.local/targets
```

В Freelens/OpenLens источник метрик указывать как `Helm`, service address `oms/prometheus-server:80`.

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
