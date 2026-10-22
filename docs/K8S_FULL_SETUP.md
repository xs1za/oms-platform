# Полная инструкция разворачивания OMS в Kubernetes с нуля

Инструкция рассчитана на локальную разработку в Windows 11 + Docker Desktop + kind + kubectl.

## 1. Что разворачивается

В Kubernetes разворачиваются:

- `OMS1` - сервис авторизации JWT.
- `OMS1 Postgres` - локальная PostGress БД для `OMS1`.
- `OMS2` - сервис сотрудников Employee на Django.
- `OMS2 Postgres` - локальная PostGIS БД для `OMS2`.
- `OMS3` - сервис отчетов.
- `OMS4` - сервис уведомлений email.
- `OMS5` - сервис операционных сущностей: клиент, смена, исполнитель, табель.
- `Kafka` - локальный single-node Kafka для межсервисных событий.
- `RabbitMQ` - локальная очередь команд для lightweight workers, retry и DLQ.
- `AKHQ` - web UI для просмотра Kafka topics, messages и consumer groups.
- `RabbitMQ Management UI` - встроенный web UI RabbitMQ.
- `Prometheus`, `kube-state-metrics`, `prometheus-node-exporter` и `metrics-server` - сбор метрик кластера для Freelens/OpenLens и Kubernetes Metrics API.
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
- host mount для постоянных данных OMS1 Postgres: `.runtime/oms1-postgres-data` -> `/mnt/oms-data/oms1-postgres-data` внутри kind node.
- host mount для постоянных данных OMS2 Postgres: `.runtime/oms2-postgres-data` -> `/mnt/oms-data/oms2-postgres-data` внутри kind node.
- host mount для постоянных данных OMS3 Postgres: `.runtime/oms3-postgres-data` -> `/mnt/oms-data/oms3-postgres-data` внутри kind node.
- host mount для постоянных данных OMS4 Postgres: `.runtime/oms4-postgres-data` -> `/mnt/oms-data/oms4-postgres-data` внутри kind node.
- host mount для постоянных данных OMS5 Postgres: `.runtime/oms5-postgres-data` -> `/mnt/oms-data/oms5-postgres-data` внутри kind node.
- host mount для файлов отчетов OMS3: `.runtime/oms3-reports-data` -> `/mnt/oms-data/oms3-reports-data` внутри kind node.

Перед созданием кластера создать host-папки для постоянных данных OMS1, OMS2, OMS3, OMS4 и OMS5 Postgres, а также файлов отчетов OMS3:

```powershell
New-Item -ItemType Directory -Path ".runtime\oms1-postgres-data" -Force
New-Item -ItemType Directory -Path ".runtime\oms2-postgres-data" -Force
New-Item -ItemType Directory -Path ".runtime\oms3-postgres-data" -Force
New-Item -ItemType Directory -Path ".runtime\oms4-postgres-data" -Force
New-Item -ItemType Directory -Path ".runtime\oms5-postgres-data" -Force
New-Item -ItemType Directory -Path ".runtime\oms3-reports-data" -Force
```

Для `OMS1`-`OMS5`, PostgreSQL и сервисных клиентов рекомендуется хранить локальные значения Kubernetes Secret в одном файле `D:\ProjectsDocker\extrawork\.env.k8s.oms1` и не генерировать новые значения при каждом создании кластера. Файл `.env.k8s.oms1` добавлен в `.gitignore` и не должен коммититься.

Создать файл `.env.k8s.oms1`, если его еще нет:

```powershell
@'
# OMS1
JWT_SECRET_KEY=change-me-in-cluster
POSTGRES_PASSWORD=change-me-oms1-postgres-password
ADMIN_INITIAL_PASSWORD=change-me-admin-password

# OMS2
OMS2_SECRET_KEY=change-me-oms2-secret-key
OMS2_POSTGRES_PASSWORD=change-me-oms2-postgres-password
OMS2_SERVICE_SECRET=change-me-oms2-service-secret

# OMS3
OMS3_POSTGRES_PASSWORD=change-me-oms3-postgres-password
OMS3_SERVICE_SECRET=change-me-oms3-service-secret

# OMS4
OMS4_POSTGRES_PASSWORD=change-me-oms4-postgres-password
OMS4_SERVICE_SECRET=change-me-oms4-service-secret

# OMS5
OMS5_POSTGRES_PASSWORD=change-me-oms5-postgres-password
OMS5_SERVICE_SECRET=change-me-oms5-service-secret
'@ | Set-Content -Encoding utf8 -Path "D:\ProjectsDocker\extrawork\.env.k8s.oms1"
```

Проверить, что файл содержит все обязательные ключи PostgreSQL до создания Kubernetes Secret:

```powershell
$envFile = "D:\ProjectsDocker\extrawork\.env.k8s.oms1"
$requiredKeys = @("POSTGRES_PASSWORD", "OMS2_POSTGRES_PASSWORD", "OMS3_POSTGRES_PASSWORD", "OMS4_POSTGRES_PASSWORD", "OMS5_POSTGRES_PASSWORD")
$envValues = @{}
Get-Content $envFile | Where-Object { $_ -match '^[^#]+=.*$' } | ForEach-Object { $parts = $_ -split '=', 2; $envValues[$parts[0]] = $parts[1] }
$missingKeys = $requiredKeys | Where-Object { -not $envValues.ContainsKey($_) -or [string]::IsNullOrWhiteSpace($envValues[$_]) }
if ($missingKeys) { throw "В $envFile отсутствуют ключи: $($missingKeys -join ', ')" }
```

