# [OMS5-INT-0003] QA: подготовка и выполнение импорта смен из отчёта

## Проверяемое требование

Инструкция покрывает приёмочную проверку импорта тестовых данных для смен ноябрь 2026:

- 5 сотрудников с доступом в админку (не исполнители);
- 20 исполнителей, для которых создаются 20 Employee с номерами `QA-EMP-006...025` и связанные профили `QA-PERF-001...020`;
- 10 городов РФ и 6 городов РБ с реальными адресами и координатами WGS84;
- 3 уровня оргструктуры клиента: головной клиент → дивизион → магазин;
- смены с 01.11.2026 по 30.11.2026 длительностью 9 часов, начало в 08:00 по местному времени города;
- по 2 смены в каждом городе РФ и по 1 смене в каждом городе РБ за день;
- импорт из mock-отчёта `report_shifts.csv`, повторный запуск не создаёт дубликатов.

## Состав поставки

| Артефакт | Путь | Назначение |
| --- | --- | --- |
| Генератор и импортёр | `platform/docs/qa/generate_and_import.py` | Генерирует отчёт и пишет данные в OMS1, OMS2, OMS5 |
| Mock-отчёт | `platform/docs/qa/report_shifts.csv` | Входной файл импорта, 780 строк за ноябрь 2026 |
| Состояние импорта | `/tmp/import_state.json` в поде, при необходимости копируется в `platform/docs/qa/import_state.json` | Соответствие `personnel_number` → `person_id`, счётчики прогона |

## Предусловия

Кластер Kind `oms-cluster`, namespace `oms`. Подняты `oms1`, `oms2`, `oms5` с базами, Kafka и топики `people.access.v1`, `people.performer.v1`.

```powershell
kubectl -n oms get pods | Select-String "oms1|oms2|oms5|kafka"
```

Базы могут содержать данные предыдущих прогонов, демонстраций и smoke-проверок. Импорт ничего не удаляет и не перезаписывает: он дополняет базу, а существующие клиенты, смены, кампании и назначения остаются без изменений. Поэтому проверки ниже считают только QA-данные по префиксам `QA-*` и `qa.operator.*`, а не общее число строк.

Импорт пишет напрямую в PostgreSQL, поэтому нужен доступ к портам баз. Ingress его не даёт.

### Доступ к базам и ingress

`platform/k8s/ingress.yaml` маршрутизирует только HTTP: пути `/oms1`…`/oms5` на сервисы `oms1`…`oms5` (порт 80), плюс Prometheus, AKHQ и RabbitMQ UI. Сервисы `oms*-postgres` — `ClusterIP` с портом 5432, TCP-маршрутов для них в ingress нет, контроллер запущен без `--tcp-services-configmap`. Публиковать PostgreSQL через ingress не нужно и не следует.

Отсюда два варианта запуска:

- **Вариант A, в кластере**: скрипт выполняется внутри пода `oms2`, базы доступны по DNS `oms2-postgres:5432` и `oms5-postgres:5432`. Port-forward не нужен.
- **Вариант B, с хоста**: нужен `kubectl port-forward` до каждой базы.

Для варианта B:

```powershell
kubectl -n oms port-forward deploy/oms2-postgres 5432:5432
kubectl -n oms port-forward deploy/oms5-postgres 5434:5432
kubectl -n oms port-forward deploy/oms1-postgres 5433:5432
```

Каждая команда занимает отдельное окно терминала. Пароли баз берутся из секретов:

```powershell
kubectl -n oms get secret oms2-secret -o jsonpath='{.data.POSTGRES_PASSWORD}' | % { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }
kubectl -n oms get secret oms5-secret -o jsonpath='{.data.POSTGRES_PASSWORD}' | % { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }
kubectl -n oms get secret oms1-secret -o jsonpath='{.data.POSTGRES_PASSWORD}' | % { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }
```

Переменные окружения:

| Переменная | Обязательность | Значение для варианта B (хост) | Значение для варианта A (в кластере) |
| --- | --- | --- | --- |
| `OMS5_DATABASE_URL` | для OMS5 | `postgresql://oms5:<oms5-pass>@127.0.0.1:5434/oms5` | `postgresql://oms5:<oms5-pass>@oms5-postgres:5432/oms5` |
| `OMS2_DATABASE_URL` | для OMS2 | `postgis://oms2:<oms2-pass>@127.0.0.1:5432/oms2` | берётся из `$DATABASE_URL` пода |
| `OMS1_DATABASE_URL` | для OMS1 | `postgresql://oms1:<oms1-pass>@127.0.0.1:5433/oms1` | `postgresql://oms1:<oms1-pass>@oms1-postgres:5432/oms1` |
| `OMS2_PROJECT_DIR` | для OMS2 | `D:\ProjectsDocker\extrawork\OMS2` | `/app` |
| `PERSON_DATA_ENCRYPTION_KEY` | для OMS2 | значение из `oms2-secret` | берётся из env пода автоматически |
| `PERSON_IDENTIFIER_HMAC_KEY` | для OMS2 | значение из `oms2-secret` | берётся из env пода автоматически |
| `QA_OPERATOR_PASSWORD` | нет | любой пароль, по умолчанию `QaOperator!2026` | то же |

Куда именно вписывать значения:

| Способ запуска | Где задаются переменные |
| --- | --- |
| Вариант B, `docker run` | флагами `-e ИМЯ="значение"` в команде `docker run` |
| Вариант A, `kubectl exec` | аргументами `env ИМЯ="значение"` после `--`; в примерах используется `QA_OMS5_DSN`, потому что `OMS5_DATABASE_URL` собирается внутри `sh -c` |
| Генерация отчёта на хосте | не требуются вообще, скрипт не обращается к БД |

`$env:ИМЯ="значение"` в PowerShell действует только в текущем окне и не переживает его закрытие. Для постоянного хранения есть `setx`, но для QA-прогона это лишнее: проще держать значения в блокноте и вставлять в команду. Если переменная задана в одном окне, а команда выполняется в другом, скрипт её не увидит.

Как получить пароли и ключи:

```powershell
kubectl -n oms get secret oms2-secret -o jsonpath='{.data.POSTGRES_PASSWORD}'          | % { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }
kubectl -n oms get secret oms5-secret -o jsonpath='{.data.POSTGRES_PASSWORD}'          | % { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }
kubectl -n oms get secret oms1-secret -o jsonpath='{.data.POSTGRES_PASSWORD}'          | % { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }
kubectl -n oms get secret oms2-secret -o jsonpath='{.data.PERSON_DATA_ENCRYPTION_KEY}'  | % { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }
kubectl -n oms get secret oms2-secret -o jsonpath='{.data.PERSON_IDENTIFIER_HMAC_KEY}'  | % { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }
```

Порты в DSN варианта B — это локальные порты из `kubectl port-forward`, а не порты сервисов в кластере: OMS2 слушает `5432`, OMS5 `5434`, OMS1 `5433` на `127.0.0.1`. Внутри кластера у всех баз порт `5432`, отличаются только имена хостов.

Импорт OMS2 использует Django ORM и требует библиотек GDAL/GEOS, которых нет на Windows-хосте. Шаги OMS2 и OMS5 выполняются внутри образа `oms2`, шаг OMS1 — внутри образа `oms1`, где есть `bcrypt`.

## Подключение из DBeaver или pgAdmin

Для ручных выборок и проверки SQL удобнее GUI. Ingress базы не публикует, поэтому подключение идёт через те же port-forward, что и вариант B:

```powershell
kubectl -n oms port-forward deploy/oms2-postgres 5432:5432
kubectl -n oms port-forward deploy/oms5-postgres 5434:5432
kubectl -n oms port-forward deploy/oms1-postgres 5433:5432
```

Параметры подключения:

| База | Host | Port | Database | User | Password | SSL |
| --- | --- | --- | --- | --- | --- | --- |
| OMS1 | `127.0.0.1` | `5433` | `oms1` | `oms1` | `POSTGRES_PASSWORD` из `oms1-secret` | off |
| OMS2 | `127.0.0.1` | `5432` | `oms2` | `oms2` | `POSTGRES_PASSWORD` из `oms2-secret` | off |
| OMS5 | `127.0.0.1` | `5434` | `oms5` | `oms5` | `POSTGRES_PASSWORD` из `oms5-secret` | off |

DBeaver:

