"""Генерация mock-отчёта по сменам и импорт QA-данных в OMS1, OMS2 и OMS5.

Период обязателен во всех режимах: `--from` и `--to` принимают дату в формате
YYYY-MM-DD, значения по умолчанию отсутствуют.

    python generate_and_import.py --from 2026-11-01 --to 2026-11-30
    python generate_and_import.py --from 2026-11-01 --to 2026-11-30 --generate-only
    python generate_and_import.py --from 2026-11-01 --to 2026-11-30 --import-only

Импорт создаёт новый QA-набор под актуальную модель:

* OMS1 — 5 операторов (`QA-OPS-001` … `QA-OPS-005`) с периодами найма,
  назначениями на `operator_software` и ролями. Штатный оператор не является
  исполнителем, поэтому `users.person_id=null`. `admin` создаёт seed OMS1;
* OMS2 — 20 исполнителей (`QA-EMP-006` … `QA-EMP-025`, `QA-PERF-001` … `QA-PERF-020`)
  с контактами, паспортами, ИНН, СНИЛС, адресами и периодами работы;
* OMS5 — 70 клиентов и 780 смен ноября 2026. Исполнители в OMS5 не пишутся:
  их создаёт consumer `people.performer.v1` из 20 событий
  `people.performer_profile.changed`, опубликованных outbox worker-ом OMS2.

Переменные окружения для импорта:

    OMS1_DATABASE_URL        DSN PostgreSQL OMS1
    OMS2_DATABASE_URL        DSN PostgreSQL/PostGIS OMS2
    OMS5_DATABASE_URL        DSN PostgreSQL OMS5
    OMS2_PROJECT_DIR         путь к исходникам OMS2 (по умолчанию соседняя папка OMS2)
    QA_OPERATOR_PASSWORD     пароль QA-операторов (по умолчанию QaOperator!2026)
    PERSON_DATA_ENCRYPTION_KEY, PERSON_IDENTIFIER_HMAC_KEY
                             ключи OMS2 из oms2-secret, обязательны для OMS2

Импорт идемпотентен: повторный прогон не создаёт дубликатов и возвращает
`*_created=0`. Состояние (идентификаторы созданных записей) хранится в
state-файле версии 3 и пишется атомарно. Персональные данные, пароли и номера
документов в state-файл не попадают.

OMS2 импортируется в образе `oms2` (Django ORM требует GDAL/GEOS), OMS1 — в
образе `oms1` (нужен bcrypt). OMS5 использует psycopg и работает в обоих
образах. См. `OMS5-INT-0003_QA_shifts_import.md`.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import uuid
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_REPORT = BASE_DIR / "report_shifts.csv"
DEFAULT_STATE = BASE_DIR / "import_state.json"

NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
EMPLOYMENT_START = datetime(2026, 10, 1, tzinfo=timezone.utc)
STATE_VERSION = 3

QA_VERIFIER_USER_ID = "00000000-0000-4000-8000-000000000001"
QA_OPERATOR_PASSWORD_DEFAULT = "QaOperator!2026"
QA_OPERATOR_SCOPES = ["operations"]
OPERATOR_POSITION_CODE = "operator_software"

SHIFT_COLUMNS = [
    "shift_key",
    "shift_id",
    "head_external_id",
    "head_name",
    "division_external_id",
    "division_name",
    "store_external_id",
    "store_name",
    "city",
    "country_code",
    "timezone",
    "address",
    "lon",
    "lat",
    "starts_at_local",
    "starts_at_utc",
    "ends_at_utc",
    "employee_personnel_number",
    "performer_external_id",
]

RF_CITIES = [
    {"code": "RF-01", "name": "Калининград", "timezone": "Europe/Kaliningrad", "offset": 2, "lat": (54.70, 54.76), "lon": (20.45, 20.55), "street": "Ленинский проспект"},
    {"code": "RF-02", "name": "Москва", "timezone": "Europe/Moscow", "offset": 3, "lat": (55.70, 55.78), "lon": (37.55, 37.65), "street": "ул. Тверская"},
    {"code": "RF-03", "name": "Санкт-Петербург", "timezone": "Europe/Moscow", "offset": 3, "lat": (59.90, 59.96), "lon": (30.25, 30.38), "street": "Невский проспект"},
    {"code": "RF-04", "name": "Казань", "timezone": "Europe/Moscow", "offset": 3, "lat": (55.76, 55.84), "lon": (49.10, 49.20), "street": "ул. Баумана"},
    {"code": "RF-05", "name": "Самара", "timezone": "Europe/Samara", "offset": 4, "lat": (53.17, 53.24), "lon": (50.10, 50.20), "street": "ул. Куйбышева"},
    {"code": "RF-06", "name": "Волгоград", "timezone": "Europe/Volgograd", "offset": 3, "lat": (48.67, 48.74), "lon": (44.48, 44.55), "street": "проспект Ленина"},
    {"code": "RF-07", "name": "Екатеринбург", "timezone": "Asia/Yekaterinburg", "offset": 5, "lat": (56.80, 56.87), "lon": (60.56, 60.65), "street": "ул. Малышева"},
    {"code": "RF-08", "name": "Челябинск", "timezone": "Asia/Yekaterinburg", "offset": 5, "lat": (55.14, 55.19), "lon": (61.37, 61.44), "street": "ул. Кирова"},
    {"code": "RF-09", "name": "Омск", "timezone": "Asia/Omsk", "offset": 6, "lat": (54.96, 55.02), "lon": (73.33, 73.40), "street": "ул. Ленина"},
    {"code": "RF-10", "name": "Новосибирск", "timezone": "Asia/Novosibirsk", "offset": 7, "lat": (55.01, 55.07), "lon": (82.90, 82.97), "street": "Красный проспект"},
]

BY_CITIES = [
    {"code": "BY-01", "name": "Минск", "timezone": "Europe/Minsk", "offset": 3, "lat": (53.88, 53.93), "lon": (27.53, 27.60), "street": "пр-т Независимости"},
    {"code": "BY-02", "name": "Брест", "timezone": "Europe/Minsk", "offset": 3, "lat": (52.08, 52.11), "lon": (23.66, 23.72), "street": "ул. Советская"},
    {"code": "BY-03", "name": "Витебск", "timezone": "Europe/Minsk", "offset": 3, "lat": (55.18, 55.21), "lon": (30.18, 30.25), "street": "ул. Ленина"},
    {"code": "BY-04", "name": "Гродно", "timezone": "Europe/Minsk", "offset": 3, "lat": (53.66, 53.70), "lon": (23.81, 23.87), "street": "ул. Советская"},
    {"code": "BY-05", "name": "Гомель", "timezone": "Europe/Minsk", "offset": 3, "lat": (52.42, 52.46), "lon": (30.95, 31.02), "street": "ул. Советская"},
    {"code": "BY-06", "name": "Могилёв", "timezone": "Europe/Minsk", "offset": 3, "lat": (53.89, 53.93), "lon": (30.30, 30.37), "street": "ул. Первомайская"},
]

SHIFTS_PER_DAY = len(RF_CITIES) * 2 + len(BY_CITIES)

# (фамилия, имя, отчество, username, роль)
OPERATORS = [
    ("Иванов", "Пётр", "Сергеевич", "qa.operator.1", "administrator"),
    ("Смирнова", "Ольга", "Андреевна", "qa.operator.2", "manager"),
    ("Кузнецов", "Дмитрий", "Викторович", "qa.operator.3", "supervisor"),
    ("Попова", "Елена", "Игоревна", "qa.operator.4", "manager"),
    ("Соколов", "Артём", "Павлович", "qa.operator.5", "supervisor"),
]

PERFORMERS = [
    ("Морозов", "Алексей", "Николаевич", "M"),
    ("Волкова", "Мария", "Сергеевна", "F"),
    ("Зайцев", "Илья", "Андреевич", "M"),
    ("Павлова", "Анна", "Дмитриевна", "F"),
    ("Семёнов", "Максим", "Олегович", "M"),
    ("Голубева", "Дарья", "Ильинична", "F"),
    ("Виноградов", "Никита", "Петрович", "M"),
    ("Богданова", "Софья", "Максимовна", "F"),
    ("Воробьёв", "Егор", "Сергеевич", "M"),
    ("Фёдорова", "Полина", "Алексеевна", "F"),
    ("Михайлов", "Роман", "Владимирович", "M"),
    ("Белова", "Ксения", "Андреевна", "F"),
    ("Тарасов", "Даниил", "Игоревич", "M"),
    ("Комарова", "Алиса", "Павловна", "F"),
    ("Орлов", "Тимофей", "Денисович", "M"),
    ("Киселёва", "Валерия", "Олеговна", "F"),
    ("Макаров", "Кирилл", "Антонович", "M"),
    ("Андреева", "Виктория", "Сергеевна", "F"),
    ("Никитин", "Степан", "Романович", "M"),
    ("Гусева", "Екатерина", "Владимировна", "F"),
]

# Стадии готовности по группам индексов 1-4, 5-8, 9-12, 13-16, 17-20.
STAGE_GROUPS = [
    {"stage": "PERFORMER_PROFILE", "medical": "none"},
    {"stage": "PERFORMER_DOCS_PENDING", "medical": "none"},
    {"stage": "PERFORMER_READY_NON_MEDICAL", "medical": "none"},
    {"stage": "PERFORMER_READY_NON_FOOD", "medical": "non_food"},
    {"stage": "PERFORMER_READY_FOOD", "medical": "food"},
]

EXPECTED_STAGE_COUNTS = {
    "PERFORMER_PROFILE": 4,
    "PERFORMER_DOCS_PENDING": 4,
    "PERFORMER_READY_NON_MEDICAL": 4,
    "PERFORMER_READY_NON_FOOD": 4,
    "PERFORMER_READY_FOOD": 4,
}

VALIDATION_VERIFIED = "verified"
VALIDATION_PENDING = "pending"
VALIDATION_REJECTED = "rejected"


def stable_uuid(kind: str, key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{kind}|{key}"))


def utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def local_iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def seeded_point(store_external_id: str, city: dict) -> tuple[float, float]:
    """Детерминированные координаты в границах города."""
    seed = int(uuid.uuid5(NAMESPACE, f"coords|{store_external_id}").int % (2**32))
    lat_span = city["lat"][1] - city["lat"][0]
    lon_span = city["lon"][1] - city["lon"][0]
    lat = city["lat"][0] + (seed % 10000) / 10000 * lat_span
    lon = city["lon"][0] + ((seed // 10000) % 10000) / 10000 * lon_span
    return round(lon, 6), round(lat, 6)


def seeded_house(store_external_id: str) -> int:
    return int(uuid.uuid5(NAMESPACE, f"house|{store_external_id}").int % 90) + 1


def seeded_address_point(seed_key: str, city: dict) -> tuple[float, float]:
    seed = int(uuid.uuid5(NAMESPACE, f"address-coords|{seed_key}").int % (2**32))
    lat_span = city["lat"][1] - city["lat"][0]
    lon_span = city["lon"][1] - city["lon"][0]
    lat = city["lat"][0] + (seed % 10000) / 10000 * lat_span
    lon = city["lon"][0] + ((seed // 10000) % 10000) / 10000 * lon_span
    return round(lon, 6), round(lat, 6)


def head_external_id(index: int) -> str:
    return f"QA-CLI-RF-{index:02d}"


def head_name(index: int) -> str:
    return f"КлиентРФ{index}"


def division_external_id(head_key: str, number: int) -> str:
    return f"QA-DIV-{head_key[7:]}-{number}"


def division_name(head: str, number: int) -> str:
    return f"{head} Дивизион {number}"


def build_clients() -> list[dict]:
    """Полная оргструктура: головные клиенты, по 3 дивизиона, магазины."""
    clients: list[dict] = []

    for index, city in enumerate(RF_CITIES, 1):
        head_ext = head_external_id(index)
        head = head_name(index)
        clients.append(
            {
                "external_id": head_ext,
                "name": head,
                "client_type_code": "head",
                "parent_external_id": None,
                "city": city["name"],
                "country_code": "RU",
                "timezone": city["timezone"],
                "address": None,
                "lon": None,
                "lat": None,
            }
        )
        divisions = []
        for number in range(1, 4):
            div_ext = division_external_id(head_ext, number)
            divisions.append(div_ext)
            clients.append(
                {
                    "external_id": div_ext,
                    "name": division_name(head, number),
                    "client_type_code": "division",
                    "parent_external_id": head_ext,
                    "head_external_id": head_ext,
                    "head_name": head,
                    "city": city["name"],
                    "country_code": "RU",
                    "timezone": city["timezone"],
                    "address": None,
                    "lon": None,
                    "lat": None,
                }
            )
        for number in range(1, 3):
            store_ext = f"QA-STORE-{head_ext[7:]}-{number:02d}"
            lon, lat = seeded_point(store_ext, city)
            clients.append(
                {
                    "external_id": store_ext,
                    "name": f"{head} Магазин {city['name']} {number}",
                    "client_type_code": "object",
                    "parent_external_id": divisions[number - 1],
                    "head_external_id": head_ext,
                    "head_name": head,
                    "city": city["name"],
                    "country_code": "RU",
                    "timezone": city["timezone"],
                    "address": f"г. {city['name']}, {city['street']}, д. {seeded_house(store_ext)}",
                    "lon": lon,
                    "lat": lat,
                }
            )

    by_head_ext = "QA-CLI-BY-01"
    by_head = "КлиентРБ1"
    clients.append(
        {
            "external_id": by_head_ext,
            "name": by_head,
            "client_type_code": "head",
            "parent_external_id": None,
            "city": "Минск",
            "country_code": "BY",
            "timezone": "Europe/Minsk",
            "address": None,
            "lon": None,
            "lat": None,
        }
    )
    by_divisions = []
    for number in range(1, 4):
        div_ext = division_external_id(by_head_ext, number)
        by_divisions.append(div_ext)
        clients.append(
            {
                "external_id": div_ext,
                "name": division_name(by_head, number),
                "client_type_code": "division",
                "parent_external_id": by_head_ext,
                "head_external_id": by_head_ext,
                "head_name": by_head,
                "city": "Минск",
                "country_code": "BY",
                "timezone": "Europe/Minsk",
                "address": None,
                "lon": None,
                "lat": None,
            }
        )
    for number, city in enumerate(BY_CITIES, 1):
        store_ext = f"QA-STORE-BY-01-{number:02d}"
        lon, lat = seeded_point(store_ext, city)
        clients.append(
            {
                "external_id": store_ext,
                "name": f"{by_head} Магазин {city['name']}",
                "client_type_code": "object",
                "parent_external_id": by_divisions[(number - 1) % 3],
                "head_external_id": by_head_ext,
                "head_name": by_head,
                "city": city["name"],
                "country_code": "BY",
                "timezone": "Europe/Minsk",
                "address": f"г. {city['name']}, {city['street']}, д. {seeded_house(store_ext)}",
                "lon": lon,
                "lat": lat,
            }
        )
    return clients


def build_stores() -> list[dict]:
    return [client for client in build_clients() if client["client_type_code"] == "object"]


def build_shift_rows(start_date: date, end_date: date) -> list[dict]:
    stores = build_stores()
    rf_stores = [store for store in stores if store["country_code"] == "RU"]
    by_stores = [store for store in stores if store["country_code"] == "BY"]
    rows: list[dict] = []

    day = start_date
    while day <= end_date:
        day_stores = rf_stores + by_stores
        for store in day_stores:
            local_start = datetime.combine(day, dt_time(8, 0))
            local_end = local_start + timedelta(hours=9)
            city = next(
                city for city in RF_CITIES + BY_CITIES if city["name"] == store["city"]
            )
            utc_start = local_start - timedelta(hours=city["offset"])
            utc_end = local_end - timedelta(hours=city["offset"])
            utc_start = utc_start.replace(tzinfo=timezone.utc)
            utc_end = utc_end.replace(tzinfo=timezone.utc)
            shift_key = f"shift.v1|{store['external_id']}|{utc_iso(utc_start)}"
            rows.append(
                {
                    "shift_key": shift_key,
                    "shift_id": stable_uuid("shift", shift_key),
                    "head_external_id": store["head_external_id"],
                    "head_name": store["head_name"],
                    "division_external_id": store["parent_external_id"],
                    "division_name": division_name(
                        store["head_name"], int(store["parent_external_id"].rsplit("-", 1)[1])
                    ),
                    "store_external_id": store["external_id"],
                    "store_name": store["name"],
                    "city": store["city"],
                    "country_code": store["country_code"],
                    "timezone": store["timezone"],
                    "address": store["address"],
                    "lon": store["lon"],
                    "lat": store["lat"],
                    "starts_at_local": local_iso(local_start),
                    "starts_at_utc": utc_iso(utc_start),
                    "ends_at_utc": utc_iso(utc_end),
                    "employee_personnel_number": None,
                    "performer_external_id": None,
                }
            )
        day += timedelta(days=1)
    return rows


def write_report(path: Path, start_date: date, end_date: date) -> int:
    rows = build_shift_rows(start_date, end_date)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHIFT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def expected_shift_count(start_date: date, end_date: date) -> int:
    return ((end_date - start_date).days + 1) * SHIFTS_PER_DAY


def validate_report(path: Path, start_date: date, end_date: date) -> list[dict]:
    try:
        handle = path.open(newline="", encoding="utf-8-sig")
    except FileNotFoundError:
        raise SystemExit(
            f"Отчёт не найден: {path}. Сгенерируйте его (--generate-only) или передайте файл в под."
        ) from None
    with handle:
        rows = list(csv.DictReader(handle))
    problems: list[str] = []
    if not rows:
        raise SystemExit("Отчёт пуст")

    keys = {row["shift_key"] for row in rows}
    if len(keys) != len(rows):
        problems.append(f"ключей {len(keys)}, строк {len(rows)}: есть дубли")

    starts_values: list[datetime] = []
    for row in rows:
        starts = datetime.fromisoformat(row["starts_at_utc"].replace("Z", "+00:00"))
        ends = datetime.fromisoformat(row["ends_at_utc"].replace("Z", "+00:00"))
        if ends - starts != timedelta(hours=9):
            problems.append(f"смена {row['shift_key']} длится {ends - starts}")
            break
        starts_values.append(starts)

    if starts_values:
        actual_start = min(starts_values).date()
        actual_end = max(starts_values).date()
        expected = expected_shift_count(actual_start, actual_end)
        if len(rows) != expected:
            problems.append(
                f"строк {len(rows)}, ожидается {expected} за период {actual_start}..{actual_end}"
            )
        if actual_start != start_date or actual_end != end_date:
            problems.append(
                f"период файла {actual_start}..{actual_end} "
                f"не совпадает с запрошенным {start_date}..{end_date}"
            )

    if problems:
        raise SystemExit("Отчёт не прошёл валидацию:\n- " + "\n- ".join(problems))
    return rows


def load_state(path: Path) -> dict:
    """Читает state-файл и оставляет только известные ключи версии 3."""
    previous: dict = {}
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as error:
            raise SystemExit(f"State-файл {path} не является корректным JSON: {error}") from None
    return {
        "version": STATE_VERSION,
        "generated_at": utc_iso(datetime.now(timezone.utc)),
        "operators": dict(previous.get("operators") or {}),
        "performers": dict(previous.get("performers") or {}),
    }


def save_state(path: Path, state: dict) -> None:
    """Атомарная запись: временный файл рядом, затем os.replace."""
    state["version"] = STATE_VERSION
    state["generated_at"] = utc_iso(datetime.now(timezone.utc))
    payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Не задана переменная окружения {name}")
    return value


def psycopg_dsn(dsn: str) -> str:
    """Django принимает postgis://, psycopg — только postgresql://."""
    for prefix in ("postgis://", "postgis+psycopg://"):
        if dsn.startswith(prefix):
            return "postgresql://" + dsn[len(prefix):]
    return dsn