Если папки `.runtime\oms1-postgres-data`, `.runtime\oms2-postgres-data`, `.runtime\oms3-postgres-data`, `.runtime\oms4-postgres-data` или `.runtime\oms5-postgres-data` уже содержат данные и их нужно сохранить, значения `POSTGRES_PASSWORD`, `OMS2_POSTGRES_PASSWORD`, `OMS3_POSTGRES_PASSWORD`, `OMS4_POSTGRES_PASSWORD`, `OMS5_POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `ADMIN_INITIAL_PASSWORD` и `OMS2_SERVICE_SECRET`-`OMS5_SERVICE_SECRET` должны быть теми же, что использовались при первичной инициализации. Пароли `POSTGRES_PASSWORD`, `OMS2_POSTGRES_PASSWORD`, `OMS3_POSTGRES_PASSWORD`, `OMS4_POSTGRES_PASSWORD` и `OMS5_POSTGRES_PASSWORD` должны совпадать с паролями пользователей PostgreSQL `oms1`, `oms2`, `oms3`, `oms4` и `oms5` соответственно; иначе соответствующий сервис не сможет подключиться к сохраненной базе данных.

Если старый кластер уже есть и его нужно пересоздать, сначала убедитесь, что `OMS4_POSTGRES_PASSWORD` совпадает с паролем пользователя `oms4` в сохраненной базе. Для нового кластера используйте значение из файла без публикации его в командах и документации.

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

Проверить, что host mounts для данных OMS1, OMS2, OMS3, OMS4 и OMS5 Postgres, а также файлов отчетов OMS3 видны внутри kind node:

```powershell
docker exec oms-cluster-control-plane ls -la /mnt/oms-data/oms1-postgres-data
docker exec oms-cluster-control-plane ls -la /mnt/oms-data/oms2-postgres-data
docker exec oms-cluster-control-plane ls -la /mnt/oms-data/oms3-postgres-data
docker exec oms-cluster-control-plane ls -la /mnt/oms-data/oms4-postgres-data
docker exec oms-cluster-control-plane ls -la /mnt/oms-data/oms5-postgres-data
docker exec oms-cluster-control-plane ls -la /mnt/oms-data/oms3-reports-data
```

Важно: изменение `extraMounts` в `platform/k8s/kind-cluster.yaml` не применяется к уже созданному kind-кластеру. Чтобы новый mount появился, нужно пересоздать kind-кластер командой `kind delete cluster --name oms-cluster`, затем `kind create cluster --config platform/k8s/kind-cluster.yaml`.

## 5. Собрать Docker-образы микросервисов

Запускать сборку нужно из корневой папки проектов: `D:\ProjectsDocker\extrawork` если нужно отключить использование кэша то применяем ключ `--no-cache`

```powershell
docker build -t oms1:latest .\OMS1 --no-cache
docker build -t oms2:latest .\OMS2 --no-cache
docker build -t oms3:latest .\OMS3 --no-cache
docker build -t oms4:latest .\OMS4 --no-cache
docker build -t oms5:latest .\OMS5 --no-cache
```

Проверить хэш и время сборки образов:

```powershell
docker images oms1
docker images oms2
docker images oms3
docker images oms4
docker images oms5
```

## 6. Загрузить образы микросервисов и инфраструктурных компонентов в kind

kind-кластер не видит локальные Docker images автоматически. Их нужно загрузить в node:

```powershell
kind load docker-image oms1:latest --name oms-cluster
kind load docker-image oms2:latest --name oms-cluster
kind load docker-image oms3:latest --name oms-cluster
kind load docker-image oms4:latest --name oms-cluster
kind load docker-image oms5:latest --name oms-cluster
```

????Проверить внутри kind node????:

```powershell
docker exec oms-cluster-control-plane crictl images | findstr oms
```

Ожидаемо должны быть:

```text
docker.io/library/oms1 latest dc24cc1a96758 86.8MB
docker.io/library/oms2 latest 5ad05671c8317 276MB
docker.io/library/oms3 latest db88ba77f9685 66.3MB
docker.io/library/oms4 latest 21483e477f359 67.2MB
docker.io/library/oms5 latest 84c5a695a877d 65.9MB
```

Загрузить в kind инфраструктурные компоненты предварительно скачав их из сетевого docker registry в локальное хранилище образов:

```
docker pull postgres:16.4-bookworm
docker save postgres:16.4-bookworm | docker exec --privileged -i oms-cluster-control-plane ctr --namespace=k8s.io images import --snapshotter=overlayfs -
```

загрузку в kind выполнить для всех компонентов кластера:

```powershell
docker save rabbitmq:3.13-management | docker exec --privileged -i oms-cluster-control-plane ctr --namespace=k8s.io images import --snapshotter=overlayfs -
docker save tchiotludo/akhq:0.25.1 | docker exec --privileged -i oms-cluster-control-plane ctr --namespace=k8s.io images import --snapshotter=overlayfs -
docker save registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.14.0 | docker exec --privileged -i oms-cluster-control-plane ctr --namespace=k8s.io images import --snapshotter=overlayfs -
```

Проверка что образы попали в kind:

```powershell
docker exec oms-cluster-control-plane crictl images | findstr /I "rabbitmq akhq kube-state"
```

## 7. Подготовить Kafka image

Kafka использует официальный образ:

```text
apache/kafka:3.7.0
```

Скачивание из сетевого registry и загрузка образа kafka в kind:

```powershell
docker pull apache/kafka:3.7.0
kind load docker-image apache/kafka:3.7.0 --name oms-cluster
```

Если `kind load docker-image apache/kafka:3.7.0 --name oms-cluster` падает с ошибкой digest, используйте именно `crictl pull` внутри node, как показано ниже:

```powershell
docker exec oms-cluster-control-plane crictl pull docker.io/apache/kafka:3.7.0
docker exec oms-cluster-control-plane crictl images | findstr kafka
```

## 8. Установить ingress-nginx

```powershell
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.12.1/deploy/static/provider/kind/deploy.yaml
kubectl wait --namespace ingress-nginx --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=180s
```

Если сеть до GitHub нестабильна, сохранить manifest локально и применять его из проекта.

Один раз при доступной сети скачать файл:

```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.12.1/deploy/static/provider/kind/deploy.yaml" -OutFile "platform/k8s/ingress-nginx-kind.yaml"
```

Далее использовать локальный файл:

```powershell
kubectl apply -f platform/k8s/ingress-nginx-kind.yaml
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

Развернуть Kafka, RabbitMQ, Kafka UI и Prometheus:

```powershell
kubectl apply -f platform/k8s/kafka-dev.yaml
kubectl apply -f platform/k8s/rabbitmq-dev.yaml
kubectl apply -f platform/k8s/kafka-ui.yaml
kubectl apply -f platform/k8s/prometheus.yaml
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl -n kube-system patch deployment metrics-server --type='strategic' -p='{"spec":{"template":{"spec":{"containers":[{"name":"metrics-server","args":["--cert-dir=/tmp","--secure-port=10250","--kubelet-preferred-address-types=InternalIP,Hostname","--kubelet-use-node-status-port","--kubelet-insecure-tls","--metric-resolution=15s"]}]}}}}'
kubectl -n kube-system rollout status deployment/metrics-server --timeout=180s
```

Развернуть микросервисы:

```powershell
$oms3PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS3_POSTGRES_PASSWORD=' }) -replace '^OMS3_POSTGRES_PASSWORD=', ''
$oms3ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS3_SERVICE_SECRET=' }) -replace '^OMS3_SERVICE_SECRET=', ''
$oms3PasswordForUrl = [Uri]::EscapeDataString($oms3PostgresPassword)
$oms2PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS2_POSTGRES_PASSWORD=' }) -replace '^OMS2_POSTGRES_PASSWORD=', ''
$oms2SecretKey = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS2_SECRET_KEY=' }) -replace '^OMS2_SECRET_KEY=', ''
$oms2ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS2_SERVICE_SECRET=' }) -replace '^OMS2_SERVICE_SECRET=', ''
$oms2PasswordForUrl = [Uri]::EscapeDataString($oms2PostgresPassword)
$oms4PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS4_POSTGRES_PASSWORD=' }) -replace '^OMS4_POSTGRES_PASSWORD=', ''
$oms4ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS4_SERVICE_SECRET=' }) -replace '^OMS4_SERVICE_SECRET=', ''
$oms4PasswordForUrl = [Uri]::EscapeDataString($oms4PostgresPassword)
$oms5PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS5_POSTGRES_PASSWORD=' }) -replace '^OMS5_POSTGRES_PASSWORD=', ''
$oms5ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS5_SERVICE_SECRET=' }) -replace '^OMS5_SERVICE_SECRET=', ''
$oms5PasswordForUrl = [Uri]::EscapeDataString($oms5PostgresPassword)
kubectl -n oms create secret generic oms1-secret --from-env-file "D:\ProjectsDocker\extrawork\.env.k8s.oms1" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms create secret generic oms2-secret `
  --from-literal=SECRET_KEY="$oms2SecretKey" `
  --from-literal=POSTGRES_PASSWORD="$oms2PostgresPassword" `
  --from-literal=DATABASE_URL="postgis://oms2:$oms2PasswordForUrl@oms2-postgres:5432/oms2" `
  --from-literal=SERVICE_CLIENT_SECRET="$oms2ServiceSecret" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms create secret generic oms3-secret `
  --from-literal=SERVICE_CLIENT_SECRET="$oms3ServiceSecret" `
  --from-literal=POSTGRES_PASSWORD="$oms3PostgresPassword" `
  --from-literal=DATABASE_URL="postgresql://oms3:$oms3PasswordForUrl@oms3-postgres:5432/oms3" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms create secret generic oms4-secret `
  --from-literal=SERVICE_CLIENT_SECRET="$oms4ServiceSecret" `
  --from-literal=POSTGRES_PASSWORD="$oms4PostgresPassword" `
  --from-literal=DATABASE_URL="postgresql://oms4:$oms4PasswordForUrl@oms4-postgres:5432/oms4" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms create secret generic oms5-secret `
  --from-literal=SERVICE_CLIENT_SECRET="$oms5ServiceSecret" `
  --from-literal=POSTGRES_PASSWORD="$oms5PostgresPassword" `
  --from-literal=DATABASE_URL="postgresql://oms5:$oms5PasswordForUrl@oms5-postgres:5432/oms5" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f OMS1/k8s/
