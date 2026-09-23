# Полная инструкция разворачивания OMS в Kubernetes с нуля

Инструкция рассчитана на локальную разработку в Windows 11 + Docker Desktop + kind + kubectl.

## 1. Что разворачивается

В Kubernetes разворачиваются:

- `OMS1` - сервис авторизации JWT.
- `OMS2` - сервис сотрудников Employee на Django.
- `OMS2 Postgres` - локальная PostGIS БД для `OMS2`.
- `OMS3` - сервис отчетов.
- `OMS4` - сервис уведомлений email.
- `OMS5` - сервис операционных сущностей: клиент, смена, задание, табель.
- `Kafka` - локальный single-node Kafka для межсервисных событий.
- `ingress-nginx` - единая точка входа вместо `kubectl port-forward`.

## 2. Предварительные требования

Должны быть установлены и доступны в PowerShell:

```powershell
docker version
kubectl version --client
kind version
```

Docker Desktop должен быть запущен. Запустить его из PowerShell можно так:

```powershell
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
docker version
```

Если `docker version` еще не отвечает, подождите завершения запуска Docker Desktop и повторите команду.

Docker Desktop Kubernetes можно отключить, чтобы не путаться с context. Для работы этой инструкции используется отдельный kind-кластер `oms-cluster`.

## 3. Перейти в каталог проекта

```powershell
cd D:\ProjectsDocker\extrawork
```

Если Docker Desktop еще не запущен, выполните команды из пункта 2.

Проверь структуру:

```powershell
dir OMS1
dir OMS2
dir OMS3
dir OMS4
dir OMS5
dir platform\k8s
```

## 4. Создать kind-кластер

Кластер создается из файла `platform/k8s/kind-cluster.yaml`. В нем уже настроены:

- имя кластера `oms-cluster`;
- проброс `80` и `443` с host в cluster node;
- label `ingress-ready=true`, который нужен `ingress-nginx` для kind.
- host mount для постоянных данных OMS2 Postgres: `.runtime/oms2-postgres-data` -> `/mnt/oms-data/oms2-postgres-data` внутри kind node.

Перед созданием кластера создать host-папку для постоянных данных OMS2 Postgres:

```powershell
New-Item -ItemType Directory -Path ".runtime\oms2-postgres-data" -Force
```

Если старый кластер уже есть и его нужно пересоздать:

```powershell
kind delete cluster --name oms-cluster
```

Создать новый кластер:

```powershell
kind create cluster --config platform/k8s/kind-cluster.yaml
kubectl config use-context kind-oms-cluster
```

Проверить:

```powershell
kind get clusters
kubectl config current-context
kubectl get nodes --show-labels
```

Ожидаемо:

```text
oms-cluster
kind-oms-cluster
```

Node должна иметь label:

```text
ingress-ready=true
```

Если label отсутствует, добавить вручную:

```powershell
kubectl label node oms-cluster-control-plane ingress-ready=true
```

Проверить, что host mount для данных OMS2 Postgres виден внутри kind node:

```powershell
docker exec oms-cluster-control-plane ls -la /mnt/oms-data/oms2-postgres-data
```

Важно: изменение `extraMounts` в `platform/k8s/kind-cluster.yaml` не применяется к уже созданному kind-кластеру. Чтобы новый mount появился, нужно пересоздать kind-кластер командой `kind delete cluster --name oms-cluster`, затем `kind create cluster --config platform/k8s/kind-cluster.yaml`.

## 5. Собрать Docker-образы микросервисов

```powershell
docker build -t oms1:latest .\OMS1
docker build -t oms2:latest .\OMS2
docker build -t oms3:latest .\OMS3
docker build -t oms4:latest .\OMS4
docker build -t oms5:latest .\OMS5
```

Проверить:

```powershell
docker images oms1
docker images oms2
docker images oms3
docker images oms4
docker images oms5
```

## 6. Загрузить образы микросервисов в kind

kind-кластер не видит локальные Docker images автоматически. Их нужно загрузить в node:

```powershell
kind load docker-image oms1:latest --name oms-cluster
kind load docker-image oms2:latest --name oms-cluster
kind load docker-image oms3:latest --name oms-cluster
kind load docker-image oms4:latest --name oms-cluster
kind load docker-image oms5:latest --name oms-cluster
```

Проверить внутри kind node:

```powershell
docker exec oms-cluster-control-plane crictl images | findstr oms
```

Ожидаемо должны быть:

```text
docker.io/library/oms1
docker.io/library/oms2
docker.io/library/oms3
docker.io/library/oms4
docker.io/library/oms5
```

## 7. Подготовить Kafka image

Kafka использует официальный образ:

```text
apache/kafka:3.7.0
```