1. Database → New Database Connection → PostgreSQL.
2. В Host указать `127.0.0.1`, в Port — локальный порт из таблицы, в Database — имя базы, в Username/Password — значения из секрета.
3. На вкладке SSL снять «Use SSL», иначе соединение может упасть на самоподписанном сертификате.
4. Test Connection. Если драйвер не установлен, DBeaver предложит скачать его.
5. SQL Editor → вставить запросы из шагов 5 и 6 → Execute. Схема `public`.

pgAdmin:

1. Object → Register → Server.
2. General: произвольное имя, например `oms5-qa`.
3. Connection: Host `127.0.0.1`, Port `5434`, Maintenance database `oms5`, Username `oms5`, Password из секрета.
4. Parameters: SSL mode `disable`.
5. Query Tool → выполнить SQL из инструкции.

Ограничения:

- Окно с `port-forward` должно оставаться открытым. При закрытии окна соединение в GUI обрывается, а не «подвисает».
- В GUI выполняйте только `SELECT`. Изменение схемы и данных делает приложение и импортёр, ручные `UPDATE`/`DELETE` на QA-стенде легко ломают идемпотентность и счётчики.
- Импорт и GUI можно использовать одновременно: скрипт работает через отдельное соединение.
- Если port-forward не поднимается, быстрый вариант без GUI — `kubectl -n oms exec deploy/oms5-postgres -- psql -U oms5 -d oms5 -c "..."`, как в шагах 5 и 6.


## Формат отчёта

Файл содержит 19 колонок:

```text
shift_key,shift_id,head_external_id,head_name,division_external_id,division_name,
store_external_id,store_name,city,country_code,timezone,address,lon,lat,
starts_at_local,starts_at_utc,ends_at_utc,employee_personnel_number,performer_external_id
```

`starts_at_local` — местное время города, `starts_at_utc`/`ends_at_utc` — UTC с суффиксом `Z`. `shift_id` — UUIDv5 от `shift_key`, `shift_key` — `shift.v1|<store_external_id>|<starts_at_utc>`.

## Бизнес-ключи

| Сущность | Ключ | Пример |
| --- | --- | --- |
| Employee (оператор) | `personnel_number` | `QA-EMP-001` … `QA-EMP-005` |
| Employee (исполнитель) | `personnel_number` | `QA-EMP-006` … `QA-EMP-025` |
| Performer | `QA-PERF-*` в отчёте состояния | `QA-PERF-001` … `QA-PERF-020` |
| Головной клиент | `clients.external_id` | `QA-CLI-RF-01` … `QA-CLI-RF-10`, `QA-CLI-BY-01` |
| Дивизион | `clients.external_id` | `QA-DIV-RF-01-1` … `QA-DIV-RF-01-3` |
| Магазин | `clients.external_id` | `QA-STORE-RF-01-01`, `QA-STORE-RF-01-02` |
| Смена | UUIDv5, ограничение `(client_id, starts_at)` | `317784c8-…` |

В БД OMS2 добавлено ограничение уникальности `employment_episode.personnel_number`, в OMS5 — уникальные индексы `clients.external_id` и `shifts(client_id, starts_at)`.

## Шаг 1. Генерация отчёта

Генерация не требует БД и выполняется на хосте. Период обязателен: `--from` и `--to` в формате `YYYY-MM-DD`, значения по умолчанию отсутствуют.

```powershell
cd D:\ProjectsDocker\extrawork\platform\docs\qa
python generate_and_import.py --generate-only --from 2026-11-01 --to 2026-11-30
```

Другой период задаётся теми же параметрами, например декабрь:

```powershell
python generate_and_import.py --generate-only --from 2026-12-01 --to 2026-12-31 --report report_shifts_december.csv
```

Ожидаемый вывод:

```text
[1/3] Отчёт сгенерирован: ...\report_shifts.csv (строк: 780, период 2026-11-01..2026-11-30)
[2/3] Отчёт проверен: 780 смен (2026-11-01..2026-11-30), дублей нет
```

Количество строк всегда равно `дни × 26`: 26 смен в день (20 в городах РФ и 6 в городах РБ). Для ноября это 780, для декабря 806.

Генератор не использует `random` без seed: повторный запуск даёт побайтово тот же файл. Проверка:

```powershell
Get-FileHash .\report_shifts.csv -Algorithm SHA256
python generate_and_import.py --generate-only --from 2026-11-01 --to 2026-11-30
Get-FileHash .\report_shifts.csv -Algorithm SHA256
```

Хеши совпадают.

## Шаг 2. Валидация отчёта до импорта

```powershell
$rows = Import-Csv .\report_shifts.csv

"Строк: $($rows.Count)"                                                              # 780 для ноября
"Уникальных ключей: $(($rows.shift_key | Sort-Object -Unique).Count)"                 # равно числу строк
"Магазинов: $(($rows.store_external_id | Sort-Object -Unique).Count)"                 # 26
"Городов: $(($rows.city | Sort-Object -Unique).Count)"                                # 16
"Смен РФ: $(($rows | ? country_code -eq 'RU').Count)"                                 # 600 для ноября
"Смен РБ: $(($rows | ? country_code -eq 'BY').Count)"                                 # 180 для ноября
```

Длительность и период:

```powershell
$durations = $rows | ForEach-Object { ([datetime]$_.ends_at_utc) - ([datetime]$_.starts_at_utc) }
$durations | Sort-Object -Unique                                                       # 09:00:00

$rows | Where-Object {
    ([datetime]$_.starts_at_utc) -lt [datetime]'2026-11-01' -or
    ([datetime]$_.starts_at_utc) -ge [datetime]'2026-12-01'
}                                                                                       # пусто
```

Распределение по городам:

```powershell
$rows | Group-Object city | Select-Object Name, Count
```

30 строк на каждый город РФ и 30 на каждый город РБ за 30-дневный месяц: 60 и 30 соответственно (2 смены и 1 смена в день).

Соответствие местного времени и UTC:

| Город | Смещение | `starts_at_utc` | `ends_at_utc` |
| --- | --- | --- | --- |
| Калининград | UTC+2 | `06:00:00Z` | `15:00:00Z` |
| Москва, Санкт-Петербург, Казань, Волгоград | UTC+3 | `05:00:00Z` | `14:00:00Z` |
| Самара | UTC+4 | `04:00:00Z` | `13:00:00Z` |
| Екатеринбург, Челябинск | UTC+5 | `03:00:00Z` | `12:00:00Z` |
| Омск | UTC+6 | `02:00:00Z` | `11:00:00Z` |
| Новосибирск | UTC+7 | `01:00:00Z` | `10:00:00Z` |
| Минск, Брест, Витебск, Гродно, Гомель, Могилёв | UTC+3 | `05:00:00Z` | `14:00:00Z` |

Проверка координат: для РФ широта 41–82, долгота 19–180; для РБ широта 51–56, долгота 23–33. Адрес магазина непустой у всех 26 магазинов.

## Шаг 3. Код запуска импорта OMS5 и OMS2

### Вариант A. В кластере, без port-forward

Скрипт передаётся в под через stdin, файлы отчёта и состояния остаются в `/tmp` пода. DSN OMS2 берётся из переменной окружения пода, DSN OMS5 собирается из секрета.

```powershell
cd D:\ProjectsDocker\extrawork\platform\docs\qa

$oms5Pass = kubectl -n oms get secret oms5-secret -o jsonpath='{.data.POSTGRES_PASSWORD}' | % { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }
$oms5Dsn  = "postgresql://oms5:$oms5Pass@oms5-postgres:5432/oms5"
$pod      = kubectl -n oms get pod -l app=oms2 -o jsonpath='{.items[0].metadata.name}'

Get-Content -Raw .\generate_and_import.py |
  kubectl -n oms exec -i $pod -- env "QA_OMS5_DSN=$oms5Dsn" sh -c 'OMS2_DATABASE_URL="$DATABASE_URL" OMS5_DATABASE_URL="$QA_OMS5_DSN" OMS2_PROJECT_DIR=/app python - --from 2026-11-01 --to 2026-11-30 --report /tmp/report_shifts.csv --state /tmp/import_state.json'
```

Проверка доступа к базам из пода без port-forward. Переменная `$pod` должна быть задана в этом же окне; если она пустая, `kubectl` отвечает `pod, type/name or --filename must be specified`.