kubectl apply -f OMS2/k8s/configmap.yaml -f OMS2/k8s/postgres.yaml -f OMS2/k8s/deployment.yaml -f OMS2/k8s/service.yaml
kubectl apply -f OMS3/k8s/
kubectl apply -f OMS4/k8s/configmap.yaml -f OMS4/k8s/postgres.yaml -f OMS4/k8s/deployment.yaml -f OMS4/k8s/service.yaml
kubectl apply -f OMS5/k8s/
kubectl apply -f platform/k8s/ingress.yaml
```

Важно: `POSTGRES_PASSWORD`, `OMS2_POSTGRES_PASSWORD`, `OMS3_POSTGRES_PASSWORD`, `OMS4_POSTGRES_PASSWORD` и `OMS5_POSTGRES_PASSWORD` применяются соответствующим PostgreSQL только при первой инициализации пустых папок `.runtime\oms1-postgres-data`, `.runtime\oms2-postgres-data`, `.runtime\oms3-postgres-data`, `.runtime\oms4-postgres-data` и `.runtime\oms5-postgres-data`. Если папка уже содержит данные, смена значения в Kubernetes Secret не меняет пароль существующего пользователя БД. Для сохранения данных используйте прежние значения паролей. Для чистого старта удалите содержимое соответствующей папки до запуска PostgreSQL.

---

Перед удалением сервисов или kind-кластера при сохранении данных сохранить текущие значения `oms1-secret`, `oms2-secret`, `oms3-secret`, `oms4-secret` и `oms5-secret` в локальный файл `.env.k8s.oms1`:

```powershell
$secret = kubectl -n oms get secret oms1-secret -o json | ConvertFrom-Json
$oms2Secret = kubectl -n oms get secret oms2-secret -o json | ConvertFrom-Json
$oms3Secret = kubectl -n oms get secret oms3-secret -o json | ConvertFrom-Json
$oms4Secret = kubectl -n oms get secret oms4-secret -o json | ConvertFrom-Json
$oms5Secret = kubectl -n oms get secret oms5-secret -o json | ConvertFrom-Json

function Get-SecretValue($secretObject, $key, $secretName) {
  if (-not $secretObject.data.$key) { throw "В $secretName отсутствует $key; файл .env.k8s.oms1 не изменен" }
  return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($secretObject.data.$key))
}

$lines = @(
  "# OMS1"
  "JWT_SECRET_KEY=$(Get-SecretValue $secret JWT_SECRET_KEY 'oms1-secret')"
  "POSTGRES_PASSWORD=$(Get-SecretValue $secret POSTGRES_PASSWORD 'oms1-secret')"
  "ADMIN_INITIAL_PASSWORD=$(Get-SecretValue $secret ADMIN_INITIAL_PASSWORD 'oms1-secret')"
  ""
  "# OMS2"
  "OMS2_SECRET_KEY=$(Get-SecretValue $oms2Secret SECRET_KEY 'oms2-secret')"
  "OMS2_POSTGRES_PASSWORD=$(Get-SecretValue $oms2Secret POSTGRES_PASSWORD 'oms2-secret')"
  "OMS2_SERVICE_SECRET=$(Get-SecretValue $secret OMS2_SERVICE_SECRET 'oms1-secret')"
  ""
  "# OMS3"
  "OMS3_POSTGRES_PASSWORD=$(Get-SecretValue $oms3Secret POSTGRES_PASSWORD 'oms3-secret')"
  "OMS3_SERVICE_SECRET=$(Get-SecretValue $secret OMS3_SERVICE_SECRET 'oms1-secret')"
  ""
  "# OMS4"
  "OMS4_POSTGRES_PASSWORD=$(Get-SecretValue $oms4Secret POSTGRES_PASSWORD 'oms4-secret')"
  "OMS4_SERVICE_SECRET=$(Get-SecretValue $secret OMS4_SERVICE_SECRET 'oms1-secret')"
  ""
  "# OMS5"
  "OMS5_POSTGRES_PASSWORD=$(Get-SecretValue $oms5Secret POSTGRES_PASSWORD 'oms5-secret')"
  "OMS5_SERVICE_SECRET=$(Get-SecretValue $secret OMS5_SERVICE_SECRET 'oms1-secret')"
)
$lines | Set-Content -Encoding utf8 -Path "D:\ProjectsDocker\extrawork\.env.k8s.oms1"
```

После пересоздания кластера восстановить secret из этого файла:

```powershell
$oms3PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS3_POSTGRES_PASSWORD=' }) -replace '^OMS3_POSTGRES_PASSWORD=', ''
$oms3ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS3_SERVICE_SECRET=' }) -replace '^OMS3_SERVICE_SECRET=', ''
$oms3PasswordForUrl = [Uri]::EscapeDataString($oms3PostgresPassword)
$oms2PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS2_POSTGRES_PASSWORD=' }) -replace '^OMS2_POSTGRES_PASSWORD=', ''
$oms2SecretKey = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS2_SECRET_KEY=' }) -replace '^OMS2_SECRET_KEY=', ''
$oms2ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS2_SERVICE_SECRET=' }) -replace '^OMS2_SERVICE_SECRET=', ''
$oms2PasswordForUrl = [Uri]::EscapeDataString($oms2PostgresPassword)
$oms4PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS4_POSTGRES_PASSWORD=' }) -replace '^OMS4_POSTGRES_PASSWORD=', ''
$oms4ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS4_SERVICE_SECRET=' }) -replace '^OMS4_SERVICE_SECRET=', ''
$oms4PasswordForUrl = [Uri]::EscapeDataString($oms4PostgresPassword)
$oms5PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS5_POSTGRES_PASSWORD=' }) -replace '^OMS5_POSTGRES_PASSWORD=', ''
$oms5ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS5_SERVICE_SECRET=' }) -replace '^OMS5_SERVICE_SECRET=', ''
$oms5PasswordForUrl = [Uri]::EscapeDataString($oms5PostgresPassword)
kubectl -n oms create secret generic oms1-secret --from-env-file "D:\ProjectsDocker\extrawork\.env.k8s.oms1" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms create secret generic oms2-secret `
  --from-literal=SECRET_KEY="$oms2SecretKey" `
  --from-literal=POSTGRES_PASSWORD="$oms2PostgresPassword" `
  --from-literal=DATABASE_URL="postgis://oms2:$oms2PasswordForUrl@oms2-postgres:5432/oms2" `
  --from-literal=SERVICE_CLIENT_SECRET="$oms2ServiceSecret" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms create secret generic oms3-secret `
  --from-literal=SERVICE_CLIENT_SECRET="$oms3ServiceSecret" `
  --from-literal=POSTGRES_PASSWORD="$oms3PostgresPassword" `
  --from-literal=DATABASE_URL="postgresql://oms3:$oms3PasswordForUrl@oms3-postgres:5432/oms3" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms create secret generic oms4-secret `
  --from-literal=SERVICE_CLIENT_SECRET="$oms4ServiceSecret" `
  --from-literal=POSTGRES_PASSWORD="$oms4PostgresPassword" `
  --from-literal=DATABASE_URL="postgresql://oms4:$oms4PasswordForUrl@oms4-postgres:5432/oms4" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms create secret generic oms5-secret `
  --from-literal=SERVICE_CLIENT_SECRET="$oms5ServiceSecret" `
  --from-literal=POSTGRES_PASSWORD="$oms5PostgresPassword" `
  --from-literal=DATABASE_URL="postgresql://oms5:$oms5PasswordForUrl@oms5-postgres:5432/oms5" `
  --dry-run=client -o yaml | kubectl apply -f -