Обычно Kubernetes сам скачает его. Если есть проблемы с pull или сетью, загрузить образ в kind вручную:

```powershell
docker pull apache/kafka:3.7.0
docker exec oms-cluster-control-plane crictl pull docker.io/apache/kafka:3.7.0
docker exec oms-cluster-control-plane crictl images | findstr kafka
```

Если `kind load docker-image apache/kafka:3.7.0` падает с ошибкой digest, используйте именно `crictl pull` внутри node, как показано выше.

## 8. Установить ingress-nginx

```powershell
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.12.1/deploy/static/provider/kind/deploy.yaml
kubectl wait --namespace ingress-nginx --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=180s
```

Проверить:

```powershell
kubectl -n ingress-nginx get pods
```

Ожидаемо:

```text
ingress-nginx-controller-...   1/1   Running
```

Если pod `ingress-nginx-controller` остается `Pending`, проверить label node:

```powershell
kubectl get nodes --show-labels
```

Исправить:

```powershell
kubectl label node oms-cluster-control-plane ingress-ready=true
```

## 9. Создать namespace и развернуть инфраструктуру

Создать namespace:

```powershell
kubectl apply -f platform/k8s/namespace.yaml
```

Развернуть Kafka:

```powershell
kubectl apply -f platform/k8s/kafka-dev.yaml
```

Развернуть микросервисы:

```powershell
kubectl apply -f OMS1/k8s/
kubectl apply -f OMS2/k8s/
kubectl apply -f OMS3/k8s/
kubectl apply -f OMS4/k8s/
kubectl apply -f OMS5/k8s/
```

Проверить pods:

```powershell
kubectl -n oms get pods -w
```

Ожидаемое итоговое состояние:

```text
kafka           1/1   Running
oms1            1/1   Running
oms2            1/1   Running
oms2-postgres   1/1   Running
oms3            1/1   Running
oms4            1/1   Running
oms5            1/1   Running
```

Проверить services:

```powershell
kubectl -n oms get svc
```

## 9.1. Создать Django Superuser Для OMS2 Admin

После первого разворачивания новой БД нужно создать пользователя для Django admin. Django-проект уже находится в `OMS2`, поэтому команду `django-admin startproject ...` выполнять не нужно.

Создать или обновить superuser `admin/admin` в работающем OMS2 pod:

```powershell
kubectl -n oms exec deployment/oms2 -- python manage.py shell -c "from django.contrib.auth import get_user_model; User=get_user_model(); u, created = User.objects.get_or_create(username='admin', defaults={'email':'admin@example.local','is_staff':True,'is_superuser':True}); u.is_staff=True; u.is_superuser=True; u.set_password('admin'); u.save(); print('created' if created else 'updated')"
```

Ожидаемый вывод:

```text
created
```

или, если пользователь уже существовал и пароль был обновлен:

```text
updated
```

После применения Ingress Django admin будет доступен по адресу:

```text
http://oms.local/oms2/admin/
```

## 10. Настроить локальный DNS через hosts

Откройте файл от имени администратора:

```text
C:\Windows\System32\drivers\etc\hosts
```

Добавьте строку:

```text
127.0.0.1 oms.local
```

Проверить:

```powershell
ping oms.local
```

Должно резолвиться в `127.0.0.1`.

## 11. Применить Ingress

```powershell
kubectl apply -f platform/k8s/ingress.yaml
kubectl -n oms get ingress
```

Ожидаемо:

```text
oms-ingress   nginx   oms.local
```

## 12. Проверить доступ без port-forward

Теперь отдельные терминалы с `kubectl port-forward` не нужны.

Проверить health endpoints:

```powershell
curl http://oms.local/oms1/health
curl http://oms.local/oms2/health/
curl http://oms.local/oms3/health
curl http://oms.local/oms3/health/
curl http://oms.local/oms4/health
curl http://oms.local/oms4/health/
curl http://oms.local/oms5/health
curl http://oms.local/oms5/health/
```

Проверить liveness endpoints:

```powershell
curl http://oms.local/oms1/health/live
curl http://oms.local/oms2/health/live/
curl http://oms.local/oms3/health/live
curl http://oms.local/oms3/health/live/
curl http://oms.local/oms4/health/live
curl http://oms.local/oms4/health/live/
curl http://oms.local/oms5/health/live
curl http://oms.local/oms5/health/live/
```

Проверить readiness endpoints с проверкой зависимостей:

```powershell
curl http://oms.local/oms1/health/ready
curl http://oms.local/oms2/health/ready/
curl http://oms.local/oms3/health/ready
curl http://oms.local/oms3/health/ready/
curl http://oms.local/oms4/health/ready
curl http://oms.local/oms4/health/ready/
curl http://oms.local/oms5/health/ready
curl http://oms.local/oms5/health/ready/
```

