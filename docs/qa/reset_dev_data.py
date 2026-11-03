"""Сброс dev-контура OMS в Kind: схемы OMS1/OMS2/OMS5, topic-и и consumer groups Kafka.

Скрипт работает только с dev-кластером Kind. Он не удаляет secrets, PVC,
deployments, services и ingress, не трогает базы OMS3 и OMS4 и не переносит
старые данные. Повторный запуск безопасен: пустая схема и отсутствующий topic
не считаются ошибкой.

Запуск (PowerShell или bash), из корня репозитория:

    $env:ALLOW_DEV_RESET="yes"
    python platform/docs/qa/reset_dev_data.py
    # подтверждение: ввести RESET

Другой namespace принимается только явным флагом:

    python platform/docs/qa/reset_dev_data.py --namespace oms-qa

Переменные окружения:

    ALLOW_DEV_RESET   обязательное значение yes, иначе выход с кодом 2
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[2]
KAFKA_MANIFEST = PLATFORM_DIR / "k8s" / "kafka-dev.yaml"

DEFAULT_NAMESPACE = "oms"
ALLOWED_CONTEXT_MARKERS = ("kind", "oms-cluster")

SERVICES = [
    "oms1",
    "oms2",
    "oms2-outbox-worker",
    "oms2-operations-consumer",
    "oms5",
]
REQUIRED_SERVICES = [name for name in SERVICES if name != "oms2-operations-consumer"]

DATABASES = [
    {
        "name": "OMS1",
        "deployment": "oms1-postgres",
        "user": "oms1",
        "database": "oms1",
        "cleanup": "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
    },
    {
        "name": "OMS2",
        "deployment": "oms2-postgres",
        "user": "oms2",
        "database": "oms2",
        # postgis пересоздаётся вместе со схемой: без него миграции не создадут
        # PointField в Address.location.
        "cleanup": (
            "DROP SCHEMA public CASCADE; CREATE SCHEMA public; "
            "CREATE EXTENSION IF NOT EXISTS postgis;"
        ),
    },
    {
        "name": "OMS5",
        "deployment": "oms5-postgres",
        "user": "oms5",
        "database": "oms5",
        "cleanup": "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
    },
]

TOPICS = ["people.access.v1", "people.performer.v1", "operations.performer.v1"]
CONSUMER_GROUPS = ["oms1.people.access", "oms5.people.performer", "oms2.operations.performer"]

# В манифесте Job называется kafka-topics-init; старое имя поддерживается,
# чтобы сброс работал и на кластерах, где Job создавали вручную под другим именем.
JOB_NAMES = ["kafka-topics-init", "kafka-topic-init"]

KAFKA_DEPLOYMENT = "kafka"
KAFKA_BOOTSTRAP = "kafka.oms.svc.cluster.local:9092"
KAFKA_BIN = "/opt/kafka/bin"

READY_PATHS = {
    "oms1": ["/health/ready/"],
    "oms2": ["/health/ready/"],
    "oms5": ["/health/ready/"],
}


class ResetError(RuntimeError):
    pass


def log(message: str) -> None:
    print(message, flush=True)


def kubectl_binary() -> str:
    binary = shutil.which("kubectl")
    if not binary:
        raise ResetError("kubectl не найден в PATH")
    return binary


def run_kubectl(
    args: list[str],
    *,
    check: bool = True,
    stdin_text: str | None = None,
) -> subprocess.CompletedProcess:
    command = [kubectl_binary(), *args]
    process = subprocess.run(
        command,
        input=stdin_text,
        text=True,
        capture_output=True,
    )
    if check and process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip()
        raise ResetError(f"kubectl {' '.join(args)} завершился с кодом {process.returncode}: {detail}")
    return process


def kubectl(namespace: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return run_kubectl(["-n", namespace, *args], check=check)


def current_context() -> str:
    result = run_kubectl(["config", "current-context"])
    context = result.stdout.strip()
    if not context:
        raise ResetError("kubectl config current-context пуст: нет активного кластера")
    return context


def resolve_namespace(explicit: str | None) -> str:
    result = run_kubectl(
        ["config", "view", "--minify", "-o", "jsonpath={..namespace}"],
        check=False,
    )
    context_namespace = result.stdout.strip() or DEFAULT_NAMESPACE
    namespace = explicit or context_namespace
    if namespace != DEFAULT_NAMESPACE and explicit is None:
        raise ResetError(
            f"namespace из контекста '{namespace}' не разрешён без флага --namespace; "
            f"сброс рассчитан на '{DEFAULT_NAMESPACE}'"
        )
    return namespace


def deployment_exists(namespace: str, name: str) -> bool:
    result = kubectl(namespace, "get", "deployment", name, check=False)
    return result.returncode == 0


def job_exists(namespace: str, name: str) -> bool:
    result = kubectl(namespace, "get", "job", name, check=False)
    return result.returncode == 0


def kafka_exec(namespace: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return kubectl(
        namespace,
        "exec",
        f"deploy/{KAFKA_DEPLOYMENT}",
        "--",
        *args,
        check=check,
    )


def list_topics(namespace: str) -> set[str]:
    result = kafka_exec(
        namespace,
        f"{KAFKA_BIN}/kafka-topics.sh",
        "--bootstrap-server",
        KAFKA_BOOTSTRAP,
        "--list",
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def list_consumer_groups(namespace: str) -> set[str]:
    result = kafka_exec(
        namespace,
        f"{KAFKA_BIN}/kafka-consumer-groups.sh",
        "--bootstrap-server",
        KAFKA_BOOTSTRAP,
        "--list",
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def print_targets(namespace: str) -> None:
    log("Цели сброса:")
    log(f"  context: {current_context()}")
    log(f"  namespace: {namespace}")
    log("  deployments:")
    for name in SERVICES:
        if deployment_exists(namespace, name):
            log(f"    - {name}")
        else:
            log(f"    - {name} (отсутствует, будет пропущен)")
    log("  базы данных (схема public):")
    for database in DATABASES:
        log(f"    - {database['name']}: deploy/{database['deployment']}, db={database['database']}")
    log("  topic-и Kafka:")
    for topic in TOPICS:
        log(f"    - {topic}")
    log("  consumer groups:")
    for group in CONSUMER_GROUPS:
        log(f"    - {group}")
    log("  Job инициализации topic-ов:")
    for job in JOB_NAMES:
        log(f"    - {job}")


def require_confirmation() -> None:
    answer = input("Введите RESET для продолжения: ").strip()
    if answer != "RESET":
        raise ResetError("подтверждение не получено, изменения не выполнялись")


def scale(namespace: str, name: str, replicas: int) -> None:
    if not deployment_exists(namespace, name):
        if name in REQUIRED_SERVICES:
            raise ResetError(f"deployment {name} не найден")
        log(f"  {name}: deployment отсутствует, шаг пропущен")
        return
    kubectl(namespace, "scale", f"deployment/{name}", f"--replicas={replicas}")
    log(f"  {name}: replicas={replicas}")


def wait_pods_gone(namespace: str, name: str, timeout: float = 180.0) -> None:
    if not deployment_exists(namespace, name):
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = kubectl(
            namespace,
            "get",
            "pods",
            "-l",
            f"app={name}",
            "--no-headers",
            check=False,
        )
        if result.returncode != 0:
            raise ResetError(f"не удалось получить поды {name}: {result.stderr.strip()}")
        if not result.stdout.strip():
            log(f"  {name}: подов нет")
            return
        time.sleep(2)
    raise ResetError(f"поды {name} не завершились за {int(timeout)} секунд")


def clean_schema(namespace: str, database: dict) -> None:
    deployment = database["deployment"]
    if not deployment_exists(namespace, deployment):
        raise ResetError(f"deployment {deployment} не найден")
    log(f"  {database['name']}: схема public пересоздаётся")
    kubectl(
        namespace,
        "exec",
        f"deploy/{deployment}",
        "--",
        "psql",
        "-U",
        database["user"],
        "-d",
        database["database"],
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        database["cleanup"],
        check=True,
    )


def delete_topics(namespace: str) -> None:
    for topic in TOPICS:
        log(f"  topic {topic}: удаляется")
        kafka_exec(
            namespace,
            f"{KAFKA_BIN}/kafka-topics.sh",
            "--bootstrap-server",
            KAFKA_BOOTSTRAP,
            "--delete",
            "--if-exists",
            "--topic",
            topic,
            check=False,
        )
    # Удаление topic-ов асинхронное: пока оно не завершилось, Kafka не даёт
    # удалить consumer group, у которой остались offset-ы по этим topic-ам.
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        present = list_topics(namespace)
        leftover = [topic for topic in TOPICS if topic in present]
        if not leftover:
            log("  topic-и удалены")
            return
        time.sleep(2)
    raise ResetError("topic-и не удалены: " + ", ".join(leftover))


def delete_consumer_groups(namespace: str) -> None:
    # После остановки consumer-ов Kafka держит участников группы до истечения
    # session.timeout.ms, поэтому удаление может временно отвечать "group is not
    # empty". Повторяем попытки, пока группа не исчезнет из списка.
    for group in CONSUMER_GROUPS:
        log(f"  consumer group {group}: удаляется")
        last_error = ""
        for _ in range(30):
            result = kafka_exec(
                namespace,
                f"{KAFKA_BIN}/kafka-consumer-groups.sh",
                "--bootstrap-server",
                KAFKA_BOOTSTRAP,
                "--delete",
                "--group",
                group,
                check=False,
            )
            last_error = (result.stderr or result.stdout or "").strip()
            if group not in list_consumer_groups(namespace):
                break
            time.sleep(3)
        else:
            log(f"  consumer group {group}: не удалена, последний ответ: {last_error}")


def verify_consumer_groups_absent(namespace: str) -> None:
    present = list_consumer_groups(namespace)
    leftover = sorted(group for group in CONSUMER_GROUPS if group in present)
    if leftover:
        raise ResetError(
            "consumer groups не удалены: " + ", ".join(leftover)
        )
    log("  consumer groups отсутствуют")


def recreate_topics(namespace: str) -> None:
    if not KAFKA_MANIFEST.exists():
        raise ResetError(f"манифест Kafka не найден: {KAFKA_MANIFEST}")
    for job in JOB_NAMES:
        if job_exists(namespace, job):
            log(f"  Job {job}: удаляется")
            kubectl(namespace, "delete", "job", job, "--ignore-not-found")
    log(f"  применяется {KAFKA_MANIFEST}")
    run_kubectl(["apply", "-f", str(KAFKA_MANIFEST)])
    log("  ожидание завершения Job инициализации topic-ов")
    kubectl(
        namespace,
        "wait",
        "--for=condition=complete",
        f"job/{JOB_NAMES[0]}",
        "--timeout=300s",
    )


def verify_topics_present(namespace: str) -> None:
    present = list_topics(namespace)
    missing = [topic for topic in TOPICS if topic not in present]
    if missing:
        raise ResetError("topic-и не созданы: " + ", ".join(missing))
    log("  topic-и созданы: " + ", ".join(TOPICS))


def wait_rollout(namespace: str, name: str, timeout: float = 300.0) -> None:
    if not deployment_exists(namespace, name):
        log(f"  {name}: deployment отсутствует, шаг пропущен")
        return
    kubectl(
        namespace,
        "rollout",
        "status",
        f"deployment/{name}",
        f"--timeout={int(timeout)}s",
    )
    log(f"  {name}: rollout завершён")


def check_readiness(namespace: str, attempts: int = 30, delay: float = 2.0) -> None:
    for service, paths in READY_PATHS.items():
        if not deployment_exists(namespace, service):
            raise ResetError(f"deployment {service} не найден: проверка readiness невозможна")
        last_error = ""
        for _ in range(attempts):
            for path in paths:
                script = (
                    "import sys, urllib.request;"
                    f"r=urllib.request.urlopen('http://127.0.0.1:8000{path}', timeout=5);"
                    "sys.exit(0 if r.status == 200 else 1)"
                )
                result = kubectl(
                    namespace,
                    "exec",
                    f"deploy/{service}",
                    "--",
                    "python",
                    "-c",
                    script,
                    check=False,
                )
                if result.returncode == 0:
                    last_error = ""
                    break
                last_error = (result.stderr or "").strip()
            if not last_error:
                break
            time.sleep(delay)
        if last_error:
            raise ResetError(f"{service}: /health/ready/ не отвечает: {last_error}")
        log(f"  {service}: /health/ready/ 200")


def main() -> None:
    parser = argparse.ArgumentParser(description="Сброс dev-контура OMS в Kind")
    parser.add_argument("--namespace", default=None, help="namespace, отличный от oms (только явно)")
    args = parser.parse_args()

    try:
        context = current_context()
        if not any(marker in context for marker in ALLOWED_CONTEXT_MARKERS):
            raise ResetError(
                f"context '{context}' не похож на dev-кластер Kind: "
                f"ожидается подстрока {' или '.join(ALLOWED_CONTEXT_MARKERS)}"
            )
        namespace = resolve_namespace(args.namespace)

        if os.environ.get("ALLOW_DEV_RESET") != "yes":
            log("Сброс отменён: задайте ALLOW_DEV_RESET=yes")
            sys.exit(2)

        print_targets(namespace)
        require_confirmation()

        log("Масштабирование сервисов в 0:")
        for name in SERVICES:
            scale(namespace, name, 0)
        log("Ожидание завершения подов:")
        for name in SERVICES:
            wait_pods_gone(namespace, name)

        log("Очистка схем public:")
        for database in DATABASES:
            clean_schema(namespace, database)

        log("Удаление topic-ов Kafka:")
        delete_topics(namespace)
        log("Удаление consumer groups:")
        delete_consumer_groups(namespace)
        verify_consumer_groups_absent(namespace)

        log("Пересоздание topic-ов Kafka:")
        recreate_topics(namespace)
        verify_topics_present(namespace)

        log("Масштабирование сервисов в 1:")
        for name in SERVICES:
            scale(namespace, name, 1)
        log("Ожидание rollout:")
        for name in SERVICES:
            wait_rollout(namespace, name)

        log("Проверка readiness:")
        check_readiness(namespace)

        log("Сброс dev-контура завершён")
    except ResetError as error:
        log(f"Ошибка сброса: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
