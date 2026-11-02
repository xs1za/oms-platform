"""Генерация mock-отчёта по сменам и импорт QA-данных в OMS1, OMS2 и OMS5.

Период обязателен во всех режимах: `--from` и `--to` принимают дату в формате
YYYY-MM-DD, значения по умолчанию отсутствуют.

    python generate_and_import.py --from 2026-11-01 --to 2026-11-30
    python generate_and_import.py --from 2026-11-01 --to 2026-11-30 --generate-only
    python generate_and_import.py --from 2026-12-01 --to 2026-12-31 --import-only

Импорт дополняет базу: существующие записи не удаляются и не изменяются, новые
смены добавляются к уже имеющимся. Поэтому декабрьский прогон после ноябрьского
даёт 806 новых смен поверх 780 существующих.

Переменные окружения для импорта:

    OMS2_DATABASE_URL   DSN PostgreSQL OMS2 (обязателен для импорта OMS2)
    OMS5_DATABASE_URL   DSN PostgreSQL OMS5 (обязателен для импорта OMS5)
    OMS1_DATABASE_URL   DSN PostgreSQL OMS1 (необязателен, создаёт доступ операторам)
    OMS2_PROJECT_DIR    путь к исходникам OMS2 (по умолчанию соседняя папка OMS2)
    QA_OPERATOR_PASSWORD пароль операторов QA (по умолчанию QaOperator!2026)

Импорт идемпотентен: естественные ключи — personnel_number, clients.external_id и
UUIDv5 от store_external_id + starts_at (UTC). Повторный запуск с тем же периодом
пропускает существующие записи, запуск с новым периодом добавляет только новые
смены. OMS2 и OMS5 находятся в разных базах, поэтому импорт возобновляемый:
состояние по сотрудникам сохраняется в import_state.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_REPORT = BASE_DIR / "report_shifts.csv"
DEFAULT_STATE = BASE_DIR / "import_state.json"

NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
EMPLOYMENT_START = datetime(2026, 10, 1, tzinfo=timezone.utc)
REPORT_VERSION = 2

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

OPERATORS = [
    ("Иванов", "Пётр", "Сергеевич", "M"),
    ("Смирнова", "Ольга", "Андреевна", "F"),
    ("Кузнецов", "Дмитрий", "Викторович", "M"),
    ("Попова", "Елена", "Игоревна", "F"),
    ("Соколов", "Артём", "Павлович", "M"),
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
            local_start = datetime.combine(day, time(8, 0))
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
    if not path.exists():
        return {"version": REPORT_VERSION, "employees": {}, "counters": {}}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Не задана переменная окружения {name}")
    return value


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


def django_bootstrap(database_url: str) -> None:
    from cryptography.fernet import Fernet

    project_dir_env = os.environ.get("OMS2_PROJECT_DIR")
    if project_dir_env:
        project_dir = Path(project_dir_env).resolve()
    elif len(BASE_DIR.parents) > 2:
        project_dir = (BASE_DIR.parents[2] / "OMS2").resolve()
    else:
        project_dir = Path("/app")
    if not (project_dir / "manage.py").exists():
        raise SystemExit(f"Не найден OMS2 в {project_dir}; задайте OMS2_PROJECT_DIR")
    os.environ["DJANGO_SETTINGS_MODULE"] = "root.settings"
    os.environ["DATABASE_URL"] = database_url
    os.environ.setdefault("PERSON_DATA_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    os.environ.setdefault("PERSON_IDENTIFIER_HMAC_KEY", "qa-seed-hmac-key-not-for-production-use")
    sys.path.insert(0, str(project_dir))
    import django

    django.setup()


def import_oms2(dsn: str, state: dict) -> dict:
    django_bootstrap(dsn)

    from django.db import transaction

    from apps.employees.events import enqueue_employment_changed, enqueue_performer_profile_changed
    from apps.employees.models import (
        EmploymentEpisode,
        PerformerProfile,
        Person,
        PersonNameHistory,
        PositionAssignment,
    )

    counters = {"employees_created": 0, "employees_skipped": 0, "performers_created": 0}
    employees: list[dict] = []
    for index in range(1, 6):
        surname, firstname, patronymic, gender = OPERATORS[index - 1]
        employees.append(
            {
                "personnel_number": f"QA-EMP-{index:03d}",
                "surname": surname,
                "firstname": firstname,
                "patronymic": patronymic,
                "gender": gender,
                "performer_external_id": None,
            }
        )
    for index in range(6, 26):
        surname, firstname, patronymic, gender = PERFORMERS[index - 6]
        employees.append(
            {
                "personnel_number": f"QA-EMP-{index:03d}",
                "surname": surname,
                "firstname": firstname,
                "patronymic": patronymic,
                "gender": gender,
                "performer_external_id": f"QA-PERF-{index - 5:03d}",
            }
        )

    for employee in employees:
        episode = (
            EmploymentEpisode.objects.filter(personnel_number=employee["personnel_number"])
            .select_related("person")
            .first()
        )
        if episode is not None:
            person = episode.person
            counters["employees_skipped"] += 1
        else:
            with transaction.atomic():
                person = Person.objects.create(
                    surname=employee["surname"],
                    firstname=employee["firstname"],
                    patronymic=employee["patronymic"],
                    gender=employee["gender"],
                    identity_status=Person.IDENTITY_PROVISIONAL,
                    name_version=1,
                )
                PersonNameHistory.objects.create(
                    person=person,
                    surname=employee["surname"],
                    firstname=employee["firstname"],
                    patronymic=employee["patronymic"],
                    valid_from=EMPLOYMENT_START,
                    version=1,
                    change_reason="initial",
                )
                episode = EmploymentEpisode.objects.create(
                    person=person,
                    personnel_number=employee["personnel_number"],
                    status=EmploymentEpisode.STATUS_ACTIVE,
                    starts_at=EMPLOYMENT_START,
                    source="qa",
                )
                assignment = PositionAssignment.objects.create(
                    employment_episode=episode,
                    position_code="operator_software",
                    status=PositionAssignment.STATUS_ACTIVE,
                    starts_at=EMPLOYMENT_START,
                )
                enqueue_employment_changed(
                    person,
                    episode.pk,
                    episode.status,
                    assignment.pk,
                    assignment.position_code,
                    EMPLOYMENT_START,
                )
            counters["employees_created"] += 1

        state["employees"][employee["personnel_number"]] = person.pk

        if employee["performer_external_id"]:
            with transaction.atomic():
                profile, created = PerformerProfile.objects.get_or_create(
                    person=person, defaults={"status": PerformerProfile.STATUS_ACTIVE}
                )
                if created:
                    enqueue_performer_profile_changed(person)
                    counters["performers_created"] += 1
                state.setdefault("performers", {})[employee["performer_external_id"]] = person.pk

    return counters


def import_oms1(dsn: str, state: dict) -> dict:
    try:
        import bcrypt
    except ImportError:
        print("OMS1 пропущен: модуль bcrypt недоступен в этом окружении")
        return {}

    import psycopg

    password = os.environ.get("QA_OPERATOR_PASSWORD", "QaOperator!2026")
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    scopes = json.dumps(["operations"])
    counters = {"users_created": 0, "assignments_created": 0}

    if not state.get("employees"):
        raise SystemExit(
            "OMS1: в import_state.json нет сотрудников. Сначала выполните импорт OMS5/OMS2, "
            "затем передайте файл состояния в этот под."
        )

    with psycopg.connect(dsn) as connection:
        for index in range(1, 6):
            personnel_number = f"QA-EMP-{index:03d}"
            person_id = state["employees"].get(personnel_number)
            if person_id is None:
                continue
            username = f"qa.operator.{index}"
            display_name = " ".join(
                part for part in (OPERATORS[index - 1][1], OPERATORS[index - 1][2], OPERATORS[index - 1][0]) if part
            )
            user_id = stable_uuid("user", username)
            cursor = connection.execute(
                """
                insert into users
                    (id, person_id, username, password_hash, display_name, name_version, is_active,
                     merged_into_user_id, scopes, auth_version, created_at, updated_at)
                values (%s, %s, %s, %s, %s, 1, true, null, %s::json, 1, now(), now())
                on conflict (username) do update
                    set person_id = excluded.person_id,
                        display_name = excluded.display_name,
                        updated_at = now()
                    where users.person_id is distinct from excluded.person_id
                       or users.display_name is distinct from excluded.display_name
                returning id
                """,
                (user_id, person_id, username, password_hash, display_name, scopes),
            )
            stored = cursor.fetchone()
            if cursor.rowcount and stored:
                counters["users_created"] += 1
                user_id = stored[0]

            assignment = connection.execute(
                """
                select id from access_role_assignments
                where user_id = %s and role_code = 'administrator' and status = 'active'
                """,
                (user_id,),
            ).fetchone()
            if assignment is None:
                connection.execute(
                    """
                    insert into access_role_assignments
                        (id, user_id, role_code, organization_id, valid_from, valid_to, status,
                         granted_by, reason, employment_episode_id, position_assignment_id,
                         membership_id, auth_version, granted_at, revoked_at, revoked_by, revoke_reason)
                    values (%s, %s, 'administrator', null, now(), null, 'active', null,
                            'QA seed operator access', null, null, null, 1, now(), null, null, null)
                    """,
                    (stable_uuid("assignment", username), user_id),
                )
                counters["assignments_created"] += 1
    counters["password"] = password
    return counters


def main() -> None:
    parser = argparse.ArgumentParser(description="QA: генерация отчёта и импорт смен")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat, required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat, required=True, metavar="YYYY-MM-DD")
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--import-only", action="store_true")
    args = parser.parse_args()

    if args.date_from > args.date_to:
        raise SystemExit("Дата начала периода позже даты окончания")

    state = load_state(args.state)

    if not args.import_only:
        count = write_report(args.report, args.date_from, args.date_to)
        print(
            f"[1/3] Отчёт сгенерирован: {args.report} "
            f"(строк: {count}, период {args.date_from}..{args.date_to})"
        )
        rows = validate_report(args.report, args.date_from, args.date_to)
        print(
            f"[2/3] Отчёт проверен: {len(rows)} смен "
            f"({args.date_from}..{args.date_to}), дублей нет"
        )
    elif os.environ.get("OMS5_DATABASE_URL") or os.environ.get("OMS2_DATABASE_URL"):
        rows = validate_report(args.report, args.date_from, args.date_to)
        print(
            f"[2/3] Отчёт проверен: {len(rows)} смен "
            f"({args.date_from}..{args.date_to}), дублей нет"
        )
    else:
        rows = []
        print("[2/3] Отчёт не требуется: импортируется только доступ OMS1")

    if args.generate_only:
        save_state(args.state, state)
        return

    counters: dict[str, object] = {}
    if os.environ.get("OMS5_DATABASE_URL"):
        counters["oms5"] = import_oms5(require_env("OMS5_DATABASE_URL"), rows, state)
    else:
        print("[3/3] OMS5 пропущен: не задан OMS5_DATABASE_URL")

    if os.environ.get("OMS2_DATABASE_URL"):
        counters["oms2"] = import_oms2(require_env("OMS2_DATABASE_URL"), state)
    else:
        print("[3/3] OMS2 пропущен: не задан OMS2_DATABASE_URL")

    if os.environ.get("OMS1_DATABASE_URL"):
        counters["oms1"] = import_oms1(require_env("OMS1_DATABASE_URL"), state)

    state["counters"] = counters
    save_state(args.state, state)

    print("[3/3] Импорт завершён")
    for service, values in counters.items():
        print(f"  {service}: " + ", ".join(f"{key}={value}" for key, value in values.items()))


if __name__ == "__main__":
    main()