Ожидаемые ответы:

```json
{"status":"ok","service":"OMS1"}
```

```json
{"status":"ok","service":"OMS2"}
```

```json
{"status":"ok","service":"OMS3"}
```

```json
{"status":"ok","service":"OMS4"}
```

```json
{"status":"ok","service":"OMS5"}
```

## 13. Основные API через Ingress

### OMS1 Auth

```powershell
curl http://oms.local/oms1/health
```

Получить пользовательский JWT:

```powershell
curl -X POST http://oms.local/oms1/auth/token -H "Content-Type: application/json" -d '{"username":"admin","password":"admin"}'
```

### OMS2 Employee

```powershell
curl http://oms.local/oms2/api/employees/
```

Создать сотрудника:

```powershell
curl -X POST http://oms.local/oms2/api/employees/ -H "Content-Type: application/json" -d '{"surname":"Иванов","firstname":"Иван","patronymic":"Иванович","personnel_number":"EMP-0001","gender":"M"}'
```

### OMS3 Reports

```powershell
curl -X POST http://oms.local/oms3/reports -H "Content-Type: application/json" -d '{"report_type":"employee_summary","period_from":"2026-01-01","period_to":"2026-01-31","filters":{}}'
```

### OMS4 Notifications

```powershell
curl -X POST http://oms.local/oms4/notifications/email -H "Content-Type: application/json" -d '{"to":"user@example.com","subject":"Test","body":"Test message"}'
```

### OMS5 Operations

```powershell
curl -X POST http://oms.local/oms5/clients -H "Content-Type: application/json" -d '{"name":"ООО Клиент","external_id":"CLIENT-0001"}'
```

## 14. Postman

В проекте есть коллекция:

```text
platform/contracts/postman_oms_microservices_collection.json
```

Для работы через Ingress в Postman можно заменить collection variables:

```text
oms1_base_url = http://oms.local/oms1
oms2_base_url = http://oms.local/oms2
oms3_base_url = http://oms.local/oms3
oms4_base_url = http://oms.local/oms4
oms5_base_url = http://oms.local/oms5
```

## 15. Постоянные Данные OMS2 Postgres

OMS2 Postgres использует статический `PersistentVolume`, который хранит данные не внутри pod и не внутри временного local-path volume kind, а в host-папке проекта:

```text
D:\ProjectsDocker\extrawork\.runtime\oms2-postgres-data
```

Эта папка монтируется в kind node через `platform/k8s/kind-cluster.yaml`:

```text
host:      D:\ProjectsDocker\extrawork\.runtime\oms2-postgres-data
kind node: /mnt/oms-data/oms2-postgres-data
pod:       /var/lib/postgresql/data
```

Файлы данных не коммитятся в Git. Папка `.runtime/` добавлена в `.gitignore`.

### Проверить PVC/PV

```powershell
kubectl -n oms get pvc oms2-postgres-data
kubectl get pv oms2-postgres-data-pv
kubectl get pv oms2-postgres-data-pv -o yaml
```

Ожидаемо:

```text
oms2-postgres-data   Bound
oms2-postgres-data-pv   Bound
```

### Проверить Файлы На Host

```powershell
Get-ChildItem -LiteralPath ".runtime\oms2-postgres-data"
```

### Проверить Mount Внутри Kind Node

```powershell
docker exec oms-cluster-control-plane ls -la /mnt/oms-data/oms2-postgres-data
```

### Проверить Доступность БД

```powershell
kubectl -n oms exec deployment/oms2-postgres -- psql -U oms2 -d oms2 -c "select 1;"
curl http://oms.local/oms2/health/ready/
```

### Пересоздание Kind-Кластера Без Потери Данных OMS2

Данные сохранятся, если не удалять папку:

```text
.runtime\oms2-postgres-data
```

Порядок:

```powershell
kind delete cluster --name oms-cluster
New-Item -ItemType Directory -Path ".runtime\oms2-postgres-data" -Force
kind create cluster --config platform/k8s/kind-cluster.yaml
kubectl config use-context kind-oms-cluster
```

Затем применить manifests:

```powershell
kubectl apply -f platform/k8s/namespace.yaml
kubectl apply -f platform/k8s/kafka-dev.yaml
kubectl apply -f OMS2/k8s/postgres.yaml
kubectl apply -f OMS2/k8s/
```

Postgres pod подключит существующие файлы из `.runtime\oms2-postgres-data` автоматически.

### Ручной Backup Текущего Kind Local-Path Volume

Если данные еще находятся в старом kind local-path volume, остановить OMS2 и Postgres:

```powershell
kubectl -n oms scale deployment/oms2 --replicas=0
kubectl -n oms scale deployment/oms2-postgres --replicas=0
```