def import_oms5(dsn: str, rows: list[dict], state: dict) -> dict:
    import psycopg

    counters = {"clients_created": 0, "shifts_created": 0, "shifts_skipped": 0}
    clients = build_clients()
    parent_ids: dict[str, str] = {}

    with psycopg.connect(dsn) as connection:
        for client in sorted(clients, key=lambda item: {"head": 0, "division": 1, "object": 2}[item["client_type_code"]]):
            client_id = stable_uuid("client", client["external_id"])
            parent_id = parent_ids.get(client["parent_external_id"]) if client["parent_external_id"] else None
            if client["parent_external_id"] and parent_id is None:
                existing = connection.execute(
                    "select id from clients where external_id = %s", (client["parent_external_id"],)
                ).fetchone()
                parent_id = existing[0] if existing else None
            cursor = connection.execute(
                """
                insert into clients
                    (id, name, external_id, client_type_code, parent_client_id, created_at,
                     address, country_code, timezone, lon, lat)
                values (%s, %s, %s, %s, %s, now(), %s, %s, %s, %s, %s)
                on conflict do nothing
                """,
                (
                    client_id, client["name"], client["external_id"], client["client_type_code"], parent_id,
                    client["address"], client["country_code"], client["timezone"], client["lon"], client["lat"],
                ),
            )
            if cursor.rowcount:
                counters["clients_created"] += 1
            stored = connection.execute(
                "select id from clients where external_id = %s", (client["external_id"],)
            ).fetchone()
            parent_ids[client["external_id"]] = stored[0]

        for row in rows:
            store_id = parent_ids[row["store_external_id"]]
            cursor = connection.execute(
                """
                insert into shifts
                    (id, client_id, starts_at, ends_at, location, required_performers_count,
                     status, assigned_performer_id, close_reason, failure_reason, auto_closed,
                     auto_close_reason, created_at, updated_at)
                values (%s, %s, %s, %s, %s, 1, 'A00_DRAFT', null, null, null, false, null, now(), now())
                on conflict do nothing
                """,
                (
                    row["shift_id"], store_id,
                    datetime.fromisoformat(row["starts_at_utc"].replace("Z", "+00:00")),
                    datetime.fromisoformat(row["ends_at_utc"].replace("Z", "+00:00")),
                    row["address"],
                ),
            )
            if cursor.rowcount:
                counters["shifts_created"] += 1
            else:
                counters["shifts_skipped"] += 1
    return counters