```powershell
$pod = kubectl -n oms get pod -l app=oms2 -o jsonpath='{.items[0].metadata.name}'
$oms5Pass = kubectl -n oms get secret oms5-secret -o jsonpath='{.data.POSTGRES_PASSWORD}' | % { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }

kubectl -n oms exec $pod -- python -c "import psycopg; print(psycopg.connect('postgresql://oms5:$oms5Pass@oms5-postgres:5432/oms5').execute('select count(*) from clients').fetchone())"
```

Если нужно забрать файл состояния на хост:

```powershell
$pod = kubectl -n oms get pod -l app=oms2 -o jsonpath='{.items[0].metadata.name}'
$target = "D:\ProjectsDocker\extrawork\platform\docs\qa\import_state.json"

kubectl -n oms exec $pod -- test -f /tmp/import_state.json
if ($LASTEXITCODE -ne 0) {
    Write-Error "В поде нет /tmp/import_state.json. Выполните шаг 3 в этом же поде: состояние создаётся импортом."
} else {
    $state = kubectl -n oms exec $pod -- cat /tmp/import_state.json
    $state | Set-Content $target -Encoding utf8
    Get-Item $target | Select-Object FullName, Length
}
```

Почему нужна проверка: если `cat` не находит файл, он пишет ошибку в stderr и ничего не отдаёт в stdout. Пустой конвейер PowerShell не запускает `Set-Content`, поэтому команда завершается без ошибки, но файл на хосте не появляется. Именно так выглядит попытка копирования до выполнения импорта.

Файл создаётся по указанному пути, при работе по этой инструкции — `D:\ProjectsDocker\extrawork\platform\docs\qa\import_state.json`, рядом со скриптом и отчётом. `kubectl exec ... cat` только печатает содержимое в stdout, в поде ничего не копируется.

`/tmp` живёт столько же, сколько под: после рестарта или rollout файл исчезает. Это не блокер — состояние восстанавливается повторным запуском шага 3, импорт идемпотентен и создаст файл заново. Скрипт читает состояние в кодировке `utf-8-sig`, поэтому BOM от PowerShell 5.1 не ломает повторный запуск.

### Вариант B. С хоста через port-forward

Требует трёх port-forward из раздела «Доступ к базам и ingress».

```powershell
cd D:\ProjectsDocker\extrawork\platform\docs\qa

docker run --rm --network host `
  -e OMS2_DATABASE_URL="postgis://oms2:<oms2-password>@127.0.0.1:5432/oms2" `
  -e OMS5_DATABASE_URL="postgresql://oms5:<oms5-password>@127.0.0.1:5434/oms5" `
  -e OMS2_PROJECT_DIR="/app" `
  -e PERSON_DATA_ENCRYPTION_KEY="<fernet-key>" `
  -e PERSON_IDENTIFIER_HMAC_KEY="<hmac-key>" `
  -v "${PWD}:/qa" -w /qa --entrypoint python oms2:latest generate_and_import.py --from 2026-11-01 --to 2026-11-30
```

Ключи `PERSON_DATA_*` берутся из `oms2-secret`. Ожидаемый вывод первого прогона в обоих вариантах (для пустой базы; на непустой добавятся только новые QA-строки):

```text
[1/3] Отчёт сгенерирован: /qa/report_shifts.csv (строк: 780, период 2026-11-01..2026-11-30)
[2/3] Отчёт проверен: 780 смен (2026-11-01..2026-11-30), дублей нет
[3/3] Импорт завершён
  oms5: clients_created=70, shifts_created=780, shifts_skipped=0
  oms2: employees_created=25, employees_skipped=0, performers_created=20
```

70 клиентов: 11 головных, 33 дивизиона, 26 магазинов. В шаге OMS2 создаются 45 событий outbox: 25 `people.employment.changed` и 20 `people.performer_profile.changed`, которые затем публикует `oms2-outbox-worker`.

### Импорт дополнительного периода

Скрипт принимает `--from` и `--to`, поэтому база пополняется сменами нового месяца без удаления прежних данных. Сначала генерируется отчёт за декабрь:

```powershell
python generate_and_import.py --generate-only --from 2026-12-01 --to 2026-12-31 --report report_shifts_december.csv
```