Скопировать данные из kind node на host:

```powershell
docker cp "oms-cluster-control-plane:/var/local-path-provisioner/<pv-folder>" ".runtime\oms2-postgres-data"
```

Вернуть сервисы:

```powershell
kubectl -n oms scale deployment/oms2-postgres --replicas=1
kubectl -n oms scale deployment/oms2 --replicas=1
```

## 16. Обновление одного сервиса после изменения кода

Пример для `OMS1`:

```powershell
docker build -t oms1:latest .\OMS1
kind load docker-image oms1:latest --name oms-cluster
kubectl -n oms rollout restart deployment oms1
kubectl -n oms rollout status deployment oms1
```

Аналогично для других сервисов:

```powershell
docker build -t oms2:latest .\OMS2
kind load docker-image oms2:latest --name oms-cluster
kubectl -n oms rollout restart deployment oms2
```

## 16.1. Правильное Завершение Работы Перед Перезагрузкой ПК

Если нужно перезагрузить Windows, выйти из Docker Desktop или выключить host PC, не закрывайте Docker Desktop сразу при работающем kind-кластере. Сначала остановите workloads и kind node container. Это снижает риск зависания Docker Desktop на `Quit` и дает Postgres время корректно завершить работу.

### Вариант A. Остановить Работу И Сохранить Kind-Кластер

Используйте этот вариант для обычной перезагрузки ПК. Kubernetes objects сохраняются внутри kind node container, а данные OMS2 Postgres остаются на host в `.runtime\oms2-postgres-data`.

Перейти в каталог проекта:

```powershell
cd D:\ProjectsDocker\extrawork
kubectl config use-context kind-oms-cluster
```

Проверить текущее состояние:

```powershell
kubectl -n oms get pods
kubectl -n oms get pvc
```

Остановить прикладные сервисы, чтобы они перестали обращаться к Kafka и Postgres:

```powershell
kubectl -n oms scale deployment/oms1 --replicas=0
kubectl -n oms scale deployment/oms2 --replicas=0
kubectl -n oms scale deployment/oms3 --replicas=0
kubectl -n oms scale deployment/oms4 --replicas=0
kubectl -n oms scale deployment/oms5 --replicas=0
```

Остановить инфраструктурные сервисы после приложений:

```powershell
kubectl -n oms scale deployment/kafka --replicas=0
kubectl -n oms scale deployment/oms2-postgres --replicas=0
```

Дождаться удаления pod-ов в namespace `oms`:

```powershell
kubectl -n oms get pods -w
```

Когда pod-ов в `oms` больше нет или все нужные pod-ы уже terminating/removed, остановить kind node container:

```powershell
docker stop oms-cluster-control-plane
```

Проверить, что container остановлен:

```powershell
docker ps -a --filter "name=oms-cluster-control-plane"
```

После этого можно делать `Quit` в Docker Desktop или перезагружать Windows.

### Вариант B. Полностью Удалить Kind-Кластер

Используйте этот вариант, если кластер нужно пересоздать с нуля или Docker Desktop нестабилен. Kubernetes objects будут удалены, но данные OMS2 Postgres сохранятся, если не удалять папку `.runtime\oms2-postgres-data`.

```powershell
cd D:\ProjectsDocker\extrawork
kubectl config use-context kind-oms-cluster
kubectl -n oms scale deployment/oms2 --replicas=0
kubectl -n oms scale deployment/oms2-postgres --replicas=0
kind delete cluster --name oms-cluster
```

После удаления кластера можно выходить из Docker Desktop или перезагружать ПК. Для следующего запуска создайте кластер заново по шагам 4-11 или быстрому сценарию из раздела 24.

### Если Docker Desktop Уже Завис На Quit

Если Docker Desktop уже завис и Docker CLI возвращает `500 Internal Server Error` для `dockerDesktopLinuxEngine`, значит backend находится в полузавершенном состоянии. Попробуйте в отдельном PowerShell:

```powershell
wsl --shutdown
```

Если окно Docker Desktop все еще не закрывается, завершите процессы через Task Manager:

```text
Docker Desktop
com.docker.backend
```

После принудительного завершения запустите Docker Desktop заново и проверьте:

```powershell
docker version
wsl -l -v
kind get clusters
```

Важно: не удаляйте `.runtime\oms2-postgres-data`, если нужно сохранить данные OMS2 Postgres.

## 17. Запуск После Перезагрузки Компьютера Или Docker Desktop

После перезагрузки Windows или Docker Desktop kind-кластер может быть остановлен вместе с Docker container `oms-cluster-control-plane`.

### 17.1. Проверить Docker И Kind

```powershell
docker ps
kind get clusters
kubectl config current-context
kubectl get nodes
```