def operator_personnel_number(index: int) -> str:
    return f"QA-OPS-{index:03d}"


def performer_index_plan(index: int) -> dict:
    """Распределение типа оформления, подтверждения, медкнижки и документов."""
    group = (index - 1) // 4
    offset = (index - 1) % 4
    stage = STAGE_GROUPS[group]

    engagement_type = "gph" if offset % 2 == 0 else "self_employed"
    if group == 0:
        validation = (VALIDATION_VERIFIED, VALIDATION_VERIFIED, VALIDATION_PENDING, VALIDATION_REJECTED)[offset]
        documents = {"passport": None, "identifiers": []}
    elif group == 1:
        validation = VALIDATION_VERIFIED
        # 5-6: ИНН pending, 7-8: СНИЛС pending. Второго идентификатора нет.
        pending_type = "inn" if offset < 2 else "snils"
        documents = {"passport": "pending", "identifiers": [(pending_type, "pending")]}
    else:
        validation = VALIDATION_VERIFIED
        documents = {
            "passport": "verified",
            "identifiers": [("inn", "verified"), ("snils", "verified")],
        }

    return {
        "index": index,
        "personnel_number": f"QA-EMP-{index + 5:03d}",
        "performer_external_id": f"QA-PERF-{index:03d}",
        "engagement_type": engagement_type,
        "validation_status": validation,
        "medical_book_status": stage["medical"],
        "expected_stage": stage["stage"],
        "passport_status": documents["passport"],
        "identifiers": documents["identifiers"],
        "work_search_addresses": 1 if index <= 10 else 2,
    }