```

`oms2-secret`, `oms3-secret`, `oms4-secret` и `oms5-secret` должны быть восстановлены до запуска соответствующих `postgres.yaml` и `deployment.yaml`. Значения `OMS2_POSTGRES_PASSWORD`, `OMS3_POSTGRES_PASSWORD`, `OMS4_POSTGRES_PASSWORD` и `OMS5_POSTGRES_PASSWORD` в `.env.k8s.oms1` должны совпадать с паролями пользователей в сохраненных базах.

### 9.1. Сменить Начальные Пароли И Service Secrets OMS1

Значения `ADMIN_INITIAL_PASSWORD` и `OMS2_SERVICE_SECRET`-`OMS5_SERVICE_SECRET` используются seed-командой только при создании отсутствующих записей в пустой БД. Если пользователь `admin` или service client уже есть в PostgreSQL, изменение `.env.k8s.oms1` не меняет hash в таблицах `users` и `service_clients`.

Чтобы сменить пароль `admin` после первичной инициализации БД, выполнить management-команду внутри `OMS1`:

```powershell
kubectl -n oms exec deployment/oms1 -- python -m app.set_user_password admin "new-admin-password"
```

После успешной смены обновить локальный `.env.k8s.oms1`, чтобы значение сохранилось для следующего пересоздания кластера:

```env
ADMIN_INITIAL_PASSWORD=new-admin-password
```

Чтобы сменить service secret для сервисного клиента, выполнить management-команду:

```powershell
kubectl -n oms exec deployment/oms1 -- python -m app.set_service_secret OMS2 "new-oms2-secret"
kubectl -n oms exec deployment/oms1 -- python -m app.set_service_secret OMS3 "new-oms3-secret"
kubectl -n oms exec deployment/oms1 -- python -m app.set_service_secret OMS4 "new-oms4-secret"
kubectl -n oms exec deployment/oms1 -- python -m app.set_service_secret OMS5 "new-oms5-secret"
```

После успешной смены обновить соответствующие значения в `.env.k8s.oms1`:

```env
OMS2_SERVICE_SECRET=new-oms2-secret
OMS3_SERVICE_SECRET=new-oms3-secret
OMS4_SERVICE_SECRET=new-oms4-secret
OMS5_SERVICE_SECRET=new-oms5-secret
```

Также обновить Kubernetes Secrets сервисов-клиентов, чтобы сами `OMS2`-`OMS5` использовали новые plaintext secrets при обращении к `OMS1`:

```powershell
kubectl -n oms patch secret oms2-secret --type merge -p '{"stringData":{"SERVICE_CLIENT_SECRET":"new-oms2-secret"}}'
kubectl -n oms patch secret oms3-secret --type merge -p '{"stringData":{"SERVICE_CLIENT_SECRET":"new-oms3-secret"}}'
kubectl -n oms patch secret oms4-secret --type merge -p '{"stringData":{"SERVICE_CLIENT_SECRET":"new-oms4-secret"}}'
kubectl -n oms create secret generic oms5-secret --from-literal=SERVICE_CLIENT_SECRET=new-oms5-secret --dry-run=client -o yaml | kubectl apply -f -
```

Перезапустить сервисы и worker-ы, чтобы pod-ы перечитали env:

```powershell
kubectl -n oms rollout restart deployment/oms2
kubectl -n oms rollout restart deployment/oms3
kubectl -n oms rollout restart deployment/oms3-problem-event-worker
kubectl -n oms rollout restart deployment/oms3-postgres
kubectl -n oms rollout restart deployment/oms4
kubectl -n oms rollout restart deployment/oms4-email-worker
kubectl -n oms rollout restart deployment/oms4-problem-event-worker
kubectl -n oms rollout restart deployment/oms4-postgres
kubectl -n oms rollout restart deployment/oms5
```

### Сменить `OMS2_SECRET_KEY`

`OMS2_SECRET_KEY` — криптографический ключ Django OMS2, а не пароль PostgreSQL. Его изменение не требует изменения роли `oms2` в базе данных, но делает недействительными существующие Django-сессии, CSRF-токены и другие подписанные значения.

Сгенерировать новое значение, сохранить его в `.env.k8s.oms1`, пересоздать `oms2-secret` со всеми необходимыми ключами и перезапустить OMS2:

```powershell
$envFile = "D:\ProjectsDocker\extrawork\.env.k8s.oms1"
$bytes = New-Object byte[] 64
[Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$newOms2SecretKey = [Convert]::ToBase64String($bytes)
$envLines = Get-Content $envFile
if ($envLines -match '^OMS2_SECRET_KEY=') {
  $envLines = $envLines -replace '^OMS2_SECRET_KEY=.*$', "OMS2_SECRET_KEY=$newOms2SecretKey"
} else {
  $envLines += "OMS2_SECRET_KEY=$newOms2SecretKey"
}
$envLines | Set-Content -Encoding utf8 -Path $envFile

$oms2PostgresPassword = (Get-Content $envFile | Where-Object { $_ -match '^OMS2_POSTGRES_PASSWORD=' }) -replace '^OMS2_POSTGRES_PASSWORD=', ''
$oms2ServiceSecret = (Get-Content $envFile | Where-Object { $_ -match '^OMS2_SERVICE_SECRET=' }) -replace '^OMS2_SERVICE_SECRET=', ''
$oms2PasswordForUrl = [Uri]::EscapeDataString($oms2PostgresPassword)
kubectl -n oms create secret generic oms2-secret `
  --from-literal=SECRET_KEY="$newOms2SecretKey" `
  --from-literal=POSTGRES_PASSWORD="$oms2PostgresPassword" `
  --from-literal=DATABASE_URL="postgis://oms2:$oms2PasswordForUrl@oms2-postgres:5432/oms2" `
  --from-literal=SERVICE_CLIENT_SECRET="$oms2ServiceSecret" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms rollout restart deployment/oms2
kubectl -n oms rollout status deployment/oms2 --timeout=240s
```

После перезапуска проверить `GET http://oms.local/oms2/health/ready` и повторно войти в OMS2. Не удалять PVC и не менять `OMS2_POSTGRES_PASSWORD` в рамках этой операции.

---

`oms2-postgres`, `oms3-postgres`, `oms4-postgres` и `oms5-postgres` перечитывают `POSTGRES_PASSWORD` из соответствующего Secret при запуске POD. Рестарт не меняет пароль уже инициализированного пользователя PostgreSQL. Для смены пароля каждого сервиса необходимо отдельно изменить пароль в базе, обновить соответствующую переменную в `D:\ProjectsDocker\extrawork\.env.k8s.oms1`, пересоздать Secret и перезапустить PostgreSQL и связанные сервисы.

---

Для смены пароля пользователя PostgreSQL `oms2` сначала замените значение `OMS2_POSTGRES_PASSWORD` в `D:\ProjectsDocker\extrawork\.env.k8s.oms1`. Не удаляйте PVC `oms2-postgres-data`. Затем выполните:

```powershell
$oms2PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS2_POSTGRES_PASSWORD=' }) -replace '^OMS2_POSTGRES_PASSWORD=', ''
$oms2PasswordSql = $oms2PostgresPassword.Replace("'", "''")
kubectl -n oms exec deployment/oms2-postgres -- psql -U oms2 -d oms2 -c "ALTER ROLE oms2 PASSWORD '$oms2PasswordSql';"
$oms2SecretKey = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS2_SECRET_KEY=' }) -replace '^OMS2_SECRET_KEY=', ''
$oms2ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS2_SERVICE_SECRET=' }) -replace '^OMS2_SERVICE_SECRET=', ''
$oms2PasswordForUrl = [Uri]::EscapeDataString($oms2PostgresPassword)
kubectl -n oms create secret generic oms2-secret `
  --from-literal=SECRET_KEY="$oms2SecretKey" `
  --from-literal=POSTGRES_PASSWORD="$oms2PostgresPassword" `
  --from-literal=DATABASE_URL="postgis://oms2:$oms2PasswordForUrl@oms2-postgres:5432/oms2" `
  --from-literal=SERVICE_CLIENT_SECRET="$oms2ServiceSecret" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms rollout restart deployment/oms2-postgres
kubectl -n oms rollout restart deployment/oms2
```

После изменения проверить, что `OMS2_POSTGRES_PASSWORD` в файле, пароль пользователя `oms2` в базе, ключ `POSTGRES_PASSWORD` в `oms2-secret` и пароль в `DATABASE_URL` совпадают.

---

Для смены пароля пользователя PostgreSQL `oms3` сначала замените значение `OMS3_POSTGRES_PASSWORD` в `D:\ProjectsDocker\extrawork\.env.k8s.oms1`. Не удаляйте PVC `oms3-postgres-data`. Затем выполните:

```powershell
$oms3PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS3_POSTGRES_PASSWORD=' }) -replace '^OMS3_POSTGRES_PASSWORD=', ''
$oms3PasswordSql = $oms3PostgresPassword.Replace("'", "''")
kubectl -n oms exec deployment/oms3-postgres -- psql -U oms3 -d oms3 -c "ALTER ROLE oms3 PASSWORD '$oms3PasswordSql';"
$oms3ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS3_SERVICE_SECRET=' }) -replace '^OMS3_SERVICE_SECRET=', ''
$oms3PasswordForUrl = [Uri]::EscapeDataString($oms3PostgresPassword)
kubectl -n oms create secret generic oms3-secret `
  --from-literal=SERVICE_CLIENT_SECRET="$oms3ServiceSecret" `
  --from-literal=POSTGRES_PASSWORD="$oms3PostgresPassword" `
  --from-literal=DATABASE_URL="postgresql://oms3:$oms3PasswordForUrl@oms3-postgres:5432/oms3" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms rollout restart deployment/oms3-postgres
kubectl -n oms rollout restart deployment/oms3
kubectl -n oms rollout restart deployment/oms3-problem-event-worker
```

После изменения проверить, что `OMS3_POSTGRES_PASSWORD` в файле, пароль пользователя `oms3` в базе, ключ `POSTGRES_PASSWORD` в `oms3-secret` и пароль в `DATABASE_URL` совпадают. Смена значения только в Kubernetes Secret не изменяет пароль уже инициализированной базы.

---

Для смены пароля пользователя PostgreSQL `oms4` сначала замените значение `OMS4_POSTGRES_PASSWORD` в `D:\ProjectsDocker\extrawork\.env.k8s.oms1`. Не удаляйте PVC `oms4-postgres-data`. Затем выполните:

```powershell
$oms4PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS4_POSTGRES_PASSWORD=' }) -replace '^OMS4_POSTGRES_PASSWORD=', ''
$oms4PasswordSql = $oms4PostgresPassword.Replace("'", "''")
kubectl -n oms exec deployment/oms4-postgres -- psql -U oms4 -d oms4 -c "ALTER ROLE oms4 PASSWORD '$oms4PasswordSql';"
$oms4ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS4_SERVICE_SECRET=' }) -replace '^OMS4_SERVICE_SECRET=', ''
$oms4PasswordForUrl = [Uri]::EscapeDataString($oms4PostgresPassword)
kubectl -n oms create secret generic oms4-secret `
  --from-literal=SERVICE_CLIENT_SECRET="$oms4ServiceSecret" `
  --from-literal=POSTGRES_PASSWORD="$oms4PostgresPassword" `
  --from-literal=DATABASE_URL="postgresql://oms4:$oms4PasswordForUrl@oms4-postgres:5432/oms4" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms rollout restart deployment/oms4-postgres
kubectl -n oms rollout restart deployment/oms4
kubectl -n oms rollout restart deployment/oms4-email-worker
kubectl -n oms rollout restart deployment/oms4-problem-event-worker
```

После изменения проверить, что `OMS4_POSTGRES_PASSWORD` в файле, пароль пользователя `oms4` в базе, ключ `POSTGRES_PASSWORD` в `oms4-secret` и пароль в `DATABASE_URL` совпадают. Смена значения только в Kubernetes Secret не изменяет пароль уже инициализированной базы.

---

Для смены пароля пользователя PostgreSQL `oms5` сначала замените значение `OMS5_POSTGRES_PASSWORD` в `D:\ProjectsDocker\extrawork\.env.k8s.oms1`. Не удаляйте PVC `oms5-postgres-data`. Затем выполните:

```powershell
$oms5PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS5_POSTGRES_PASSWORD=' }) -replace '^OMS5_POSTGRES_PASSWORD=', ''
$oms5PasswordSql = $oms5PostgresPassword.Replace("'", "''")
kubectl -n oms exec deployment/oms5-postgres -- psql -U oms5 -d oms5 -c "ALTER ROLE oms5 PASSWORD '$oms5PasswordSql';"
$oms5ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS5_SERVICE_SECRET=' }) -replace '^OMS5_SERVICE_SECRET=', ''
$oms5PasswordForUrl = [Uri]::EscapeDataString($oms5PostgresPassword)
kubectl -n oms create secret generic oms5-secret `
  --from-literal=SERVICE_CLIENT_SECRET="$oms5ServiceSecret" `
  --from-literal=POSTGRES_PASSWORD="$oms5PostgresPassword" `
  --from-literal=DATABASE_URL="postgresql://oms5:$oms5PasswordForUrl@oms5-postgres:5432/oms5" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms rollout restart deployment/oms5-postgres
kubectl -n oms rollout restart deployment/oms5
```

После изменения проверить, что `OMS5_POSTGRES_PASSWORD` в файле, пароль пользователя `oms5` в базе, ключ `POSTGRES_PASSWORD` в `oms5-secret` и пароль в `DATABASE_URL` совпадают. Смена значения только в Kubernetes Secret не изменяет пароль уже инициализированной базы.

Затем пересоздать Kubernetes Secret и перезапустить `OMS1`, чтобы runtime env соответствовал локальному файлу:

```powershell
kubectl -n oms create secret generic oms1-secret --from-env-file "D:\ProjectsDocker\extrawork\.env.k8s.oms1" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms rollout restart deployment/oms1
kubectl -n oms rollout status deployment/oms1 --timeout=240s
```

Management-команды не выводят plaintext password/secret в logs; они пересчитывают hash и сохраняют только hash в PostgreSQL.

Проверить pods:

```powershell
kubectl -n oms get pods -w
```

Ожидаемое итоговое состояние:

```text
kafka           1/1   Running
rabbitmq        1/1   Running
akhq            1/1   Running
prometheus      1/1   Running
kube-state-metrics 1/1 Running
oms1            1/1   Running
oms1-postgres   1/1   Running
oms2            1/1   Running
oms2-postgres   1/1   Running
oms3            1/1   Running
oms3-problem-event-worker 1/1 Running
oms3-postgres   1/1   Running
oms4            1/1   Running
oms4-email-worker 1/1 Running
oms4-problem-event-worker 1/1 Running
oms4-postgres   1/1   Running
oms5            1/1   Running
```

`oms3-problem-event-worker` и `oms4-problem-event-worker` читают RabbitMQ queues `problem-events.reprocess` / `problem-events.reprocess.manual` и выполняют повторную обработку Kafka problem events. Production rollout этих workers описан отдельно:

```text
platform/docs/PROBLEM_EVENT_WORKERS_PRODUCTION_RUNBOOK.md
```

Проверить services:

```powershell
kubectl -n oms get svc
```

## 9.2. Создать Django Superuser Для OMS2 Admin

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
127.0.0.1 prometheus.oms.local
127.0.0.1 kafka.oms.local
127.0.0.1 rabbitmq.oms.local
```

Проверить:

```powershell
ping oms.local
ping prometheus.oms.local
ping kafka.oms.local
ping rabbitmq.oms.local
```

Должно резолвиться в `127.0.0.1`.

## 11. Применить Ingress

```powershell
kubectl apply -f platform/k8s/ingress.yaml
kubectl -n oms get ingress
```

Ожидаемо:

```text
oms-ingress          nginx   oms.local
prometheus-ingress   nginx   prometheus.oms.local
kafka-ui-ingress     nginx   kafka.oms.local
rabbitmq-ingress     nginx   rabbitmq.oms.local
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
curl http://prometheus.oms.local/-/ready
curl http://kafka.oms.local
curl http://rabbitmq.oms.local
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

## 15. Постоянные Данные OMS1, OMS2, OMS3, OMS4 И OMS5 Postgres

OMS1, OMS2, OMS3, OMS4 и OMS5 Postgres используют статические `PersistentVolume`, которые хранят данные не внутри pod и не внутри временного local-path volume kind, а в host-папках проекта:

```text
D:\ProjectsDocker\extrawork\.runtime\oms1-postgres-data
D:\ProjectsDocker\extrawork\.runtime\oms2-postgres-data
D:\ProjectsDocker\extrawork\.runtime\oms3-postgres-data
D:\ProjectsDocker\extrawork\.runtime\oms4-postgres-data
D:\ProjectsDocker\extrawork\.runtime\oms5-postgres-data
D:\ProjectsDocker\extrawork\.runtime\oms3-reports-data
```

Эти папки монтируются в kind node через `platform/k8s/kind-cluster.yaml`:

```text
host:      D:\ProjectsDocker\extrawork\.runtime\oms1-postgres-data
kind node: /mnt/oms-data/oms1-postgres-data
pod:       /var/lib/postgresql/data

host:      D:\ProjectsDocker\extrawork\.runtime\oms3-postgres-data
kind node: /mnt/oms-data/oms3-postgres-data
pod:       /var/lib/postgresql/data

host:      D:\ProjectsDocker\extrawork\.runtime\oms4-postgres-data
kind node: /mnt/oms-data/oms4-postgres-data
pod:       /var/lib/postgresql/data

host:      D:\ProjectsDocker\extrawork\.runtime\oms3-reports-data
kind node: /mnt/oms-data/oms3-reports-data
pod:       /data/reports

host:      D:\ProjectsDocker\extrawork\.runtime\oms2-postgres-data
kind node: /mnt/oms-data/oms2-postgres-data
pod:       /var/lib/postgresql/data

host:      D:\ProjectsDocker\extrawork\.runtime\oms5-postgres-data
kind node: /mnt/oms-data/oms5-postgres-data
pod:       /var/lib/postgresql/data
```

Файлы данных не коммитятся в Git. Папка `.runtime/` добавлена в `.gitignore`.

### Проверить PVC/PV

```powershell
kubectl -n oms get pvc oms1-postgres-data
kubectl -n oms get pvc oms2-postgres-data
kubectl -n oms get pvc oms3-postgres-data
kubectl -n oms get pvc oms4-postgres-data
kubectl -n oms get pvc oms5-postgres-data
kubectl -n oms get pvc oms3-reports-data
kubectl get pv oms1-postgres-data-pv
kubectl get pv oms2-postgres-data-pv
kubectl get pv oms3-postgres-data-pv
kubectl get pv oms4-postgres-data-pv
kubectl get pv oms5-postgres-data-pv
kubectl get pv oms3-reports-data-pv
kubectl get pv oms1-postgres-data-pv -o yaml
kubectl get pv oms2-postgres-data-pv -o yaml
```

Ожидаемо:

```text
oms1-postgres-data   Bound
oms2-postgres-data   Bound
oms3-postgres-data   Bound
oms4-postgres-data   Bound
oms5-postgres-data   Bound
oms3-reports-data    Bound
oms1-postgres-data-pv   Bound
oms2-postgres-data-pv   Bound
oms3-postgres-data-pv   Bound
oms4-postgres-data-pv   Bound
oms5-postgres-data-pv   Bound
oms3-reports-data-pv    Bound
```

### Проверить Файлы На Host

```powershell
Get-ChildItem -LiteralPath ".runtime\oms1-postgres-data"
Get-ChildItem -LiteralPath ".runtime\oms2-postgres-data"
Get-ChildItem -LiteralPath ".runtime\oms3-postgres-data"
Get-ChildItem -LiteralPath ".runtime\oms4-postgres-data"
Get-ChildItem -LiteralPath ".runtime\oms5-postgres-data"
Get-ChildItem -LiteralPath ".runtime\oms3-reports-data"
```

### Проверить Mount Внутри Kind Node

```powershell
docker exec oms-cluster-control-plane ls -la /mnt/oms-data/oms1-postgres-data
docker exec oms-cluster-control-plane ls -la /mnt/oms-data/oms2-postgres-data
docker exec oms-cluster-control-plane ls -la /mnt/oms-data/oms3-postgres-data
docker exec oms-cluster-control-plane ls -la /mnt/oms-data/oms4-postgres-data
docker exec oms-cluster-control-plane ls -la /mnt/oms-data/oms5-postgres-data
docker exec oms-cluster-control-plane ls -la /mnt/oms-data/oms3-reports-data
```

### Проверить Доступность БД

```powershell
kubectl -n oms exec deployment/oms1-postgres -- psql -U oms1 -d oms1 -c "select 1;"
curl http://oms.local/oms1/health/ready
kubectl -n oms exec deployment/oms2-postgres -- psql -U oms2 -d oms2 -c "select 1;"
curl http://oms.local/oms2/health/ready/
kubectl -n oms exec deployment/oms3-postgres -- psql -U oms3 -d oms3 -c "select 1;"
curl http://oms.local/oms3/health/ready/
kubectl -n oms exec deployment/oms4-postgres -- psql -U oms4 -d oms4 -c "select 1;"
curl http://oms.local/oms4/health/ready
kubectl -n oms exec deployment/oms5-postgres -- psql -U oms5 -d oms5 -c "select 1;"
curl http://oms.local/oms5/health/ready
```

### Пересоздание Kind-Кластера Без Потери Данных OMS1, OMS2, OMS3, OMS4 И OMS5

Данные сохранятся, если не удалять папку:

```text
.runtime\oms1-postgres-data
.runtime\oms2-postgres-data
.runtime\oms3-postgres-data
.runtime\oms4-postgres-data
.runtime\oms5-postgres-data
.runtime\oms3-reports-data
```

Порядок:

```powershell
kind delete cluster --name oms-cluster
New-Item -ItemType Directory -Path ".runtime\oms1-postgres-data" -Force
New-Item -ItemType Directory -Path ".runtime\oms2-postgres-data" -Force
New-Item -ItemType Directory -Path ".runtime\oms3-postgres-data" -Force
New-Item -ItemType Directory -Path ".runtime\oms4-postgres-data" -Force
New-Item -ItemType Directory -Path ".runtime\oms5-postgres-data" -Force
New-Item -ItemType Directory -Path ".runtime\oms3-reports-data" -Force
kind create cluster --config platform/k8s/kind-cluster.yaml
kubectl config use-context kind-oms-cluster
```

Затем применить manifests:

```powershell
kubectl apply -f platform/k8s/namespace.yaml
kubectl apply -f platform/k8s/kafka-dev.yaml
kubectl apply -f platform/k8s/rabbitmq-dev.yaml
kubectl apply -f platform/k8s/prometheus.yaml
kubectl apply -f OMS2/k8s/postgres.yaml
kubectl apply -f OMS2/k8s/configmap.yaml -f OMS2/k8s/deployment.yaml -f OMS2/k8s/service.yaml
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

Используйте этот вариант для обычной перезагрузки ПК. Kubernetes objects сохраняются внутри kind node container, а данные OMS1, OMS2, OMS3, OMS4 и OMS5 Postgres и файлы отчетов OMS3 остаются на host в `.runtime\oms1-postgres-data`, `.runtime\oms2-postgres-data`, `.runtime\oms3-postgres-data`, `.runtime\oms4-postgres-data`, `.runtime\oms5-postgres-data` и `.runtime\oms3-reports-data`.

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
kubectl -n oms scale deployment/oms3-problem-event-worker --replicas=0
kubectl -n oms scale deployment/oms4-problem-event-worker --replicas=0
kubectl -n oms scale deployment/oms4-email-worker --replicas=0
kubectl -n oms scale deployment/akhq --replicas=0
kubectl -n oms scale deployment/kafka --replicas=0
kubectl -n oms scale deployment/rabbitmq --replicas=0
kubectl -n oms scale deployment/prometheus --replicas=0
kubectl -n oms scale deployment/kube-state-metrics --replicas=0
kubectl -n oms scale deployment/oms1-postgres --replicas=0
kubectl -n oms scale deployment/oms2-postgres --replicas=0
kubectl -n oms scale deployment/oms3-postgres --replicas=0
kubectl -n oms scale deployment/oms4-postgres --replicas=0
kubectl -n oms delete daemonset prometheus-node-exporter
$kafkaTopicsInitStatus = kubectl -n oms get job kafka-topics-init -o jsonpath="{.status.succeeded}" 2>$null
if ($kafkaTopicsInitStatus -eq "1") { kubectl -n oms delete job kafka-topics-init --wait=true }
```

Команда удаляет завершившийся одноразовый `kafka-topics-init` Job вместе с pod `kafka-topics-init-*`. Масштабирование Deployment-ов не удаляет Job и его завершившийся pod автоматически.

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

Используйте этот вариант, если кластер нужно пересоздать с нуля или Docker Desktop нестабилен. Kubernetes objects будут удалены, но данные OMS1, OMS2, OMS3, OMS4 и OMS5 Postgres, а также файлы отчетов OMS3 сохранятся, если не удалять папки `.runtime\oms1-postgres-data`, `.runtime\oms2-postgres-data`, `.runtime\oms3-postgres-data`, `.runtime\oms4-postgres-data`, `.runtime\oms5-postgres-data` и `.runtime\oms3-reports-data`.

```powershell
cd D:\ProjectsDocker\extrawork
kubectl config use-context kind-oms-cluster
kubectl -n oms scale deployment/oms1 --replicas=0
kubectl -n oms scale deployment/oms1-postgres --replicas=0
kubectl -n oms scale deployment/oms2 --replicas=0
kubectl -n oms scale deployment/oms2-postgres --replicas=0
kubectl -n oms scale deployment/oms3 --replicas=0
kubectl -n oms scale deployment/oms3-postgres --replicas=0
kubectl -n oms scale deployment/oms4 --replicas=0
kubectl -n oms scale deployment/oms4-postgres --replicas=0
kubectl -n oms scale deployment/oms5 --replicas=0
kubectl -n oms scale deployment/oms5-postgres --replicas=0
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

Важно: перед удалением кластера сохраните `oms2-secret`, `oms3-secret`, `oms4-secret` и `oms5-secret` в `.env.k8s.oms1` по инструкции выше. Не удаляйте `.runtime\oms1-postgres-data`, `.runtime\oms2-postgres-data`, `.runtime\oms3-postgres-data`, `.runtime\oms4-postgres-data`, `.runtime\oms5-postgres-data` и `.runtime\oms3-reports-data`, если нужно сохранить базы данных и файлы отчетов OMS1, OMS2, OMS3, OMS4 и OMS5.

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
kubectl get nodes --no-headers | Where-Object { $_ -notmatch ' Ready ' } | ForEach-Object { throw "Kubernetes node is not Ready: $_" }
kubectl apply -f platform/k8s/prometheus.yaml
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl -n kube-system patch deployment metrics-server --type='strategic' -p='{"spec":{"template":{"spec":{"containers":[{"name":"metrics-server","args":["--cert-dir=/tmp","--secure-port=10250","--kubelet-preferred-address-types=InternalIP,Hostname","--kubelet-use-node-status-port","--kubelet-insecure-tls","--metric-resolution=15s"]}]}}}}'
kubectl -n oms rollout status deployment/prometheus --timeout=180s
kubectl -n oms rollout status deployment/kube-state-metrics --timeout=180s
kubectl -n oms rollout status daemonset/prometheus-node-exporter --timeout=180s
kubectl -n kube-system rollout status deployment/metrics-server --timeout=180s
$kafkaTopicsInitStatus = kubectl -n oms get job kafka-topics-init -o jsonpath="{.status.succeeded}" 2>$null
if ($kafkaTopicsInitStatus -eq "1") { kubectl -n oms delete job kafka-topics-init --wait=true }
kubectl -n oms get pods
```

### 17.4. Запустить Все Workloads Повторно

Если namespace и deployments существуют, поднять replicas всех deployment-ов обратно до `1`. Это обязательно после корректного завершения из пункта 16.1, потому что там deployments были остановлены через `scale --replicas=0`. Команда `deployment --all` включает все PostgreSQL deployment-ы, OMS-сервисы, workers и системные приложения namespace `oms`.

```powershell
kubectl -n oms scale deployment --all --replicas=1
kubectl -n oms wait --for=condition=available deployment --all --timeout=300s
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

Проверить, что стандартные и Prometheus-метрики доступны после восстановления:

```powershell
kubectl top nodes
kubectl top pods -A
kubectl get --raw "/api/v1/namespaces/oms/services/prometheus-server/proxy/-/ready"
```

Ожидаемо в итоге:

```text
kafka-...           1/1   Running
rabbitmq-...        1/1   Running
akhq-...            1/1   Running
prometheus-...      1/1   Running
kube-state-metrics-... 1/1 Running
oms1-...            1/1   Running
oms2-...            1/1   Running
oms2-postgres-...   1/1   Running
oms3-...            1/1   Running
oms3-postgres-...   1/1   Running
oms4-...            1/1   Running
oms4-postgres-...   1/1   Running
oms5-...            1/1   Running
prometheus-node-exporter-... 1/1 Running
```

Если deployments отсутствуют, применить манифесты заново:

```powershell
kubectl apply -f platform/k8s/namespace.yaml
kubectl apply -f platform/k8s/kafka-dev.yaml
kubectl apply -f platform/k8s/rabbitmq-dev.yaml
kubectl apply -f platform/k8s/kafka-ui.yaml
kubectl apply -f platform/k8s/prometheus.yaml
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl -n kube-system patch deployment metrics-server --type='strategic' -p='{"spec":{"template":{"spec":{"containers":[{"name":"metrics-server","args":["--cert-dir=/tmp","--secure-port=10250","--kubelet-preferred-address-types=InternalIP,Hostname","--kubelet-use-node-status-port","--kubelet-insecure-tls","--metric-resolution=15s"]}]}}}}'
kubectl -n kube-system rollout status deployment/metrics-server --timeout=180s
$oms2PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS2_POSTGRES_PASSWORD=' }) -replace '^OMS2_POSTGRES_PASSWORD=', ''
$oms2SecretKey = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS2_SECRET_KEY=' }) -replace '^OMS2_SECRET_KEY=', ''
$oms2ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS2_SERVICE_SECRET=' }) -replace '^OMS2_SERVICE_SECRET=', ''
$oms2PasswordForUrl = [Uri]::EscapeDataString($oms2PostgresPassword)
$oms3PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS3_POSTGRES_PASSWORD=' }) -replace '^OMS3_POSTGRES_PASSWORD=', ''
$oms3ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS3_SERVICE_SECRET=' }) -replace '^OMS3_SERVICE_SECRET=', ''
$oms3PasswordForUrl = [Uri]::EscapeDataString($oms3PostgresPassword)
$oms4PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS4_POSTGRES_PASSWORD=' }) -replace '^OMS4_POSTGRES_PASSWORD=', ''
$oms4ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS4_SERVICE_SECRET=' }) -replace '^OMS4_SERVICE_SECRET=', ''
$oms4PasswordForUrl = [Uri]::EscapeDataString($oms4PostgresPassword)
$oms5PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS5_POSTGRES_PASSWORD=' }) -replace '^OMS5_POSTGRES_PASSWORD=', ''
$oms5ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS5_SERVICE_SECRET=' }) -replace '^OMS5_SERVICE_SECRET=', ''
$oms5PasswordForUrl = [Uri]::EscapeDataString($oms5PostgresPassword)
kubectl -n oms create secret generic oms1-secret --from-env-file "D:\ProjectsDocker\extrawork\.env.k8s.oms1" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms create secret generic oms2-secret `
  --from-literal=SECRET_KEY="$oms2SecretKey" `
  --from-literal=POSTGRES_PASSWORD="$oms2PostgresPassword" `
  --from-literal=DATABASE_URL="postgis://oms2:$oms2PasswordForUrl@oms2-postgres:5432/oms2" `
  --from-literal=SERVICE_CLIENT_SECRET="$oms2ServiceSecret" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms create secret generic oms3-secret `
  --from-literal=SERVICE_CLIENT_SECRET="$oms3ServiceSecret" `
  --from-literal=POSTGRES_PASSWORD="$oms3PostgresPassword" `
  --from-literal=DATABASE_URL="postgresql://oms3:$oms3PasswordForUrl@oms3-postgres:5432/oms3" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms create secret generic oms4-secret `
  --from-literal=SERVICE_CLIENT_SECRET="$oms4ServiceSecret" `
  --from-literal=POSTGRES_PASSWORD="$oms4PostgresPassword" `
  --from-literal=DATABASE_URL="postgresql://oms4:$oms4PasswordForUrl@oms4-postgres:5432/oms4" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms create secret generic oms5-secret `
  --from-literal=SERVICE_CLIENT_SECRET="$oms5ServiceSecret" `
  --from-literal=POSTGRES_PASSWORD="$oms5PostgresPassword" `
  --from-literal=DATABASE_URL="postgresql://oms5:$oms5PasswordForUrl@oms5-postgres:5432/oms5" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f OMS1/k8s/
kubectl apply -f OMS2/k8s/configmap.yaml -f OMS2/k8s/postgres.yaml -f OMS2/k8s/deployment.yaml -f OMS2/k8s/service.yaml
kubectl apply -f OMS3/k8s/
kubectl apply -f OMS4/k8s/configmap.yaml -f OMS4/k8s/postgres.yaml -f OMS4/k8s/deployment.yaml -f OMS4/k8s/service.yaml
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

Запустить все deployments обратно, включая OMS1-OMS5, PostgreSQL и workers:

```powershell
kubectl -n oms scale deployment --all --replicas=1
kubectl -n oms wait --for=condition=available deployment --all --timeout=300s
```

Перезапустить все deployments:

```powershell
kubectl -n oms rollout restart deployment --all
kubectl -n oms rollout status deployment --all --timeout=300s
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

### 18.4.1. Kafka UI Через AKHQ

Применить AKHQ manifest:

```powershell
kubectl apply -f platform/k8s/kafka-ui.yaml
```

Проверить deployment и service:

```powershell
kubectl -n oms rollout status deployment/akhq
kubectl -n oms get pods -l app=akhq
kubectl -n oms get svc akhq
```

AKHQ подключается к Kafka service `kafka:9092`. Через Ingress UI доступен по адресу:

```text
http://kafka.oms.local
```

### 18.4.2. RabbitMQ Management UI

RabbitMQ использует image `rabbitmq:3.13-management`, поэтому management UI уже встроен в pod и открыт service port `15672`.

Проверить service:

```powershell
kubectl -n oms get svc rabbitmq
```

Через Ingress UI доступен по адресу:

```text
http://rabbitmq.oms.local
```

Локальные credentials по умолчанию:

```text
user: oms
password: oms
```

### 18.4.3. Prometheus И Метрики Для Freelens

Применить Prometheus manifest:

```powershell
kubectl apply -f platform/k8s/prometheus.yaml
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl -n kube-system patch deployment metrics-server --type='strategic' -p='{"spec":{"template":{"spec":{"containers":[{"name":"metrics-server","args":["--cert-dir=/tmp","--secure-port=10250","--kubelet-preferred-address-types=InternalIP,Hostname","--kubelet-use-node-status-port","--kubelet-insecure-tls","--metric-resolution=15s"]}]}}}}'
kubectl -n kube-system rollout status deployment/metrics-server --timeout=180s
```

Проверить deployments и service:

```powershell
kubectl -n oms get deployment prometheus kube-state-metrics
kubectl -n oms rollout status deployment/prometheus
kubectl -n oms rollout status deployment/kube-state-metrics
kubectl -n oms get svc prometheus prometheus-server kube-state-metrics prometheus-node-exporter
kubectl -n oms rollout status daemonset/prometheus-node-exporter
kubectl -n kube-system rollout status deployment/metrics-server
kubectl top nodes
kubectl top pods -A
```

Проверить targets Prometheus через Ingress:

```text
http://prometheus.oms.local/targets
```

Проверить readiness:

```powershell
curl http://prometheus.oms.local/-/ready
```

Проверить наличие метрик состояния workloads:

```text
kube_pod_status_phase
kube_deployment_status_replicas_available
```

Проверить доступность Prometheus для Freelens через Kubernetes API proxy:

```powershell
kubectl get --raw "/api/v1/namespaces/oms/services/prometheus-server/proxy/-/ready"
kubectl get --raw "/api/v1/namespaces/oms/services/prometheus-server/proxy/api/v1/query?query=up"
```

Проверить наличие CPU/RAM метрик и совместимых Lens labels:

```powershell
kubectl get --raw "/api/v1/namespaces/oms/services/prometheus-server/proxy/api/v1/query?query=node_cpu_seconds_total"
kubectl get --raw "/api/v1/namespaces/oms/services/prometheus-server/proxy/api/v1/query?query=container_cpu_usage_seconds_total%7Bpod_name%21%3D%22%22%2Ccontainer_name%21%3D%22%22%7D"
kubectl get --raw "/api/v1/namespaces/oms/services/prometheus-server/proxy/api/v1/query?query=container_memory_working_set_bytes%7Bpod_name%21%3D%22%22%2Ccontainer_name%21%3D%22%22%7D"
```

Freelens settings:

```text
PROMETHEUS: Helm
PROMETHEUS SERVICE ADDRESS: oms/prometheus-server:80
CUSTOM PATH PREFIX: пусто
PROMETHEUS HTTPS REQUESTS: выключено
PROMETHEUS REQUEST METHOD: GET
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
kubectl -n oms describe ingress prometheus-ingress
kubectl -n oms describe ingress kafka-ui-ingress
kubectl -n oms describe ingress rabbitmq-ingress
curl http://oms.local/oms1/health
curl http://prometheus.oms.local/-/ready
curl http://kafka.oms.local
curl http://rabbitmq.oms.local
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
kubectl -n oms port-forward service/akhq 8080:80
kubectl -n oms port-forward service/rabbitmq 15672:15672
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
kubectl -n oms describe ingress prometheus-ingress
kubectl -n oms describe ingress kafka-ui-ingress
kubectl -n oms describe ingress rabbitmq-ingress
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
127.0.0.1 prometheus.oms.local
127.0.0.1 kafka.oms.local
127.0.0.1 rabbitmq.oms.local
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
New-Item -ItemType Directory -Path ".runtime\oms1-postgres-data" -Force
New-Item -ItemType Directory -Path ".runtime\oms2-postgres-data" -Force
New-Item -ItemType Directory -Path ".runtime\oms3-postgres-data" -Force
New-Item -ItemType Directory -Path ".runtime\oms4-postgres-data" -Force
New-Item -ItemType Directory -Path ".runtime\oms3-reports-data" -Force
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
kubectl apply -f platform/k8s/rabbitmq-dev.yaml
kubectl apply -f platform/k8s/kafka-ui.yaml
kubectl apply -f platform/k8s/prometheus.yaml
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl -n kube-system patch deployment metrics-server --type='strategic' -p='{"spec":{"template":{"spec":{"containers":[{"name":"metrics-server","args":["--cert-dir=/tmp","--secure-port=10250","--kubelet-preferred-address-types=InternalIP,Hostname","--kubelet-use-node-status-port","--kubelet-insecure-tls","--metric-resolution=15s"]}]}}}}'
kubectl -n kube-system rollout status deployment/metrics-server --timeout=180s
$oms2PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS2_POSTGRES_PASSWORD=' }) -replace '^OMS2_POSTGRES_PASSWORD=', ''
$oms2SecretKey = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS2_SECRET_KEY=' }) -replace '^OMS2_SECRET_KEY=', ''
$oms2ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS2_SERVICE_SECRET=' }) -replace '^OMS2_SERVICE_SECRET=', ''
$oms2PasswordForUrl = [Uri]::EscapeDataString($oms2PostgresPassword)
$oms3PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS3_POSTGRES_PASSWORD=' }) -replace '^OMS3_POSTGRES_PASSWORD=', ''
$oms3ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS3_SERVICE_SECRET=' }) -replace '^OMS3_SERVICE_SECRET=', ''
$oms3PasswordForUrl = [Uri]::EscapeDataString($oms3PostgresPassword)
$oms4PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS4_POSTGRES_PASSWORD=' }) -replace '^OMS4_POSTGRES_PASSWORD=', ''
$oms4ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS4_SERVICE_SECRET=' }) -replace '^OMS4_SERVICE_SECRET=', ''
$oms4PasswordForUrl = [Uri]::EscapeDataString($oms4PostgresPassword)
$oms5PostgresPassword = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS5_POSTGRES_PASSWORD=' }) -replace '^OMS5_POSTGRES_PASSWORD=', ''
$oms5ServiceSecret = (Get-Content "D:\ProjectsDocker\extrawork\.env.k8s.oms1" | Where-Object { $_ -match '^OMS5_SERVICE_SECRET=' }) -replace '^OMS5_SERVICE_SECRET=', ''
$oms5PasswordForUrl = [Uri]::EscapeDataString($oms5PostgresPassword)
kubectl -n oms create secret generic oms1-secret --from-env-file "D:\ProjectsDocker\extrawork\.env.k8s.oms1" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms create secret generic oms2-secret `
  --from-literal=SECRET_KEY="$oms2SecretKey" `
  --from-literal=POSTGRES_PASSWORD="$oms2PostgresPassword" `
  --from-literal=DATABASE_URL="postgis://oms2:$oms2PasswordForUrl@oms2-postgres:5432/oms2" `
  --from-literal=SERVICE_CLIENT_SECRET="$oms2ServiceSecret" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms create secret generic oms3-secret `
  --from-literal=SERVICE_CLIENT_SECRET="$oms3ServiceSecret" `
  --from-literal=POSTGRES_PASSWORD="$oms3PostgresPassword" `
  --from-literal=DATABASE_URL="postgresql://oms3:$oms3PasswordForUrl@oms3-postgres:5432/oms3" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms create secret generic oms4-secret `
  --from-literal=SERVICE_CLIENT_SECRET="$oms4ServiceSecret" `
  --from-literal=POSTGRES_PASSWORD="$oms4PostgresPassword" `
  --from-literal=DATABASE_URL="postgresql://oms4:$oms4PasswordForUrl@oms4-postgres:5432/oms4" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n oms create secret generic oms5-secret `
  --from-literal=SERVICE_CLIENT_SECRET="$oms5ServiceSecret" `
  --from-literal=POSTGRES_PASSWORD="$oms5PostgresPassword" `
  --from-literal=DATABASE_URL="postgresql://oms5:$oms5PasswordForUrl@oms5-postgres:5432/oms5" `
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f OMS1/k8s/
kubectl apply -f OMS2/k8s/configmap.yaml -f OMS2/k8s/postgres.yaml -f OMS2/k8s/deployment.yaml -f OMS2/k8s/service.yaml
kubectl apply -f OMS3/k8s/
kubectl apply -f OMS4/k8s/configmap.yaml -f OMS4/k8s/postgres.yaml -f OMS4/k8s/deployment.yaml -f OMS4/k8s/service.yaml
kubectl apply -f OMS5/k8s/
kubectl apply -f platform/k8s/ingress.yaml

kubectl -n oms get pods
kubectl -n oms get svc prometheus kube-state-metrics
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
curl http://prometheus.oms.local/-/ready
curl http://kafka.oms.local
curl http://rabbitmq.oms.local
```