Ожидается 806 строк: 31 день × 26 смен. Затем отчёт импортируется тем же способом, что и ноябрьский, но с явным указанием файла. В варианте A файл сначала копируется в под:

```powershell
$oms5Pass = kubectl -n oms get secret oms5-secret -o jsonpath='{.data.POSTGRES_PASSWORD}' | % { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }
$oms5Dsn  = "postgresql://oms5:$oms5Pass@oms5-postgres:5432/oms5"
$pod      = kubectl -n oms get pod -l app=oms2 -o jsonpath='{.items[0].metadata.name}'

Get-Content -Raw .\report_shifts_december.csv | kubectl -n oms exec -i $pod -- sh -c 'cat > /tmp/report_shifts_december.csv'
Get-Content -Raw .\generate_and_import.py | kubectl -n oms exec -i $pod -- env "QA_OMS5_DSN=$oms5Dsn" sh -c 'OMS2_DATABASE_URL="$DATABASE_URL" OMS5_DATABASE_URL="$QA_OMS5_DSN" OMS2_PROJECT_DIR=/app python - --import-only --from 2026-12-01 --to 2026-12-31 --report /tmp/report_shifts_december.csv --state /tmp/import_state.json'
```

Для варианта B файл уже доступен через volume:

```powershell
docker run --rm --network host `
  -e OMS5_DATABASE_URL="postgresql://oms5:<oms5-password>@127.0.0.1:5434/oms5" `
  -v "${PWD}:/qa" -w /qa --entrypoint python oms2:latest generate_and_import.py --import-only --from 2026-12-01 --to 2026-12-31 --report /qa/report_shifts_december.csv
```

Ожидаемый вывод:

```text
[2/3] Отчёт проверен: 806 смен (2026-12-01..2026-12-31), дублей нет
[3/3] Импорт завершён
  oms5: clients_created=0, shifts_created=806, shifts_skipped=0
```

Итог в базе после ноября и декабря: 1586 QA-смен, клиенты и магазины не дублируются, кампании и назначения прежних смен не меняются. Повторный импорт декабрьского файла даёт `shifts_created=0, shifts_skipped=806`.

## Шаг 4. Импорт доступа операторов в OMS1

Выполняется в образе `oms1`, потому что для bcrypt нужен модуль из этого образа.

### Вариант A. В кластере

У подов `oms1` и `oms2` разные `/tmp`: отчёт и состояние, созданные шагом 3, в поде `oms1` не видны. Переносится только файл состояния, он содержит соответствие `personnel_number` → `person_id`. Отчёт для шага OMS1 не нужен.

```powershell
cd D:\ProjectsDocker\extrawork\platform\docs\qa

$oms1Pass = kubectl -n oms get secret oms1-secret -o jsonpath='{.data.POSTGRES_PASSWORD}' | % { [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }
$oms1Dsn  = "postgresql://oms1:$oms1Pass@oms1-postgres:5432/oms1"
$oms1Pod  = kubectl -n oms get pod -l app=oms1 -o jsonpath='{.items[0].metadata.name}'
$oms2Pod  = kubectl -n oms get pod -l app=oms2 -o jsonpath='{.items[0].metadata.name}'

kubectl -n oms exec $oms2Pod -- cat /tmp/import_state.json |
  kubectl -n oms exec -i $oms1Pod -- sh -c 'cat > /tmp/import_state.json'

Get-Content -Raw .\generate_and_import.py |
  kubectl -n oms exec -i $oms1Pod -- env "OMS1_DATABASE_URL=$oms1Dsn" python - --import-only --from 2026-11-01 --to 2026-11-30 --state /tmp/import_state.json
```

Если файла состояния в `oms2` уже нет (под перезапускался), сначала повторите шаг 3: он идемпотентен и создаст файл заново.

### Вариант B. С хоста

```powershell
docker run --rm --network host `
  -e OMS1_DATABASE_URL="postgresql://oms1:<oms1-password>@127.0.0.1:5433/oms1" `
  -v "${PWD}:/qa" -w /qa --entrypoint python oms1:latest generate_and_import.py --import-only --from 2026-11-01 --to 2026-11-30
```

Ожидаемый вывод:

```text
[2/3] Отчёт не требуется: импортируется только доступ OMS1
[3/3] OMS5 пропущен: не задан OMS5_DATABASE_URL
[3/3] OMS2 пропущен: не задан OMS2_DATABASE_URL
[3/3] Импорт завершён
  oms1: users_created=5, assignments_created=5, password=QaOperator!2026
```

Создаются учётные записи `qa.operator.1...5` с ролью `administrator` и `person_id` из состояния импорта. Пароль задаётся переменной `QA_OPERATOR_PASSWORD` и печатается в консоли; для общих стендов его нужно менять.

## Шаг 5. Проверки OMS5

```powershell
kubectl -n oms exec deploy/oms5-postgres -- psql -U oms5 -d oms5 -c "
select client_type_code, count(*) from clients where external_id like 'QA-%' group by 1 order by 1;
select count(*) as qa_shifts, count(distinct s.client_id) as stores
from shifts s join clients c on c.id = s.client_id where c.external_id like 'QA-STORE-%';
select count(*) as dupes from (select client_id, starts_at from shifts group by 1,2 having count(*)>1) d;
select count(*) as bad_duration from shifts s join clients c on c.id = s.client_id
where c.external_id like 'QA-STORE-%' and s.ends_at - s.starts_at <> interval '9 hours';
select count(*) as not_object from shifts s join clients c on c.id = s.client_id
where c.external_id like 'QA-STORE-%' and c.client_type_code <> 'object';"
```

Ожидается: 11 головных, 33 дивизиона, 26 магазинов по префиксу `QA-*`; 780 QA-смен на 26 магазинах; 0 дублей; 0 смен другой длительности; 0 ссылок не на магазин.

Общее число строк в базе при этом больше: к QA-данным добавляются записи предыдущих прогонов и smoke-проверок. Проверки ниже считают только QA-срез, поэтому подходят и для непустой базы.

Кампании и назначения скрипт не создаёт. Проверяется, что для QA-смен их нет:

```sql
select count(*) from offer_campaigns oc
join shifts s on s.id = oc.shift_id
join clients c on c.id = s.client_id
where c.external_id like 'QA-STORE-%';

select count(*) from shift_assignments sa
join shifts s on s.id = sa.shift_id
join clients c on c.id = s.client_id
where c.external_id like 'QA-STORE-%';
```

Оба значения 0. Ранее созданные кампании и назначения на других сменах остаются как были.

Глубина иерархии:

```sql
with recursive tree as (
  select id, parent_client_id, 1 as depth from clients
  where parent_client_id is null and external_id like 'QA-%'
  union all
  select c.id, c.parent_client_id, t.depth + 1
  from clients c join tree t on c.parent_client_id = t.id
)
select max(depth) from tree;
```

Ожидается 3.

Адрес магазина:

```sql
select count(*) filter (where address is null) as no_address,
       count(*) filter (where country_code is null) as no_country,
       count(*) filter (where lon is null or lat is null) as no_coords
from clients where client_type_code = 'object' and external_id like 'QA-STORE-%';
```

Все три значения 0. Дополнительно:

```sql
select country_code, count(*) from clients
where client_type_code = 'object' and external_id like 'QA-STORE-%' group by 1;
```

20 магазинов РФ и 6 магазинов РБ.

## Шаг 6. Проверки OMS2

```powershell
kubectl -n oms exec deploy/oms2-postgres -- psql -U oms2 -d oms2 -c "
select count(*) as employees from employees_employmentepisode where personnel_number like 'QA-EMP-%';
select count(*) as performers from employees_performerprofile pp
join employees_employmentepisode e on e.person_id = pp.person_id
where e.personnel_number like 'QA-EMP-%';
select topic, count(*) from employees_integrationoutbox o
where exists (
  select 1 from employees_employmentepisode e
  where e.personnel_number like 'QA-EMP-%' and e.person_id::text = o.aggregate_id
) group by 1 order by 1;"
```

Ожидается 25 сотрудников, 20 профилей и 45 событий по QA-персонам: 25 в `people.access.v1` и 20 в `people.performer.v1`. События других персон в подсчёт не попадают.

Связь исполнителя с Employee проверяется через активный employment episode персоны:

```sql
select count(*) from employees_performerprofile pp
join employees_employmentepisode e on e.person_id = pp.person_id and e.status = 'active'
where e.personnel_number ~ '^QA-EMP-0(0[6-9]|1[0-9]|2[0-5])$';
```