def passport_number(index: int) -> str:
    return f"45{index:02d}{700000 + index:06d}"


def inn_number(index: int) -> str:
    base = f"77{index:02d}{300000 + index:06d}"
    weights_11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
    weights_12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
    digits = [int(item) for item in base]
    check_11 = sum(digit * weight for digit, weight in zip(digits[:10], weights_11)) % 11 % 10
    check_12 = sum(digit * weight for digit, weight in zip(digits + [check_11], weights_12)) % 11 % 10
    return f"{base}{check_11}{check_12}"


def snils_number(index: int) -> str:
    base = f"{100000000 + index * 1013:09d}"
    digits = [int(item) for item in base]
    checksum = sum(digit * (9 - position) for position, digit in enumerate(digits))
    if checksum < 100:
        expected = checksum
    elif checksum in (100, 101):
        expected = 0
    else:
        expected = checksum % 101
        if expected in (100, 101):
            expected = 0
    return f"{base}{expected:02d}"


def build_address(index: int, address_type: str, slot: int) -> dict:
    city = RF_CITIES[(index - 1) % len(RF_CITIES)]
    seed_key = f"{index}|{address_type}|{slot}"
    # Дом зависит от персоны и адреса; слот сдвигает его на единицу, чтобы два
    # адреса work_search одной персоны гарантированно различались.
    base_house = int(uuid.uuid5(NAMESPACE, f"address-house|{index}").int % 100) + 1
    house = base_house + (slot - 1 if address_type == "work_search" else 0)
    flat = None
    if address_type == "registration":
        flat = int(uuid.uuid5(NAMESPACE, f"address-flat|{seed_key}").int % 300) + 1
    lon, lat = seeded_address_point(seed_key, city)
    full_address = f"г. {city['name']}, {city['street']}, д. {house}"
    if flat is not None:
        full_address = f"{full_address}, кв. {flat}"
    return {
        "full_address": full_address,
        "postal_code": f"{100000 + int(uuid.uuid5(NAMESPACE, f'address-postal|{seed_key}').int % 899999):06d}",
        "country_code": "RU",
        "country": "Россия",
        "city": city["name"],
        "street": city["street"],
        "house": str(house),
        "flat": str(flat) if flat is not None else "",
        "lon": lon,
        "lat": lat,
        "is_primary": address_type == "work_search" and slot == 1,
    }


