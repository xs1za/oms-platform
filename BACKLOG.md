# OMS Platform Backlog

- Добавить production-настройки RabbitMQ: persistent storage, credentials через Secret, backup/restore policy и upgrade procedure.
- Добавить мониторинг RabbitMQ queues, retry и DLQ для OMS3/OMS4 workers.
- Добавить Kubernetes manifests для oms3-report-worker после реализации RabbitMQ-команды report.build в OMS3.
- Добавить Kubernetes CronJob для OMS5 auto-close после отчетного периода.
- Подготовить отдельные repositories oms-admin-ui и oms-portal-ui.
