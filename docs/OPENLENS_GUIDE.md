# OpenLens / Freelens Guide For Kind Cluster

Документ описывает установку и использование OpenLens/Freelens для локального Kubernetes kind-кластера `oms-cluster`.

## Что Использовать

OpenLens как проект больше не развивается активно. На практике для той же задачи можно использовать:

- `OpenLens` - классический open-source Lens build.
- `Freelens` - актуальный community fork, совместимый с kubeconfig и kind.
- `Lens Desktop` - коммерческий Lens с UI и расширениями.

Для локальной разработки с kind достаточно `OpenLens` или `Freelens`.

## Установка Через Chocolatey

Откройте PowerShell от имени администратора.

Проверить Chocolatey:

```powershell
choco --version
```

Установить OpenLens:

```powershell
choco install openlens -y
```

Если пакет `openlens` тянет `freelens`, это нормально: в Chocolatey пакет может использовать community fork как dependency.

Проверить установку:

```powershell
choco list --localonly | findstr /i "openlens freelens lens"
```

Если установка падает с ошибкой lock-файла вида:

```text
Unable to obtain lock file access on C:\ProgramData\chocolatey\lib\...
```

убедитесь, что PowerShell запущен от имени администратора, закройте другие процессы `choco`/`nuget`, затем повторите установку.

Проверить процессы:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'choco|nuget' -or $_.CommandLine -match 'choco|nuget' } |
  Select-Object ProcessId,Name,CommandLine
```

## Установка Без Chocolatey

Если Chocolatey недоступен или нет прав администратора:

1. Откройте страницу релизов OpenLens/Freelens в браузере.
2. Скачайте Windows installer или portable build.
3. Установите приложение в user profile, если installer поддерживает per-user installation.
4. Запустите приложение из Start Menu или из папки установки.

## Подготовить Kind Cluster

Перед запуском OpenLens/Freelens проверьте, что kind-кластер существует и выбран правильный context:

```powershell
kubectl config get-contexts
kubectl config use-context kind-oms-cluster
kubectl get nodes
kubectl -n oms get pods
```

Ожидаемый context:

```text
kind-oms-cluster
```

Kubeconfig обычно находится здесь:

```text
%USERPROFILE%\.kube\config
```

## Подключение К Кластеру В OpenLens/Freelens

1. Запустите OpenLens/Freelens.
2. Откройте раздел `Catalog` или `Clusters`.
3. Нажмите `Add Cluster` или `Browse Kubeconfig`.
4. Выберите kubeconfig:

```text
C:\Users\<user>\.kube\config
```

5. Выберите context:

```text
kind-oms-cluster
```

6. Откройте cluster dashboard.

## Что Смотреть В UI

### Nodes

Проверьте node:

```text
oms-cluster-control-plane
```

Node должен быть `Ready`.

### Namespaces

Основные namespaces:

- `oms`
- `ingress-nginx`
- `kube-system`

### Workloads

В namespace `oms` проверьте deployments:

- `kafka`
- `oms1`
- `oms2`
- `oms2-postgres`
- `oms3`
- `oms4`
- `oms5`

Все должны быть `Ready`.

### Pods

Проверьте pods в namespace `oms`:

- status `Running`;
- restarts не растут;
- readiness/liveness probes успешны.

### Services

Проверьте services:

- `kafka`
- `oms1`
- `oms2`
- `oms2-postgres`
- `oms3`
- `oms4`
- `oms5`

### Ingress

Проверьте ingress:

```text
oms-ingress
```

Host:

```text
oms.local
```

Routes:

- `/oms1`
- `/oms2`
- `/oms3`
- `/oms4`
- `/oms5`

### Persistent Volumes

Проверьте OMS2 Postgres storage:

- PVC: `oms2-postgres-data`
- PV: `oms2-postgres-data-pv`
- Status: `Bound`

Физические данные на host:

```text
D:\ProjectsDocker\extrawork\.runtime\oms2-postgres-data
```

## Частые Действия В UI

### Посмотреть Logs

1. Namespace `oms`.
2. Workloads или Pods.
3. Выберите pod.
4. Откройте tab `Logs`.

CLI-аналог:

```powershell
kubectl -n oms logs deployment/oms1 --tail=100
```

### Exec В Pod

1. Namespace `oms`.
2. Выберите pod.
3. Нажмите `Shell` или `Exec`.

CLI-аналог:

```powershell
kubectl -n oms exec -it deployment/oms3 -- /bin/sh
```

### Перезапустить Deployment

В UI можно удалить pod, Kubernetes создаст новый. Безопаснее через CLI:

```powershell
kubectl -n oms rollout restart deployment/oms3
kubectl -n oms rollout status deployment/oms3
```

### Port Forward

В UI можно открыть port-forward у service/pod, если build поддерживает эту функцию.

CLI-аналог:

```powershell
kubectl -n oms port-forward service/oms1 8001:80
```

После этого встроенный Swagger OMS1 доступен по адресу:

```text
http://localhost:8001/docs
```

## Проверка Снаружи После Изменений

```powershell
curl http://oms.local/oms1/health
curl http://oms.local/oms2/health/
curl http://oms.local/oms3/health/ready
curl http://oms.local/oms4/health/ready
curl http://oms.local/oms5/health/ready
```

## Важное Ограничение

OpenLens/Freelens использует ваш текущий kubeconfig. Если кластер был пересоздан, перезапустите приложение или обновите cluster connection, чтобы UI перечитал kubeconfig.
