# Problem Event Workers Production Runbook

## Назначение

Инструкция описывает публикацию problem event workers `OMS3` и `OMS4` на production после успешной проверки на тестовом стенде.

Workers обрабатывают RabbitMQ queues `problem-events.reprocess` и `problem-events.reprocess.manual` для повторной обработки Kafka problem events.

## Предусловия

- Тестовый стенд прошел `OMS5-INT-0002_QA_problem_events_retry_pending_dlq.md` TC-04+.
- Production release согласован.
- Production namespace выбран и известен команде релиза.
- Production `oms3-config`, `oms4-config`, `oms3-secret` при необходимости и `oms4-secret` существуют.
- ConfigMaps/Secrets содержат production значения `RABBITMQ_URL` и `PROBLEM_EVENTS_*`, без test-only endpoints.
- ConfigMaps содержат `PROBLEM_EVENTS_STORE_PATH=/data/problem-events/<service>-problem-events.json` или согласованный production path.
- Production cluster предоставляет shared persistent storage для `problem_events`. Для manifest template используется PVC `ReadWriteMany`; если production storage class не поддерживает RWX, нужно заменить его на согласованный shared storage mechanism до rollout.
- Production images `oms3` и `oms4` содержат `app.problem_event_worker`.

## Rollout

1. Выбрать production context.

```powershell
kubectl config current-context
kubectl config use-context <production-context>
```

2. Проверить namespace и конфигурацию.

```powershell
kubectl -n <prod-namespace> get configmap oms3-config oms4-config
kubectl -n <prod-namespace> get secret oms4-secret
kubectl -n <prod-namespace> get secret oms3-secret
```

Если `oms3-secret` не используется в production, secret может отсутствовать: deployment template помечает его как optional.

3. Проверить production RabbitMQ перед rollout.

```powershell
kubectl -n <prod-namespace> exec deploy/<rabbitmq-deploy> -- rabbitmqctl list_queues name messages arguments
```

4. Применить production manifest.

```powershell
kubectl apply -f platform/k8s/production/problem-event-workers.yaml -n <prod-namespace>
```

Если production namespace отличается от `oms`, используйте стандартный overlay/CI substitution, принятый в platform deployment process.

5. Дождаться rollout.

```powershell
kubectl -n <prod-namespace> rollout status deployment/oms3-problem-event-worker
kubectl -n <prod-namespace> rollout status deployment/oms4-problem-event-worker
```

## Production Smoke-Check

На production не публиковать искусственные Kafka-события без отдельного согласования.

Проверить workloads:

```powershell
kubectl -n <prod-namespace> get deploy,pods | Select-String "problem|worker|oms3|oms4|rabbit"
```

Проверить логи подключения к RabbitMQ:

```powershell
kubectl -n <prod-namespace> logs deploy/oms3-problem-event-worker --since=10m
kubectl -n <prod-namespace> logs deploy/oms4-problem-event-worker --since=10m
```

Проверить RabbitMQ topology:

```powershell
kubectl -n <prod-namespace> exec deploy/<rabbitmq-deploy> -- rabbitmqctl list_queues name messages arguments
```

Ожидаемые queues:

- `problem-events.retry.5m`
- `problem-events.retry.15m`
- `problem-events.retry.1h`
- `problem-events.reprocess`
- `problem-events.reprocess.manual`

Ожидаемые TTL/DLX для retry queues:

| Queue | x-message-ttl | x-dead-letter-exchange | x-dead-letter-routing-key |
| --- | ---: | --- | --- |
| `problem-events.retry.5m` | `300000` | `problem-events.reprocess.exchange` | `problem-events.reprocess` |
| `problem-events.retry.15m` | `900000` | `problem-events.reprocess.exchange` | `problem-events.reprocess` |
| `problem-events.retry.1h` | `3600000` | `problem-events.reprocess.exchange` | `problem-events.reprocess` |

## Rollback

Если workers создают ошибки подключения или некорректно обрабатывают reprocess:

```powershell
kubectl -n <prod-namespace> rollout undo deployment/oms3-problem-event-worker
kubectl -n <prod-namespace> rollout undo deployment/oms4-problem-event-worker
```

Если предыдущей revision нет и нужно временно остановить workers:

```powershell
kubectl -n <prod-namespace> scale deployment/oms3-problem-event-worker --replicas=0
kubectl -n <prod-namespace> scale deployment/oms4-problem-event-worker --replicas=0
```

После rollback проверить:

```powershell
kubectl -n <prod-namespace> get deploy,pods | Select-String "problem|worker"
kubectl -n <prod-namespace> logs deploy/oms3-problem-event-worker --since=10m
kubectl -n <prod-namespace> logs deploy/oms4-problem-event-worker --since=10m
```