Ожидаемо:

```text
oms-cluster
kind-oms-cluster
```

Если context не выбран:

```powershell
kubectl config use-context kind-oms-cluster
```

Если `kind get clusters` не показывает `oms-cluster`, кластер удален или Docker потерял контейнер kind node. Нужно создать кластер заново по шагам 4-11 или выполнить быстрый сценарий из раздела 24.

### 17.2. Поднять Существующий Kind Node Container

Проверить состояние kind node container:

```powershell
docker ps -a --filter "name=oms-cluster-control-plane"
```

Если контейнер существует и уже запущен, `STATUS` будет вида:

```text
Up ...
```

Если контейнер существует, но остановлен, `STATUS` будет вида:

```text
Exited ...
```

Запустить контейнер, только если он еще не запущен:

```powershell
if (-not (docker ps --filter "name=oms-cluster-control-plane" --format "{{.Names}}")) { docker start oms-cluster-control-plane }
```

Ожидаемый вывод:

```text
# Сценарий 1: контейнер уже запущен, например Docker Desktop поднял его автоматически.
# Команда ничего не выводит.

# Сценарий 2: контейнер был остановлен и сейчас запущен командой docker start.
oms-cluster-control-plane
```

После этого выбрать context и проверить node:

```powershell
kubectl config use-context kind-oms-cluster
kubectl get nodes
```

Ожидаемо:

```text
NAME                        STATUS   ROLES           AGE   VERSION
oms-cluster-control-plane   Ready    control-plane   ...   ...
```

### 17.3. Проверить И Дождаться Системных Pod

```powershell
kubectl get pods -A
kubectl -n ingress-nginx wait --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=180s
kubectl -n oms get pods
```

### 17.4. Запустить Все Workloads Повторно

Если namespace и deployments существуют, поднять replicas обратно до `1`. Это обязательно после корректного завершения из пункта 16.1, потому что там deployments были остановлены через `scale --replicas=0`.

```powershell
kubectl -n oms scale deployment/kafka deployment/oms2-postgres --replicas=1
kubectl -n oms scale deployment/oms1 deployment/oms2 deployment/oms3 deployment/oms4 deployment/oms5 --replicas=1
```

Если перед запуском `kubectl -n oms get pods` показывает:

```text
No resources found in oms namespace.
```

это нормально для сценария после корректной остановки: deployments существуют, но их replicas равны `0`.

Дождаться готовности:

```powershell
kubectl -n oms get pods -w
```

Ожидаемо в итоге:

```text
kafka-...           1/1   Running
oms1-...            1/1   Running
oms2-...            1/1   Running
oms2-postgres-...   1/1   Running
oms3-...            1/1   Running
oms4-...            1/1   Running
oms5-...            1/1   Running
```

Если deployments отсутствуют, применить манифесты заново:

```powershell
kubectl apply -f platform/k8s/namespace.yaml
kubectl apply -f platform/k8s/kafka-dev.yaml
kubectl apply -f OMS1/k8s/
kubectl apply -f OMS2/k8s/
kubectl apply -f OMS3/k8s/
kubectl apply -f OMS4/k8s/
kubectl apply -f OMS5/k8s/
kubectl apply -f platform/k8s/ingress.yaml
```

### 17.5. Проверить Ingress И Hosts

```powershell
ping oms.local
kubectl -n ingress-nginx get pods
kubectl -n oms get ingress
curl http://oms.local/oms1/health
curl http://oms.local/oms2/health/
curl http://oms.local/oms3/health/ready
curl http://oms.local/oms4/health/ready
curl http://oms.local/oms5/health/ready
```

## 18. Управление Kubernetes, Kind, Kafka, Ingress И Pod

### 18.1. Kubernetes Context

Посмотреть context:

```powershell
kubectl config get-contexts
kubectl config current-context
```

Выбрать kind context:

```powershell
kubectl config use-context kind-oms-cluster
```

### 18.2. Kind Cluster

Посмотреть clusters:

```powershell
kind get clusters
```

Создать cluster:

```powershell
kind create cluster --config platform/k8s/kind-cluster.yaml
```

Остановить kind node container без удаления кластера:

```powershell
docker stop oms-cluster-control-plane
```

Запустить kind node container после остановки:

```powershell
docker start oms-cluster-control-plane
kubectl config use-context kind-oms-cluster
kubectl get nodes
```

Удалить cluster полностью:

```powershell
kind delete cluster --name oms-cluster
```

### 18.3. Namespace OMS

Создать или обновить namespace:

```powershell
kubectl apply -f platform/k8s/namespace.yaml
```

Посмотреть ресурсы namespace:

```powershell
kubectl -n oms get all
kubectl -n oms get deployments
```