Ожидается 20.

## Шаг 7. Повторный запуск

Повторить шаги 3 и 4.

Ожидается:

```text
oms5: clients_created=0, shifts_created=0, shifts_skipped=780
oms2: employees_created=0, employees_skipped=25, performers_created=0
oms1: users_created=0, assignments_created=0
```

Количество строк в базах не меняется, новые события в outbox не появляются, хеш `report_shifts.csv` совпадает с первым прогоном.

## Шаг 8. Частичный сбой

1. Запустить шаг 3, прервать выполнение после блока OMS5 (например, закрыть терминал при появлении `oms5:`).
2. Проверить, что QA-смены и клиенты уже записаны, а QA-сотрудники в OMS2 ещё не созданы.
3. Повторить шаг 3.

Ожидается: OMS5 пропускает существующие строки, OMS2 создаёт 25 сотрудников и 20 профилей. Дублей нет, состояние сохраняется в `import_state.json`.

## Тест-кейсы

| ID | Сценарий | Ожидание |
| --- | --- | --- |
| TC-01 | Первый прогон на непустую базу | +70 клиентов и +780 смен, прежние записи не меняются |
| TC-02 | Повторный прогон | все счётчики `created=0`, `shifts_skipped=780` |
| TC-03 | Повторная генерация отчёта | одинаковый SHA256 |
| TC-04 | Смена с `client_id` дивизиона через API | `422 invalid_client_type` |
| TC-05 | Клиент с родителем неподходящего типа | `422 invalid_parent_type` |
| TC-06 | Обрыв после OMS5 | повторный запуск не создаёт дублей |
| TC-07 | Отчёт с дублем `shift_key` | импорт останавливается с ошибкой валидации |
| TC-08 | Отчёт с длительностью не 9 часов | импорт останавливается с ошибкой валидации |
| TC-09 | Вход `qa.operator.1` с паролем из вывода | 200, `/auth/verify` возвращает `person_id` и роль `administrator` |
| TC-10 | Импорт декабря поверх ноября | +806 смен, итого 1586 QA-смен, клиенты не дублируются |
| TC-11 | Повторный импорт декабря | `shifts_created=0`, `shifts_skipped=806` |

## Открытые ограничения

- Адрес магазина хранится в `clients.address`, `country_code`, `timezone`, `lon`, `lat`. Модель `Address` в OMS2 к магазинам не применяется: она относится к Person.
- PostgreSQL не публикуется через ingress: TCP-маршрутов для портов 5432 нет, поэтому для запуска с хоста нужен port-forward.
- Офферы и назначения не создаются, смены остаются в статусе `A00_DRAFT`.
- Пароль операторов печатается в консоли и задаётся общей переменной; для общих стендов нужен отдельный секрет.
- Скрипт не удаляет QA-данные и не «переимпортирует» период: чтобы пересоздать месяц, строки нужно удалить вручную.

## Критерии приёмки

- в OMS5 по префиксу `QA-*` 70 клиентов (11/33/26) и 780 смен за ноябрь 2026;
- для двух месяцев ноябрь + декабрь — 1586 QA-смен без дублей;
- дублей по `(client_id, starts_at)` нет, все QA-смены ссылаются на `object`;
- глубина QA-иерархии 3, у всех QA-магазинов заполнены адрес, страна и координаты;
- каждая смена длится 9 часов, начало соответствует 08:00 местного времени;
- в каждом городе РФ 2 смены в день, в каждом городе РБ 1 смена в день;
- в OMS2 25 сотрудников с номерами `QA-EMP-*`, 20 профилей исполнителей и 45 событий outbox;
- в OMS1 5 операторов с активной ролью `administrator`;
- повторный прогон того же периода не меняет количество записей и хеш отчёта;
- записи, существовавшие до импорта, остаются без изменений.

## Что приложить к отчёту

- Вывод первого и повторного прогона шага 3 и шага 4.
- `SHA256` файла `report_shifts.csv` до и после повторной генерации.
- Результаты SQL-проверок шагов 5 и 6.
- Содержимое `import_state.json` после первого прогона.
- Версии образов `oms1` и `oms2`, commit импортёра.