def django_bootstrap(database_url: str) -> None:
    project_dir_env = os.environ.get("OMS2_PROJECT_DIR")
    if project_dir_env:
        project_dir = Path(project_dir_env).resolve()
    elif len(BASE_DIR.parents) > 2:
        project_dir = (BASE_DIR.parents[2] / "OMS2").resolve()
    else:
        project_dir = Path("/app")
    if not (project_dir / "manage.py").exists():
        raise SystemExit(f"Не найден OMS2 в {project_dir}; задайте OMS2_PROJECT_DIR")
    require_env("PERSON_DATA_ENCRYPTION_KEY")
    require_env("PERSON_IDENTIFIER_HMAC_KEY")
    os.environ["DJANGO_SETTINGS_MODULE"] = "root.settings"
    os.environ["DATABASE_URL"] = database_url
    sys.path.insert(0, str(project_dir))
    import django

    django.setup()


def import_oms2(dsn: str, state: dict, state_path: Path) -> dict:
    django_bootstrap(dsn)

    from django.contrib.gis.geos import Point
    from django.db import transaction

    from apps.employees.events import enqueue_performer_profile_changed
    from apps.employees.funnel import recompute_funnel_stage
    from apps.employees.models import (
        Address,
        PerformerEngagementTypeChange,
        PerformerProfile,
        PerformerWorkPeriod,
        Person,
        PersonAddress,
        PersonContact,
        PersonDocument,
        PersonIdentifier,
        PersonNameHistory,
    )
    from apps.employees.privacy import (
        encrypt_value,
        lookup_hmac,
        normalize_document_number,
        normalize_email,
        normalize_phone,
    )

    counters = {
        "persons_created": 0,
        "profiles_created": 0,
        "work_periods_created": 0,
        "addresses_created": 0,
        "contacts_created": 0,
        "documents_created": 0,
        "identifiers_created": 0,
    }
    failures: list[str] = []

    for index in range(1, len(PERFORMERS) + 1):
        plan = performer_index_plan(index)
        personnel_number = plan["personnel_number"]
        external_id = plan["performer_external_id"]
        surname, firstname, patronymic, gender = PERFORMERS[index - 1]

        try:
            with transaction.atomic():
                period = (
                    PerformerWorkPeriod.objects.select_related("person")
                    .filter(personnel_number=personnel_number)
                    .first()
                )
                if period is not None:
                    person = period.person
                else:
                    person = Person.objects.create(
                        surname=surname,
                        firstname=firstname,
                        patronymic=patronymic,
                        gender=gender,
                        identity_status=Person.IDENTITY_PROVISIONAL,
                        name_version=1,
                    )
                    PersonNameHistory.objects.create(
                        person=person,
                        surname=surname,
                        firstname=firstname,
                        patronymic=patronymic,
                        valid_from=EMPLOYMENT_START,
                        version=1,
                        change_reason="initial",
                    )
                    PerformerWorkPeriod.objects.create(
                        person=person,
                        engagement_type=plan["engagement_type"],
                        personnel_number=personnel_number,
                        status=PerformerWorkPeriod.STATUS_ACTIVE,
                        starts_at=EMPLOYMENT_START,
                        source="qa",
                    )
                    counters["persons_created"] += 1
                    counters["work_periods_created"] += 1

                profile = (
                    PerformerProfile.objects.select_for_update()
                    .filter(person=person)
                    .first()
                )
                profile_created = profile is None
                if profile_created:
                    validated = plan["validation_status"] in (
                        VALIDATION_VERIFIED,
                        VALIDATION_REJECTED,
                    )
                    profile = PerformerProfile.objects.create(
                        person=person,
                        status=PerformerProfile.STATUS_ACTIVE,
                        engagement_type=plan["engagement_type"],
                        engagement_type_validation_status=plan["validation_status"],
                        engagement_type_selected_at=EMPLOYMENT_START,
                        engagement_type_validated_at=EMPLOYMENT_START if validated else None,
                        engagement_type_validated_by_user_id=QA_VERIFIER_USER_ID if validated else None,
                        engagement_type_rejection_reason=(
                            "QA: тип оформления отклонён при проверке"
                            if plan["validation_status"] == VALIDATION_REJECTED
                            else None
                        ),
                        medical_book_status=plan["medical_book_status"],
                        funnel_stage=PerformerProfile.STAGE_PROFILE,
                        funnel_stage_changed_at=EMPLOYMENT_START,
                    )
                    PerformerEngagementTypeChange.objects.create(
                        person=person,
                        previous_engagement_type=None,
                        new_engagement_type=plan["engagement_type"],
                        previous_validation_status=None,
                        new_validation_status=plan["validation_status"],
                        change_source=PerformerEngagementTypeChange.SOURCE_REGISTRATION,
                        changed_by_user_id=QA_VERIFIER_USER_ID,
                        reason="QA registration",
                    )
                    counters["profiles_created"] += 1

                phone = normalize_phone(f"+7999{index:07d}")
                email = normalize_email(f"qa.performer.{index:02d}@example.test")
                for contact_type, value in (
                    (PersonContact.TYPE_PHONE, phone),
                    (PersonContact.TYPE_EMAIL, email),
                ):
                    namespace = f"contact:{contact_type}"
                    fingerprint = lookup_hmac(namespace, value)
                    exists = PersonContact.objects.filter(
                        person=person,
                        contact_type=contact_type,
                        lookup_hmac=fingerprint,
                    ).exists()
                    if exists:
                        continue
                    PersonContact.objects.create(
                        person=person,
                        contact_type=contact_type,
                        encrypted_value=encrypt_value(value),
                        lookup_hmac=fingerprint,
                        is_primary=True,
                        verification_status=PersonContact.VERIFICATION_VERIFIED,
                        status=PersonContact.STATUS_ACTIVE,
                        valid_from=EMPLOYMENT_START,
                        verified_at=EMPLOYMENT_START,
                    )
                    counters["contacts_created"] += 1

                passport_status = plan["passport_status"]
                if passport_status is not None:
                    normalized = normalize_document_number("passport", "RU", passport_number(index))
                    fingerprint = lookup_hmac("document:RU:passport", normalized)
                    exists = PersonDocument.objects.filter(
                        person=person,
                        document_type=PersonDocument.DOC_PASSPORT,
                        lookup_hmac=fingerprint,
                    ).exists()
                    if not exists:
                        verified = passport_status == "verified"
                        PersonDocument.objects.create(
                            person=person,
                            document_type=PersonDocument.DOC_PASSPORT,
                            passport_kind="national",
                            issuing_country_code="RU",
                            encrypted_number=encrypt_value(normalized),
                            lookup_hmac=fingerprint,
                            verification_status=(
                                PersonDocument.VERIFY_VERIFIED if verified else PersonDocument.VERIFY_PENDING
                            ),
                            status=(
                                PersonDocument.STATUS_ACTIVE if verified else PersonDocument.STATUS_PENDING
                            ),
                            issued_at=date(2021, 1, 1),
                            valid_from=date(2021, 1, 1),
                            valid_to=date(2031, 1, 1),
                            is_primary=True,
                            verified_at=EMPLOYMENT_START if verified else None,
                            verified_by_user_id=QA_VERIFIER_USER_ID if verified else None,
                        )
                        counters["documents_created"] += 1

                for identifier_type, identifier_status in plan["identifiers"]:
                    raw_value = inn_number(index) if identifier_type == "inn" else snils_number(index)
                    normalized = normalize_document_number(identifier_type, "RU", raw_value)
                    fingerprint = lookup_hmac(f"identifier:RU:{identifier_type}", normalized)
                    exists = PersonIdentifier.objects.filter(
                        person=person,
                        identifier_type=identifier_type,
                        lookup_hmac=fingerprint,
                    ).exists()
                    if exists:
                        continue
                    verified = identifier_status == "verified"
                    PersonIdentifier.objects.create(
                        person=person,
                        identifier_type=identifier_type,
                        country_code="RU",
                        encrypted_value=encrypt_value(normalized),
                        lookup_hmac=fingerprint,
                        verification_status=(
                            PersonIdentifier.VERIFY_VERIFIED if verified else PersonIdentifier.VERIFY_PENDING
                        ),
                        status=PersonIdentifier.STATUS_ACTIVE,
                        verified_at=EMPLOYMENT_START if verified else None,
                        verified_by_user_id=QA_VERIFIER_USER_ID if verified else None,
                        verification_source="qa_import" if verified else None,
                    )
                    counters["identifiers_created"] += 1

                address_specs = [("registration", 1)]
                for slot in range(1, plan["work_search_addresses"] + 1):
                    address_specs.append(("work_search", slot))
                for address_type, slot in address_specs:
                    spec = build_address(index, address_type, slot)
                    exists = PersonAddress.objects.filter(
                        person=person,
                        address_type=address_type,
                        address__full_address=spec["full_address"],
                    ).exists()
                    if exists:
                        continue
                    address = Address.objects.create(
                        full_address=spec["full_address"],
                        postal_code=spec["postal_code"],
                        country_code=spec["country_code"],
                        country=spec["country"],
                        city=spec["city"],
                        street=spec["street"],
                        house=spec["house"],
                        flat=spec["flat"],
                        main_address=spec["is_primary"],
                        location=Point(spec["lon"], spec["lat"], srid=4326),
                        is_auto=True,
                    )
                    PersonAddress.objects.create(
                        person=person,
                        address=address,
                        address_type=address_type,
                        is_primary=spec["is_primary"],
                    )
                    counters["addresses_created"] += 1

                actual_stage = recompute_funnel_stage(person.pk, enqueue=False)
                if actual_stage != plan["expected_stage"]:
                    raise RuntimeError(
                        f"стадия {actual_stage} не совпадает с ожидаемой {plan['expected_stage']}"
                    )
                if profile_created:
                    # recompute_funnel_stage обновляет профиль отдельным
                    # экземпляром; refresh_from_db сбрасывает кэш related
                    # объектов, иначе событие уйдёт со стадией PERFORMER_PROFILE.
                    person.refresh_from_db()
                    enqueue_performer_profile_changed(person)

                state.setdefault("performers", {})[external_id] = {
                    "person_id": person.pk,
                    "personnel_number": personnel_number,
                }
        except Exception as error:  # noqa: BLE001 - одна персона не должна ломать остальные
            failures.append(personnel_number)
            print(
                f"OMS2: персона {personnel_number} не импортирована: "
                f"{type(error).__name__}: {error}",
                flush=True,
            )
            continue
        save_state(state_path, state)
        print(
            f"OMS2: персона {personnel_number} обработана, стадия {plan['expected_stage']}",
            flush=True,
        )

    if failures:
        raise SystemExit("OMS2: не импортированы персоны: " + ", ".join(failures))
    return counters