Остановить все deployments в namespace через scale to zero:

```powershell
kubectl -n oms scale deployment --all --replicas=0
```

Запустить все deployments обратно:

```powershell
kubectl -n oms scale deployment/kafka --replicas=1
kubectl -n oms scale deployment/oms2-postgres --replicas=1
kubectl -n oms scale deployment/oms1 --replicas=1
kubectl -n oms scale deployment/oms2 --replicas=1
kubectl -n oms scale deployment/oms3 --replicas=1
kubectl -n oms scale deployment/oms4 --replicas=1
kubectl -n oms scale deployment/oms5 --replicas=1
```

Перезапустить все deployments:

```powershell
kubectl -n oms rollout restart deployment/kafka deployment/oms2-postgres deployment/oms1 deployment/oms2 deployment/oms3 deployment/oms4 deployment/oms5
```

### 18.4. Kafka

Применить Kafka manifest:

```powershell
kubectl apply -f platform/k8s/kafka-dev.yaml
```

Перезапустить Kafka:

```powershell
kubectl -n oms rollout restart deployment/kafka
kubectl -n oms rollout status deployment/kafka
```

Остановить Kafka:

```powershell
kubectl -n oms scale deployment/kafka --replicas=0
```

Запустить Kafka:

```powershell
kubectl -n oms scale deployment/kafka --replicas=1
kubectl -n oms rollout status deployment/kafka
```

Проверить Kafka pod и service:

```powershell
kubectl -n oms get pods -l app=kafka
kubectl -n oms get svc kafka
kubectl -n oms logs deployment/kafka --tail=100
```

### 18.5. Ingress NGINX

Установить или обновить ingress-nginx:

```powershell
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.12.1/deploy/static/provider/kind/deploy.yaml
kubectl -n ingress-nginx wait --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=180s
```

Применить routing OMS:

```powershell
kubectl apply -f platform/k8s/ingress.yaml
```

Перезапустить ingress controller:

```powershell
kubectl -n ingress-nginx rollout restart deployment/ingress-nginx-controller
kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller
```

Остановить ingress controller:

```powershell
kubectl -n ingress-nginx scale deployment/ingress-nginx-controller --replicas=0
```

Запустить ingress controller:

```powershell
kubectl -n ingress-nginx scale deployment/ingress-nginx-controller --replicas=1
kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller
```

Проверить ingress:

```powershell
kubectl -n ingress-nginx get pods
kubectl -n oms get ingress
kubectl -n oms describe ingress oms-ingress
curl http://oms.local/oms1/health
```

### 18.6. Отдельные OMS-Сервисы

Перезапустить один сервис:

```powershell
kubectl -n oms rollout restart deployment/oms1
kubectl -n oms rollout status deployment/oms1
```

Остановить один сервис:

```powershell
kubectl -n oms scale deployment/oms1 --replicas=0
```

Запустить один сервис:

```powershell
kubectl -n oms scale deployment/oms1 --replicas=1
kubectl -n oms rollout status deployment/oms1
```

Удалить текущий pod сервиса, чтобы Kubernetes создал новый:

```powershell
kubectl -n oms delete pod -l app=oms1
```

Примеры для остальных сервисов:

```powershell
kubectl -n oms rollout restart deployment/oms2
kubectl -n oms rollout restart deployment/oms3
kubectl -n oms rollout restart deployment/oms4
kubectl -n oms rollout restart deployment/oms5
```

## 19. Проверка Работоспособности Сети Внутри Kubernetes И Kind

### 19.1. Проверить Services, Endpoints И DNS

```powershell
kubectl -n oms get svc
kubectl -n oms get endpoints
kubectl -n oms get pods -o wide
```

Проверить DNS внутри кластера через временный debug pod:

```powershell
kubectl -n oms run netshoot --rm -it --image=nicolaka/netshoot --restart=Never -- nslookup kafka.oms.svc.cluster.local
kubectl -n oms run netshoot --rm -it --image=nicolaka/netshoot --restart=Never -- nslookup oms1.oms.svc.cluster.local
kubectl -n oms run netshoot --rm -it --image=nicolaka/netshoot --restart=Never -- nslookup oms2.oms.svc.cluster.local
```

Если `nicolaka/netshoot` не скачивается, используйте busybox:

```powershell
kubectl -n oms run busybox-dns --rm -it --image=busybox:1.36 --restart=Never -- nslookup kafka.oms.svc.cluster.local
```

### 19.2. Проверить TCP Connectivity Внутри Кластера

Kafka:

```powershell
kubectl -n oms run netshoot --rm -it --image=nicolaka/netshoot --restart=Never -- nc -vz kafka.oms.svc.cluster.local 9092
```

OMS services:

```powershell
kubectl -n oms run netshoot --rm -it --image=nicolaka/netshoot --restart=Never -- curl -i http://oms1/health
kubectl -n oms run netshoot --rm -it --image=nicolaka/netshoot --restart=Never -- curl -i http://oms2/health/
kubectl -n oms run netshoot --rm -it --image=nicolaka/netshoot --restart=Never -- curl -i http://oms3/health/ready
kubectl -n oms run netshoot --rm -it --image=nicolaka/netshoot --restart=Never -- curl -i http://oms4/health/ready
kubectl -n oms run netshoot --rm -it --image=nicolaka/netshoot --restart=Never -- curl -i http://oms5/health/ready
```

Postgres OMS2:

```powershell
kubectl -n oms run netshoot --rm -it --image=nicolaka/netshoot --restart=Never -- nc -vz oms2-postgres 5432
```

### 19.3. Проверить Сеть Kind Node

Войти в kind node:

```powershell
docker exec -it oms-cluster-control-plane bash
```

Проверить container runtime images:

```powershell
docker exec oms-cluster-control-plane crictl images
docker exec oms-cluster-control-plane crictl ps
```

Проверить доступность Ingress ports на host:

```powershell
curl http://localhost
curl http://oms.local/oms1/health
```

Проверить сетевые правила и адреса внутри kind node:

```powershell
docker exec oms-cluster-control-plane ip addr
docker exec oms-cluster-control-plane ip route
```

### 19.4. Проверить CoreDNS

```powershell
kubectl -n kube-system get pods -l k8s-app=kube-dns
kubectl -n kube-system logs deployment/coredns --tail=100
kubectl -n kube-system rollout restart deployment/coredns
kubectl -n kube-system rollout status deployment/coredns
```

## 20. Подключение К Bash/Шеллу Отдельных Pod

### 20.1. Через Deployment

FastAPI services обычно имеют `/bin/sh`, а не обязательно `bash`:

```powershell
kubectl -n oms exec -it deployment/oms1 -- /bin/sh
kubectl -n oms exec -it deployment/oms3 -- /bin/sh
kubectl -n oms exec -it deployment/oms4 -- /bin/sh
kubectl -n oms exec -it deployment/oms5 -- /bin/sh
```

Django OMS2:

```powershell
kubectl -n oms exec -it deployment/oms2 -- /bin/sh
```

Kafka:

```powershell
kubectl -n oms exec -it deployment/kafka -- /bin/bash
```

Postgres:

```powershell
kubectl -n oms exec -it deployment/oms2-postgres -- /bin/bash
```

Если `bash` отсутствует, используйте `/bin/sh`:

```powershell
kubectl -n oms exec -it deployment/kafka -- /bin/sh
```

### 20.2. Через Имя Pod

Получить pod names:

```powershell
kubectl -n oms get pods
```

Подключиться:

```powershell
kubectl -n oms exec -it <pod-name> -- /bin/sh
```

Пример:

```powershell
kubectl -n oms exec -it oms3-xxxxxxxxxx-yyyyy -- /bin/sh
```

### 20.3. Выполнить Одну Команду В Pod Без Интерактивного Shell

```powershell
kubectl -n oms exec deployment/oms1 -- env
kubectl -n oms exec deployment/oms3 -- python -c "import socket; print(socket.gethostname())"
kubectl -n oms exec deployment/oms2 -- python manage.py showmigrations
kubectl -n oms exec deployment/oms2-postgres -- psql -U oms2 -d oms2 -c "select 1;"
```

Kafka CLI внутри Kafka pod:

```powershell
kubectl -n oms exec deployment/kafka -- /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
kubectl -n oms exec deployment/kafka -- /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe
```

### 20.4. Port-Forward Для Отдельных Сервисов

Если Ingress не работает, можно временно подключиться напрямую:

```powershell
kubectl -n oms port-forward service/oms1 8001:80
kubectl -n oms port-forward service/oms2 8002:80
kubectl -n oms port-forward service/oms3 8003:80
kubectl -n oms port-forward service/oms4 8004:80
kubectl -n oms port-forward service/oms5 8005:80
kubectl -n oms port-forward service/kafka 9092:9092
kubectl -n oms port-forward service/oms2-postgres 5432:5432
```

