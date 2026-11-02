# OMS5 — ERD сущностей базы данных

Диаграмма отражает таблицы, создаваемые SQL-миграцией `OMS5/app/migrations/001_create_operational_state.sql`. OMS5 не использует ORM для хранения данных: доступ к PostgreSQL реализован SQL-запросами в `OMS5/app/storage.py`. Pydantic-модели в `OMS5/app/main.py` описывают API payloads и не являются ORM-сущностями.

```mermaid
erDiagram
    schema_migrations {
        varchar_100 version PK
        timestamptz applied_at
    }

    clients {
        varchar_36 id PK
        varchar_255 name
        varchar_255 external_id "nullable"
        timestamptz created_at
    }

    performers {
        varchar_36 id PK
        bigint employee_id UK
        varchar_255 display_name
        varchar_255 email "nullable"
        varchar_100 phone "nullable"
        varchar_50 status
        bigint source_version "nullable"
        timestamptz synced_at
    }

    shifts {
        varchar_36 id PK
        varchar_36 client_id FK
        timestamptz starts_at
        timestamptz ends_at
        varchar_255 location "nullable"
        integer required_performers_count "default 1, CHECK = 1"
        varchar_255 created_by_user_id "nullable, no FK"
        varchar_30 status
        varchar_36 assigned_performer_id FK "nullable"
        varchar_50 close_reason "nullable"
        varchar_100 failure_reason "nullable"
        boolean auto_closed
        varchar_100 auto_close_reason "nullable"
        timestamptz created_at
        timestamptz updated_at
    }

    shift_status_history {
        varchar_36 id PK
        varchar_36 shift_id FK
        varchar_30 from_status
        varchar_30 to_status
        varchar_100 transition_code
        varchar_255 reason "nullable"
        varchar_255 actor_user_id "nullable, no FK"
        timestamptz occurred_at
        varchar_36 correlation_id UK
        jsonb metadata
    }

    offer_campaigns {
        varchar_36 id PK
        varchar_36 shift_id FK
        varchar_30 status
        varchar_255 created_by_user_id "nullable, no FK"
        timestamptz created_at
    }

    shift_offers {
        varchar_36 id PK
        varchar_36 campaign_id FK
        varchar_36 shift_id FK
        varchar_36 performer_id FK
        varchar_30 status
        varchar_64 token_hash UK
        timestamptz expires_at
        timestamptz sent_at
        timestamptz responded_at "nullable"
    }

    shift_offer_views {
        varchar_36 id PK
        varchar_36 offer_id FK
        timestamptz viewed_at
        varchar_255 ip_address "nullable"
        varchar_1000 user_agent "nullable"
        varchar_36 correlation_id UK
    }

    shift_assignments {
        varchar_36 id PK
        varchar_36 shift_id FK
        varchar_36 performer_id FK
        varchar_36 offer_id FK "UNIQUE"
        varchar_30 status
        timestamptz assigned_at
        timestamptz removed_at "nullable"
        varchar_255 reason "nullable"
    }

    timesheets {
        varchar_36 id PK
        varchar_36 performer_id FK
        varchar_36 shift_id FK
        date work_date
        double hours "CHECK > 0 and <= 24"
        varchar_30 status
        timestamptz created_at
    }

    clients ||--o{ shifts : "client_id"
    performers o|--o{ shifts : "assigned_performer_id"
    shifts ||--o{ shift_status_history : "shift_id"
    shifts ||--o{ offer_campaigns : "shift_id"
    offer_campaigns ||--o{ shift_offers : "campaign_id"
    shifts ||--o{ shift_offers : "shift_id"
    performers ||--o{ shift_offers : "performer_id"
    shift_offers ||--o{ shift_offer_views : "offer_id"
    shifts ||--o{ shift_assignments : "shift_id"
    performers ||--o{ shift_assignments : "performer_id"
    shift_offers ||--o| shift_assignments : "offer_id (UNIQUE)"
    shifts ||--o{ timesheets : "shift_id"
    performers ||--o{ timesheets : "performer_id"
```

## Ограничения и примечания

- `schema_migrations` хранит версию примененной SQL-миграции; бизнес-связей с остальными таблицами нет.
- Для `shifts` действует `CHECK (ends_at > starts_at)` и `CHECK (required_performers_count = 1)`.
- Для `shift_offers` задана уникальность `(campaign_id, performer_id)`; `token_hash` уникален.
- Для `shift_assignments.offer_id` задана уникальность. Дополнительно существует частичный уникальный индекс: одновременно может быть только одно назначение со статусом `assigned` на одну смену.
- Для `timesheets` задана уникальность `(performer_id, shift_id, work_date)`.
- Для `shift_status_history.correlation_id` и `shift_offer_views.correlation_id` заданы уникальные ограничения.
- `created_by_user_id` и `actor_user_id` — идентификаторы пользователей, хранящиеся без внешнего ключа на БД OMS1.
- Внешний ключ `performers.employee_id` на таблицу сотрудников OMS2 отсутствует: это идентификатор источника, а не межбазовая FK-связь.
- В миграции не объявлены ENUM-типы для статусов; они представлены строковыми колонками и ограничиваются логикой приложения.
- Схема live-БД не опрашивалась: namespace `oms` сейчас не содержит запущенных ресурсов. Диаграмма построена по SQL-миграции репозитория.