def import_oms1(dsn: str, state: dict) -> dict:
    import bcrypt
    import psycopg

    password = os.environ.get("QA_OPERATOR_PASSWORD", QA_OPERATOR_PASSWORD_DEFAULT)
    password_hash: str | None = None
    counters = {
        "users_created": 0,
        "periods_created": 0,
        "assignments_created": 0,
        "roles_created": 0,
    }

    with psycopg.connect(dsn) as connection:
        for index, (surname, firstname, patronymic, username, role_code) in enumerate(OPERATORS, 1):
            personnel_number = operator_personnel_number(index)
            display_name = f"{surname} {firstname} {patronymic}"

            existing_user = connection.execute(
                "select id from users where username = %s",
                (username,),
            ).fetchone()
            if existing_user is None:
                if password_hash is None:
                    password_hash = bcrypt.hashpw(
                        password.encode("utf-8"), bcrypt.gensalt()
                    ).decode("utf-8")
                user_id = stable_uuid("user", username)
                connection.execute(
                    """
                    insert into users
                        (id, person_id, username, password_hash, display_name, name_version,
                         is_active, merged_into_user_id, scopes, auth_version, created_at, updated_at)
                    values (%s, null, %s, %s, %s, 1, true, null, %s::json, 1, now(), now())
                    """,
                    (user_id, username, password_hash, display_name, json.dumps(QA_OPERATOR_SCOPES)),
                )
                counters["users_created"] += 1
            else:
                user_id = existing_user[0]

            existing_period = connection.execute(
                "select id from operator_employment_periods where personnel_number = %s",
                (personnel_number,),
            ).fetchone()
            if existing_period is None:
                period_id = stable_uuid("operator-period", personnel_number)
                connection.execute(
                    """
                    insert into operator_employment_periods
                        (id, user_id, personnel_number, status, starts_at, ends_at,
                         termination_reason, source, created_at, updated_at)
                    values (%s, %s, %s, 'active', %s, null, null, 'qa', now(), now())
                    """,
                    (period_id, user_id, personnel_number, EMPLOYMENT_START),
                )
                counters["periods_created"] += 1
            else:
                period_id = existing_period[0]

            existing_assignment = connection.execute(
                """
                select id from operator_position_assignments
                where employment_period_id = %s and status = 'active'
                """,
                (period_id,),
            ).fetchone()
            if existing_assignment is None:
                assignment_id = stable_uuid("operator-assignment", personnel_number)
                connection.execute(
                    """
                    insert into operator_position_assignments
                        (id, employment_period_id, position_code, status, starts_at, ends_at,
                         created_at, updated_at)
                    values (%s, %s, %s, 'active', %s, null, now(), now())
                    """,
                    (assignment_id, period_id, OPERATOR_POSITION_CODE, EMPLOYMENT_START),
                )
                counters["assignments_created"] += 1
            else:
                assignment_id = existing_assignment[0]

            existing_role = connection.execute(
                """
                select id from access_role_assignments
                where user_id = %s and role_code = %s
                  and operator_employment_period_id = %s and status = 'active'
                """,
                (user_id, role_code, period_id),
            ).fetchone()
            if existing_role is None:
                connection.execute(
                    """
                    insert into access_role_assignments
                        (id, user_id, role_code, valid_from, valid_to, status, granted_by,
                         reason, operator_employment_period_id, operator_position_assignment_id,
                         membership_id, auth_version, granted_at, revoked_at, revoked_by, revoke_reason)
                    values (%s, %s, %s, %s, null, 'active', null,
                            'QA operator access', %s, %s,
                            null, 1, now(), null, null, null)
                    """,
                    (
                        stable_uuid("operator-role", f"{personnel_number}|{role_code}"),
                        user_id,
                        role_code,
                        EMPLOYMENT_START,
                        period_id,
                        assignment_id,
                    ),
                )
                counters["roles_created"] += 1

            state.setdefault("operators", {})[personnel_number] = {
                "user_id": user_id,
                "username": username,
            }

    return counters


