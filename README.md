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
docs/        инструкции по Kubernetes, Swagger, Postman, OpenLens и versioning
k8s/         namespace, Kafka, Ingress и kind cluster config
scripts/     генерация Postman collection из OpenAPI
```

## Что Коммитить

В первый коммит `oms-platform` должны входить только файлы из этого каталога:

```text
.gitignore
README.md
contracts/
docs/
k8s/
scripts/
```

Не коммитить:

```text
.idea/
__pycache__/
*.pyc
.env
*.env
.runtime/
```

Сервисные каталоги `OMS1`-`OMS5` не относятся к этому репозиторию.

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

## Git Init Через PyCharm

1. Откройте в PyCharm каталог:

```text
D:\ProjectsDocker\extrawork\platform
```

2. Убедитесь, что в окне Project видны только папки этого репозитория:

```text
contracts
docs
k8s
scripts
```

3. Откройте меню:

```text
VCS -> Enable Version Control Integration...
```

4. Выберите:

```text
Git
```

5. После этого PyCharm создаст `.git` внутри `platform/`.

6. Откройте вкладку Commit и проверьте список файлов. В initial commit не должно быть `apps`, `root`, `manage.py`, `OMS1`-`OMS5`, `.idea`, `__pycache__`.

7. Отметьте файлы для коммита и используйте сообщение:

```text
Initial platform infrastructure
```

8. Создайте remote repository на GitHub, например:

```text
oms-platform
```

9. Добавьте remote через PyCharm:

```text
Git -> Manage Remotes... -> +
```

URL:

```text
https://github.com/<your-user>/oms-platform.git
```

10. Выполните push:

```text
Git -> Push...
```

## Основные Документы

- `docs/K8S_FULL_SETUP.md` - полный локальный запуск Kubernetes/kind.
- `docs/POSTMAN_OPENAPI_WORKFLOW.md` - OpenAPI и Postman workflow.
- `docs/SWAGGER_UPDATE_GUIDE.md` - публикация OpenAPI в Swagger UI.
- `docs/API_VERSIONING_AND_REPO_COMMITS.md` - API versioning и multi-repo workflow.
- `docs/OMS5_SHIFT_DESIGN.md` - проектирование смен, FSM, offers, RabbitMQ workers и UI boundaries.
- `docs/OPENLENS_GUIDE.md` - OpenLens/Freelens для kind-кластера.
- `docs/kafka_interservice_sequence.puml` - Kafka sequence diagram.
