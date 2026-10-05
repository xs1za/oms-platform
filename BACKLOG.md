# OMS Platform Backlog

- Добавить production-настройки RabbitMQ: persistent storage, credentials через Secret, backup/restore policy и upgrade procedure.
- Добавить мониторинг RabbitMQ queues, retry и DLQ для OMS3/OMS4 workers.
- Добавить Kubernetes manifests для `oms3-report-worker` после реализации команды `report.build` в OMS3.
- Добавить Kubernetes CronJob для запуска auto-close сценария OMS5 в конце 10-го числа месяца после отчетного периода.
- Подготовить отдельные repositories `oms-admin-ui` и `oms-portal-ui` в multi-repo модели.
- Обновить OpenAPI/Postman contracts после стабилизации payload Kafka-событий и новых API сценариев OMS5.