def wait_for_projection(
    oms5_dsn: str,
    oms2_dsn: str | None,
    timeout: float,
) -> bool:
    import psycopg

    deadline = time.monotonic() + timeout
    performers = 0
    unpublished = None
    while time.monotonic() < deadline:
        with psycopg.connect(oms5_dsn) as connection:
            performers = connection.execute("select count(*) from performers").fetchone()[0]
        if oms2_dsn:
            with psycopg.connect(psycopg_dsn(oms2_dsn)) as connection:
                unpublished = connection.execute(
                    "select count(*) from employees_integrationoutbox where published_at is null"
                ).fetchone()[0]
        if performers >= 20 and unpublished in (None, 0):
            return True
        time.sleep(2)

    print(
        f"Проекция не готова: performers={performers}, "
        f"неопубликованных событий OMS2={unpublished}",
        flush=True,
    )
    print("Если проекция не появилась:", flush=True)
    print("  1. проверить employees_integrationoutbox в OMS2: published_at заполнен;", flush=True)
    print("  2. проверить person_event_inbox и person_consumer_state в OMS5;", flush=True)
    print("  3. проверить логи oms2-outbox-worker и oms5;", flush=True)
    print("  4. проверить, что topic people.performer.v1 создан.", flush=True)
    return False


def run_checks(oms1_dsn: str | None, oms2_dsn: str | None, oms5_dsn: str | None) -> bool:
    import psycopg

    failures: list[str] = []
    connections: dict[str, object] = {}

    def connection(dsn: str):
        normalized = psycopg_dsn(dsn)
        existing = connections.get(normalized)
        if existing is None:
            existing = psycopg.connect(normalized)
            existing.autocommit = True
            connections[normalized] = existing
        return existing

    def compare(dsn: str, label: str, sql: str, expected) -> None:
        actual = connection(dsn).execute(sql).fetchone()[0]
        if actual == expected:
            print(f"  [ok] {label}: {actual}", flush=True)
        else:
            failures.append(label)
            print(f"  [fail] {label}: {actual}, ожидается {expected}", flush=True)

    try:
        if oms1_dsn:
            print("Проверки OMS1:", flush=True)
            compare(oms1_dsn, "QA-операторы", "select count(*) from users where username like 'qa.operator.%'", 5)
            compare(
                oms1_dsn,
                "периоды QA-OPS",
                "select count(*) from operator_employment_periods where personnel_number like 'QA-OPS-%'",
                5,
            )
            compare(oms1_dsn, "периоды всего", "select count(*) from operator_employment_periods", 6)
            compare(oms1_dsn, "назначения на должность", "select count(*) from operator_position_assignments", 6)
            compare(
                oms1_dsn,
                "роли операторов",
                "select count(*) from access_role_assignments "
                "where role_code in ('manager', 'supervisor', 'administrator')",
                6,
            )
            compare(
                oms1_dsn,
                "QA-операторы без person_id",
                "select count(*) from users where username like 'qa.operator.%' and person_id is not null",
                0,
            )

        if oms2_dsn:
            print("Проверки OMS2:", flush=True)
            compare(oms2_dsn, "персоны", "select count(*) from employees_employeepersinfo", 20)
            compare(oms2_dsn, "профили", "select count(*) from employees_performerprofile", 20)
            compare(
                oms2_dsn,
                "аудит типа оформления",
                "select count(*) from employees_performerengagementtypechange",
                20,
            )
            compare(oms2_dsn, "периоды работы", "select count(*) from employees_performerworkperiod", 20)
            compare(oms2_dsn, "адреса", "select count(*) from employees_personaddress", 50)
            compare(oms2_dsn, "контакты", "select count(*) from employees_personcontact", 40)
            compare(
                oms2_dsn,
                "паспорта",
                "select count(*) from employees_persondocument where document_type = 'passport'",
                16,
            )
            compare(oms2_dsn, "идентификаторы", "select count(*) from employees_personidentifier", 28)
            compare(oms2_dsn, "нет employees_employmentepisode", "select to_regclass('employees_employmentepisode')::text", None)
            compare(oms2_dsn, "нет employees_positionassignment", "select to_regclass('employees_positionassignment')::text", None)
            compare(oms2_dsn, "нет employees_externalmembership", "select to_regclass('employees_externalmembership')::text", None)
            compare(
                oms2_dsn,
                "неопубликованные события OMS2",
                "select count(*) from employees_integrationoutbox where published_at is null",
                0,
            )
            compare(
                oms2_dsn,
                "операторы в OMS2",
                "select count(*) from employees_performerworkperiod where personnel_number like 'QA-OPS-%'",
                0,
            )
            rows = connection(oms2_dsn).execute(
                "select funnel_stage, count(*) from employees_performerprofile group by 1 order by 1"
            ).fetchall()
            actual_stages = {stage: count for stage, count in rows}
            if actual_stages == EXPECTED_STAGE_COUNTS:
                print(f"  [ok] стадии воронки: {actual_stages}", flush=True)
            else:
                failures.append("стадии воронки")
                print(f"  [fail] стадии воронки: {actual_stages}, ожидается {EXPECTED_STAGE_COUNTS}", flush=True)
            compare(
                oms2_dsn,
                "дубликаты фактов смен",
                "select count(*) from (select assignment_id, fact_type from employees_performershiftfact "
                "group by 1, 2 having count(*) > 1) duplicates",
                0,
            )

        if oms5_dsn:
            print("Проверки OMS5:", flush=True)
            compare(oms5_dsn, "клиенты", "select count(*) from clients", 70)
            compare(oms5_dsn, "смены", "select count(*) from shifts", 780)
            compare(oms5_dsn, "исполнители", "select count(*) from performers", 20)
            compare(
                oms5_dsn,
                "исполнители без типа оформления",
                "select count(*) from performers where engagement_type is null",
                0,
            )
            compare(
                oms5_dsn,
                "исполнители без стадии",
                "select count(*) from performers where funnel_stage is null",
                0,
            )
            compare(
                oms5_dsn,
                "неопубликованные события OMS5",
                "select count(*) from operations_outbox where published_at is null",
                0,
            )
    finally:
        for item in connections.values():
            item.close()

    if failures:
        print("Проверки не прошли: " + ", ".join(failures), flush=True)
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="QA: генерация отчёта и импорт QA-данных")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat, required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat, required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--import-only", action="store_true")
    parser.add_argument(
        "--skip-wait",
        action="store_true",
        help="не ждать проекцию и не выполнять проверки (диагностика промежуточного состояния)",
    )
    parser.add_argument("--wait-seconds", type=float, default=120.0, help="таймаут ожидания проекции")
    args = parser.parse_args()

    if args.date_from > args.date_to:
        raise SystemExit("Дата начала периода позже даты окончания")

    state = load_state(args.state)
    oms1_dsn = os.environ.get("OMS1_DATABASE_URL")
    oms2_dsn = os.environ.get("OMS2_DATABASE_URL")
    oms5_dsn = os.environ.get("OMS5_DATABASE_URL")

    if not args.import_only:
        count = write_report(args.report, args.date_from, args.date_to)
        print(
            f"[1/6] Отчёт сгенерирован: {args.report} "
            f"(строк: {count}, период {args.date_from}..{args.date_to})"
        )
        rows = validate_report(args.report, args.date_from, args.date_to)
        print(
            f"[2/6] Отчёт проверен: {len(rows)} смен "
            f"({args.date_from}..{args.date_to}), дублей нет"
        )
    elif oms5_dsn or oms2_dsn:
        rows = validate_report(args.report, args.date_from, args.date_to)
        print(
            f"[2/6] Отчёт проверен: {len(rows)} смен "
            f"({args.date_from}..{args.date_to}), дублей нет"
        )
    else:
        rows = []
        print("[2/6] Отчёт не требуется: импорт не пишет смены")

    if args.generate_only:
        save_state(args.state, state)
        return

    counters: dict[str, object] = {}

    if oms1_dsn:
        counters["oms1"] = import_oms1(require_env("OMS1_DATABASE_URL"), state)
        save_state(args.state, state)
        print("[3/6] OMS1: операторы импортированы")
    else:
        print("[3/6] OMS1 пропущен: не задан OMS1_DATABASE_URL")

    if oms2_dsn:
        counters["oms2"] = import_oms2(require_env("OMS2_DATABASE_URL"), state, args.state)
        save_state(args.state, state)
        print("[4/6] OMS2: исполнители импортированы")
    else:
        print("[4/6] OMS2 пропущен: не задан OMS2_DATABASE_URL")

    if oms5_dsn:
        counters["oms5"] = import_oms5(require_env("OMS5_DATABASE_URL"), rows, state)
        save_state(args.state, state)
        print("[5/6] OMS5: клиенты и смены импортированы")
    else:
        print("[5/6] OMS5 пропущен: не задан OMS5_DATABASE_URL")

    checks_ok = True
    if args.skip_wait:
        print("[6/6] Ожидание проекции и проверки пропущены (--skip-wait)")
    else:
        if oms5_dsn:
            projection_ok = wait_for_projection(
                require_env("OMS5_DATABASE_URL"),
                oms2_dsn,
                args.wait_seconds,
            )
            print(
                f"[6/6] Проекция performers: {'готова' if projection_ok else 'не готова'}",
                flush=True,
            )
            checks_ok = projection_ok
        checks_ok = run_checks(oms1_dsn, oms2_dsn, oms5_dsn) and checks_ok

    print("[6/6] Импорт завершён")
    for service, values in counters.items():
        print(f"  {service}: " + ", ".join(f"{key}={value}" for key, value in values.items()))

    if not checks_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