Остановить port-forward можно через `Ctrl+C` в терминале, где он запущен. Если процесс запущен в фоне, найти и остановить:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*port-forward*' } | Select-Object ProcessId,CommandLine
Stop-Process -Id <ProcessId> -Force
```

## 21. Диагностика

### Посмотреть pods

```powershell
kubectl -n oms get pods
```

### Посмотреть events

```powershell
kubectl -n oms get events --sort-by=.lastTimestamp
```

### Посмотреть логи сервиса

```powershell
kubectl -n oms logs deployment/oms1
kubectl -n oms logs deployment/oms2
kubectl -n oms logs deployment/oms3
kubectl -n oms logs deployment/oms4
kubectl -n oms logs deployment/oms5
kubectl -n oms logs deployment/kafka
```

### Посмотреть предыдущие логи после CrashLoopBackOff

```powershell
kubectl -n oms logs deployment/oms1 --previous
kubectl -n oms logs deployment/kafka --previous
```

### Описать pod

```powershell
kubectl -n oms describe pod -l app=oms1
kubectl -n oms describe pod -l app=kafka
```

### Проверить Ingress

```powershell
kubectl -n oms get ingress
kubectl -n oms describe ingress oms-ingress
kubectl -n ingress-nginx logs deployment/ingress-nginx-controller --tail=100
```

## 22. Частые проблемы и решения

### ImagePullBackOff для OMS1-OMS5

Причина: образ не загружен в kind.

Решение:

```powershell
kind load docker-image oms1:latest --name oms-cluster
kubectl -n oms rollout restart deployment oms1
```

### `kind load` не работает для Kafka image

Использовать pull внутри kind node:

```powershell
docker exec oms-cluster-control-plane crictl pull docker.io/apache/kafka:3.7.0
```

### OMS2 initContainer падает на миграциях

Причина: Postgres еще не готов.

В актуальном `OMS2/k8s/deployment.yaml` initContainer уже ждет `oms2-postgres:5432`. Применить актуальный манифест:

```powershell
kubectl apply -f OMS2/k8s/deployment.yaml
kubectl -n oms rollout restart deployment oms2
```

### ingress-nginx controller Pending

Причина: нет label `ingress-ready=true`.

Решение:

```powershell
kubectl label node oms-cluster-control-plane ingress-ready=true
```

### `oms.local` не открывается

Проверить hosts:

```text
127.0.0.1 oms.local
```

Проверить DNS:

```powershell
ping oms.local
```

Проверить ingress-nginx:

```powershell
kubectl -n ingress-nginx get pods
kubectl -n oms get ingress
```

### Ingress возвращает 404

Проверить, что применен `platform/k8s/ingress.yaml`:

```powershell
kubectl -n oms describe ingress oms-ingress
```

Проверить URL с правильным prefix:

```text
http://oms.local/oms1/health
http://oms.local/oms2/health/
```

## 23. Полная очистка

Удалить namespace приложения:

```powershell
kubectl delete namespace oms
```

Удалить весь kind-кластер:

```powershell
kind delete cluster --name oms-cluster
```

После удаления кластера нужно заново выполнить шаги создания кластера, установки ingress-nginx, загрузки образов и деплоя.

## 24. Быстрый полный сценарий

Если образы уже собраны:

```powershell
cd D:\ProjectsDocker\extrawork

kind delete cluster --name oms-cluster
New-Item -ItemType Directory -Path ".runtime\oms2-postgres-data" -Force
kind create cluster --config platform/k8s/kind-cluster.yaml
kubectl config use-context kind-oms-cluster

kind load docker-image oms1:latest --name oms-cluster
kind load docker-image oms2:latest --name oms-cluster
kind load docker-image oms3:latest --name oms-cluster
kind load docker-image oms4:latest --name oms-cluster
kind load docker-image oms5:latest --name oms-cluster
docker exec oms-cluster-control-plane crictl pull docker.io/apache/kafka:3.7.0

kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.12.1/deploy/static/provider/kind/deploy.yaml
kubectl wait --namespace ingress-nginx --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=180s

kubectl apply -f platform/k8s/namespace.yaml
kubectl apply -f platform/k8s/kafka-dev.yaml
kubectl apply -f OMS1/k8s/
kubectl apply -f OMS2/k8s/
kubectl apply -f OMS3/k8s/
kubectl apply -f OMS4/k8s/
kubectl apply -f OMS5/k8s/
kubectl apply -f platform/k8s/ingress.yaml

kubectl -n oms get pods
kubectl -n oms get ingress
```

Проверка:

```powershell
curl http://oms.local/oms1/health
curl http://oms.local/oms2/health/
curl http://oms.local/oms3/health
curl http://oms.local/oms3/health/
curl http://oms.local/oms4/health
curl http://oms.local/oms4/health/
curl http://oms.local/oms5/health
curl http://oms.local/oms5/health/
curl http://oms.local/oms1/health/ready
curl http://oms.local/oms2/health/ready/
curl http://oms.local/oms3/health/ready
curl http://oms.local/oms3/health/ready/
curl http://oms.local/oms4/health/ready
curl http://oms.local/oms4/health/ready/
curl http://oms.local/oms5/health/ready
curl http://oms.local/oms5/health/ready/
```
