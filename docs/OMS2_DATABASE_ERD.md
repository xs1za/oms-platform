# OMS2 — ERD сущностей базы данных

Диаграмма отражает прикладные таблицы сервиса OMS2 по Django-моделям и миграции `OMS2/apps/employees/migrations/0001_initial.py`. Стандартные системные таблицы Django (`auth_*`, `django_*`) в диаграмму не включены.

```mermaid
erDiagram
    employees_address {
        bigint id PK
        varchar_1000 full_address
        varchar_32 postal_code
        varchar_250 country
        varchar_250 federal_district
        varchar_250 region
        varchar_250 city
        varchar_250 settlement
        varchar_250 street
        varchar_250 house
        varchar_250 block
        varchar_250 flat
        boolean main_address
        geometry_point_4326 location "nullable"
        integer qc "nullable"
        boolean is_auto
    }

    employees_employeepersinfo {
        bigint id PK
        varchar_50 surname
        varchar_50 firstname
        varchar_50 patronymic
        varchar_250 personnel_number
        varchar_6 gender
        timestamptz created_at "nullable, auto_now_add"
        timestamptz updated_at "nullable, auto_now"
        bigint address_id FK "nullable"
    }

    employees_address o|--o{ employees_employeepersinfo : "address_id (PROTECT)"
```

## Примечания

- `employees_address` соответствует модели `Address`; `employees_employeepersinfo` — модели `Employeepersinfo`.
- `address_id` nullable: сотрудник может не иметь связанного адреса. Один адрес может быть связан с несколькими сотрудниками.
- `location` — PostGIS `PointField` с SRID 4326; поле nullable.
- `personnel_number` не имеет ограничения `UNIQUE` в текущей модели/миграции.
- Модели OMS2 — ORM-модели Django; эта диаграмма одновременно отражает их прикладную ORM-структуру и соответствующие таблицы.
- Схема live-БД не опрашивалась: namespace `oms` сейчас не содержит запущенных ресурсов. Диаграмма построена по исходным моделям и миграции репозитория.
