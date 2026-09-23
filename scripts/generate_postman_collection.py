#!/usr/bin/env python3
"""Generate a Postman collection from OpenAPI plus an optional collection overlay.

The OpenAPI file is the source of truth for request schemas and operation
descriptions. By default, the existing Postman collection is used as an overlay
to preserve hand-written examples, mock responses, variables, folders, and
scripts. Use --from-scratch to create a collection only from OpenAPI.

Usage:
    python platform/scripts/generate_postman_collection.py
    python platform/scripts/generate_postman_collection.py --openapi openapi.json --overlay collection.json --output collection.json
    python platform/scripts/generate_postman_collection.py --from-scratch --output collection.json
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OPENAPI = PLATFORM_ROOT / "contracts" / "openapi_oms_microservices.json"
DEFAULT_COLLECTION = PLATFORM_ROOT / "contracts" / "postman_oms_microservices_collection.json"
SERVICE_BASE_URL_VARIABLES = {
    "OMS1 Auth Service": "{{oms1_base_url}}",
    "OMS2 Employee Service": "{{oms2_base_url}}",
    "OMS3 Report Service": "{{oms3_base_url}}",
    "OMS4 Notification Service": "{{oms4_base_url}}",
    "OMS5 Operations Service": "{{oms5_base_url}}",
}


def empty_collection(openapi: dict[str, Any]) -> dict[str, Any]:
    title = openapi.get("info", {}).get("title", "OMS Microservices Contracts")
    return {
        "info": {
            "name": title,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [],
        "variable": [
            {"key": "oms1_base_url", "value": "http://oms.local/oms1"},
            {"key": "oms2_base_url", "value": "http://oms.local/oms2"},
            {"key": "oms3_base_url", "value": "http://oms.local/oms3"},
            {"key": "oms4_base_url", "value": "http://oms.local/oms4"},
            {"key": "oms5_base_url", "value": "http://oms.local/oms5"},
            {"key": "access_token", "value": ""},
        ],
    }


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")


def resolve_ref(document: dict[str, Any], value: Any) -> Any:
    if not isinstance(value, dict) or "$ref" not in value:
        return value

    ref = value["$ref"]
    if not ref.startswith("#/"):
        return value

    current: Any = document
    for part in ref[2:].split("/"):
        current = current[part]
    return resolve_refs(document, current)


def resolve_refs(document: dict[str, Any], value: Any) -> Any:
    if isinstance(value, dict):
        if "$ref" in value:
            return resolve_ref(document, value)
        return {key: resolve_refs(document, item) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_refs(document, item) for item in value]
    return value


def normalize_path(path: str) -> str:
    if not path:
        return "/"
    parsed = urlparse(path)
    clean = parsed.path if parsed.scheme or parsed.netloc else path
    clean = clean.split("?", 1)[0]

    # Strip Postman variables and service prefixes.
    for prefix in (
        "{{oms1_base_url}}",
        "{{oms2_base_url}}",
        "{{oms3_base_url}}",
        "{{oms4_base_url}}",
        "{{oms5_base_url}}",
        "{{baseUrl}}",
    ):
        if clean.startswith(prefix):
            clean = clean[len(prefix) :]

    for ingress_prefix in ("/oms1", "/oms2", "/oms3", "/oms4", "/oms5"):
        if clean == ingress_prefix:
            clean = "/"
        elif clean.startswith(ingress_prefix + "/"):
            clean = clean[len(ingress_prefix) :]

    if not clean.startswith("/"):
        clean = "/" + clean
    clean = re.sub(r"\{\{([^}/]+)\}\}", "{param}", clean)
    clean = re.sub(r"\{([^}/]+)\}", "{param}", clean)
    return clean


def request_url_raw(request: dict[str, Any]) -> str:
    url = request.get("url", "")
    if isinstance(url, str):
        return url
    if isinstance(url, dict):
        return str(url.get("raw") or "")
    return ""


def build_operation_index(openapi: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    operations: dict[tuple[str, str], dict[str, Any]] = {}
    for path, path_item in openapi.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            method_upper = method.upper()
            if method_upper not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                continue
            operations[(method_upper, normalize_path(path))] = operation
    return operations


def iter_openapi_operations(openapi: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    result: list[tuple[str, str, dict[str, Any]]] = []
    for path, path_item in openapi.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            method_upper = method.upper()
            if method_upper in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                result.append((method_upper, normalize_path(path), operation))
    return result


def collection_operation_keys(items: list[dict[str, Any]]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for item in items:
        if "item" in item and isinstance(item["item"], list):
            keys.update(collection_operation_keys(item["item"]))
            continue
        request = item.get("request")
        if isinstance(request, dict):
            method = str(request.get("method", "GET")).upper()
            keys.add((method, normalize_path(request_url_raw(request))))
    return keys


def request_service_marker(request: dict[str, Any]) -> str:
    raw = request_url_raw(request)
    for variable in SERVICE_BASE_URL_VARIABLES.values():
        if raw.startswith(variable):
            return variable
    parsed = urlparse(raw)
    path = parsed.path if parsed.scheme or parsed.netloc else raw
    for service_number in range(1, 6):
        prefix = f"/oms{service_number}"
        if path == prefix or path.startswith(prefix + "/"):
            return f"{{{{oms{service_number}_base_url}}}}"
    return ""


def collection_operation_keys_by_service(items: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    for item in items:
        if "item" in item and isinstance(item["item"], list):
            keys.update(collection_operation_keys_by_service(item["item"]))
            continue
        request = item.get("request")
        if isinstance(request, dict):
            method = str(request.get("method", "GET")).upper()
            keys.add((method, request_service_marker(request), normalize_path(request_url_raw(request))))
    return keys


def service_name_for_operation(path: str, operation: dict[str, Any]) -> str:
    operation_id = str(operation.get("operationId", ""))
    if operation_id.startswith("oms1"):
        return "OMS1 Auth Service"
    if operation_id.startswith("oms2"):
        return "OMS2 Employee Service"
    if operation_id.startswith("oms3"):
        return "OMS3 Report Service"
    if operation_id.startswith("oms4"):
        return "OMS4 Notification Service"
    if operation_id.startswith("oms5"):
        return "OMS5 Operations Service"
    if path.startswith("/auth"):
        return "OMS1 Auth Service"
    if path.startswith("/api/employees"):
        return "OMS2 Employee Service"
    if path.startswith("/api/v1/report-tasks"):
        return "OMS3 Report Service"
    if path.startswith("/notifications"):
        return "OMS4 Notification Service"
    return "OMS5 Operations Service"


def base_url_variable_for_service(service_name: str) -> str:
    return SERVICE_BASE_URL_VARIABLES.get(service_name, "{{baseUrl}}")


def ensure_service_folder(collection: dict[str, Any], service_name: str) -> dict[str, Any]:
    items = collection.setdefault("item", [])
    for item in items:
        if item.get("name") == service_name and isinstance(item.get("item"), list):
            return item
    folder = {"name": service_name, "item": []}
    items.append(folder)
    return folder


def ensure_healthcheck_folder(service_folder: dict[str, Any]) -> dict[str, Any]:
    for item in service_folder.setdefault("item", []):
        if item.get("name") == "healthcheck" and isinstance(item.get("item"), list):
            return item
    folder = {"name": "healthcheck", "item": []}
    service_folder["item"].insert(0, folder)
    return folder


def display_name_for_operation(method: str, path: str, operation: dict[str, Any]) -> str:
    summary = operation.get("summary")
    if isinstance(summary, str) and summary:
        return summary
    return f"{method} {path}"


def postman_path_from_openapi(path: str) -> str:
    return path.replace("{", "{{").replace("}", "}}")


def response_examples_from_openapi(openapi: dict[str, Any], operation: dict[str, Any]) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    for code, response in operation.get("responses", {}).items():
        resolved = resolve_refs(openapi, response)
        description = resolved.get("description", "") if isinstance(resolved, dict) else ""
        status_name = f"{code} {description}".strip()
        body = ""
        content = resolved.get("content", {}) if isinstance(resolved, dict) else {}
        media = content.get("application/json") if isinstance(content, dict) else None
        if isinstance(media, dict):
            if "example" in media:
                body = json.dumps(media["example"], ensure_ascii=False, indent=2)
            elif "schema" in media:
                schema = resolve_refs(openapi, media["schema"])
                body = json.dumps(example_from_schema(schema), ensure_ascii=False, indent=2)
        responses.append(
            {
                "name": status_name,
                "status": description or status_name,
                "code": int(code) if str(code).isdigit() else 0,
                "header": [{"key": "Content-Type", "value": "application/json"}] if body else [],
                "body": body,
            }
        )
    return responses


def example_from_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return None
    if "const" in schema:
        return schema["const"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), "null")
    if schema_type == "object" or "properties" in schema:
        return {key: example_from_schema(value) for key, value in schema.get("properties", {}).items()}
    if schema_type == "array":
        return [example_from_schema(schema.get("items", {}))]
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 1
    if schema_type == "boolean":
        return True
    if schema.get("format") == "date-time":
        return "2026-09-20T12:00:00Z"
    if schema.get("format") == "date":
        return "2026-09-20"
    if schema.get("format") == "uri":
        return "https://example.local/resource"
    return "string"


def create_item_from_operation(openapi: dict[str, Any], method: str, path: str, operation: dict[str, Any], service_name: str) -> dict[str, Any]:
    schema = operation_request_schema(openapi, operation)
    example = operation_request_example(operation)
    raw_url = base_url_variable_for_service(service_name) + postman_path_from_openapi(path)
    request: dict[str, Any] = {
        "method": method,
        "header": [],
        "url": raw_url,
    }
    generated_description = operation_description(operation, schema)
    if generated_description:
        request["description"] = generated_description
    if schema:
        ensure_raw_json_body(request, schema, example)
    if operation.get("security"):
        merge_request_header(request, "Authorization", "Bearer {{access_token}}")
    merge_openapi_header_parameters(request, operation)
    normalize_request_headers(request)

    item = {
        "name": display_name_for_operation(method, path, operation),
        "request": request,
        "response": response_examples_from_openapi(openapi, operation),
    }
    normalize_health_response_examples(item, service_name)
    return item


def header_parameter_value(parameter: dict[str, Any]) -> str:
    if "example" in parameter:
        return str(parameter["example"])
    schema = parameter.get("schema")
    if isinstance(schema, dict):
        if "default" in schema:
            return str(schema["default"])
        if "example" in schema:
            return str(schema["example"])
    if parameter.get("name") == "Idempotency-Key":
        return "{{$guid}}"
    return ""


def merge_request_header(request: dict[str, Any], key: str, value: str, description: str | None = None) -> None:
    headers = request.setdefault("header", [])
    if not isinstance(headers, list):
        request["header"] = headers = []

    for header in headers:
        if isinstance(header, dict) and str(header.get("key", "")).lower() == key.lower():
            if not header.get("value") and value:
                header["value"] = value
            if description and not header.get("description"):
                header["description"] = description
            return

    new_header = {"key": key, "value": value}
    if description:
        new_header["description"] = description
    headers.append(new_header)


def merge_openapi_header_parameters(request: dict[str, Any], operation: dict[str, Any]) -> None:
    parameters = operation.get("parameters", [])
    if not isinstance(parameters, list):
        return

    for parameter in parameters:
        if not isinstance(parameter, dict) or parameter.get("in") != "header":
            continue
        name = parameter.get("name")
        if not isinstance(name, str) or not name:
            continue
        description = parameter.get("description")
        merge_request_header(
            request,
            name,
            header_parameter_value(parameter),
            description if isinstance(description, str) else None,
        )


def normalize_request_headers(request: dict[str, Any]) -> None:
    headers = request.get("header", [])
    if not isinstance(headers, list):
        request["header"] = []
        return

    auto_managed = {"content-type", "accept"}
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []

    for header in headers:
        if not isinstance(header, dict):
            continue
        key = str(header.get("key", "")).strip()
        if not key:
            continue
        key_lower = key.lower()
        if key_lower in auto_managed:
            continue
        if key_lower in seen:
            continue
        seen.add(key_lower)
        normalized.append(header)

    request["header"] = normalized


def service_code_from_name(service_name: str) -> str:
    for code, name in {
        "OMS1": "OMS1 Auth Service",
        "OMS2": "OMS2 Employee Service",
        "OMS3": "OMS3 Report Service",
        "OMS4": "OMS4 Notification Service",
        "OMS5": "OMS5 Operations Service",
    }.items():
        if service_name == name:
            return code
    return "OMS"


def service_name_from_request(request: dict[str, Any]) -> str:
    marker = request_service_marker(request)
    for service_name, variable in SERVICE_BASE_URL_VARIABLES.items():
        if marker == variable:
            return service_name
    return ""


def health_example(service_code: str, path: str, status_code: int) -> dict[str, Any]:
    if path.endswith("/ready") or path.endswith("/ready/"):
        status_value = "ok" if status_code == 200 else "failed"
        checks: dict[str, Any]
        if service_code == "OMS1":
            checks = {"jwt": {"status": status_value}, "kafka": {"status": status_value, "endpoint": "kafka.oms.svc.cluster.local:9092"}}
        elif service_code == "OMS2":
            checks = {"database": {"status": status_value}, "kafka": {"status": status_value, "endpoint": "kafka.oms.svc.cluster.local:9092"}}
        elif service_code == "OMS4":
            checks = {
                "kafka": {"status": status_value, "endpoint": "kafka.oms.svc.cluster.local:9092"},
                "smtp": {"status": "failed", "endpoint": "mailhog:1025", "required": False},
            }
        else:
            checks = {"kafka": {"status": status_value, "endpoint": "kafka.oms.svc.cluster.local:9092"}}
        return {"status": status_value, "service": service_code, "checks": checks}

    if path.endswith("/live") or path.endswith("/live/"):
        return {"status": "ok", "service": service_code, "checks": {"app": {"status": "ok"}}}

    return {"status": "ok", "service": service_code}


def normalize_health_response_examples(item: dict[str, Any], service_name: str | None = None) -> None:
    request = item.get("request")
    if not isinstance(request, dict):
        return
    path = normalize_path(request_url_raw(request))
    if path not in {"/health", "/health/", "/health/live", "/health/live/", "/health/ready", "/health/ready/"}:
        return

    resolved_service_name = service_name or service_name_from_request(request)
    service_code = service_code_from_name(resolved_service_name)
    for response in item.get("response", []) or []:
        if not isinstance(response, dict) or response.get("code") not in {200, 503}:
            continue
        response["body"] = json.dumps(health_example(service_code, path, int(response["code"])), ensure_ascii=False, indent=2)


def append_missing_openapi_operations(collection: dict[str, Any], openapi: dict[str, Any]) -> None:
    existing = collection_operation_keys(collection.get("item", []))
    existing_by_service = collection_operation_keys_by_service(collection.get("item", []))
    for method, path, operation in iter_openapi_operations(openapi):
        postman_services = operation.get("x-postman-services")
        if isinstance(postman_services, list) and postman_services:
            for service_name in postman_services:
                if not isinstance(service_name, str):
                    continue
                service_marker = base_url_variable_for_service(service_name)
                service_key = (method, service_marker, path)
                if service_key in existing_by_service:
                    continue
                service_folder = ensure_service_folder(collection, service_name)
                target_folder = ensure_healthcheck_folder(service_folder) if path.startswith("/health") else service_folder
                target_folder.setdefault("item", []).append(create_item_from_operation(openapi, method, path, operation, service_name))
                existing_by_service.add(service_key)
                existing.add((method, path))
            continue

        key = (method, path)
        if key in existing:
            continue
        service_name = service_name_for_operation(path, operation)
        service_folder = ensure_service_folder(collection, service_name)
        target_folder = ensure_healthcheck_folder(service_folder) if path.startswith("/health") else service_folder
        target_folder.setdefault("item", []).append(create_item_from_operation(openapi, method, path, operation, service_name))
        existing.add(key)


def remove_duplicate_operation_items(items: list[dict[str, Any]], seen: set[tuple[str, str, str]] | None = None) -> None:
    if seen is None:
        seen = set()

    deduped: list[dict[str, Any]] = []
    for item in items:
        if "item" in item and isinstance(item["item"], list):
            remove_duplicate_operation_items(item["item"], seen)
            deduped.append(item)
            continue

        request = item.get("request")
        if isinstance(request, dict):
            key = (
                str(request.get("method", "GET")).upper(),
                request_service_marker(request),
                normalize_path(request_url_raw(request)),
            )
            if key in seen:
                continue
            seen.add(key)

        deduped.append(item)

    items[:] = deduped


def operation_request_schema(openapi: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any] | None:
    request_body = operation.get("requestBody")
    if not isinstance(request_body, dict):
        return None

    content = request_body.get("content", {})
    media_type = content.get("application/json") if isinstance(content, dict) else None
    if not isinstance(media_type, dict) or "schema" not in media_type:
        return None

    return resolve_refs(openapi, media_type["schema"])


def operation_request_example(operation: dict[str, Any]) -> Any:
    request_body = operation.get("requestBody")
    if not isinstance(request_body, dict):
        return None
    content = request_body.get("content", {})
    media_type = content.get("application/json") if isinstance(content, dict) else None
    if not isinstance(media_type, dict):
        return None
    if "example" in media_type:
        return media_type["example"]
    examples = media_type.get("examples")
    if isinstance(examples, dict) and examples:
        first = next(iter(examples.values()))
        if isinstance(first, dict):
            return first.get("value")
    return None


def schema_markdown(schema: dict[str, Any]) -> str:
    return "### Request JSON Schema\n```json\n" + json.dumps(schema, ensure_ascii=False, indent=2) + "\n```"


def operation_description(operation: dict[str, Any], schema: dict[str, Any] | None) -> str:
    parts: list[str] = []
    summary = operation.get("summary")
    description = operation.get("description")
    if isinstance(summary, str) and summary:
        parts.append(f"### {summary}")
    if isinstance(description, str) and description:
        parts.append(description)
    if schema:
        parts.append(schema_markdown(schema))
    return "\n\n".join(parts)


def merge_description(item: dict[str, Any], request: dict[str, Any], generated_description: str) -> None:
    current_item_description = item.get("description")
    current_request_description = request.get("description")

    if generated_description.strip():
        base = generated_description.strip()
    elif isinstance(current_request_description, str) and current_request_description.strip():
        base = current_request_description.strip()
    elif isinstance(current_item_description, str) and current_item_description.strip():
        base = current_item_description.strip()
    else:
        base = ""

    # Replace a stale schema block with the OpenAPI-generated block while
    # preserving the hand-written narrative above it.
    if generated_description and "### Request JSON Schema" in generated_description:
        generated_schema_block = generated_description.split("### Request JSON Schema", 1)[1]
        generated_schema_block = "### Request JSON Schema" + generated_schema_block
        if "### Request JSON Schema" in base:
            base = base.split("### Request JSON Schema", 1)[0].rstrip()
        if base:
            base = f"{base}\n\n{generated_schema_block}"
        else:
            base = generated_schema_block

    if base:
        request["description"] = base

    # Postman Docs renders request.description more consistently than
    # item.description. Keep a single source in the collection to avoid drift.
    item.pop("description", None)


def ensure_raw_json_body(request: dict[str, Any], schema: dict[str, Any] | None, example: Any) -> None:
    if schema is None:
        return

    body = request.setdefault("body", {})
    body["mode"] = "raw"

    if example is not None:
        body["raw"] = json.dumps(example, ensure_ascii=False, indent=2)
    elif not body.get("raw"):
        body["raw"] = "{}"

    options = body.setdefault("options", {})
    raw_options = options.setdefault("raw", {})
    raw_options["language"] = "json"
    # Kept for forward compatibility and external tooling. Postman UI currently
    # displays schemas from OpenAPI imports, not reliably from collections.
    raw_options["schema"] = schema


def update_item_from_openapi(item: dict[str, Any], openapi: dict[str, Any], operations: dict[tuple[str, str], dict[str, Any]]) -> None:
    request = item.get("request")
    if not isinstance(request, dict):
        return

    method = str(request.get("method", "GET")).upper()
    path = normalize_path(request_url_raw(request))
    operation = operations.get((method, path))
    if operation is None:
        return

    schema = operation_request_schema(openapi, operation)
    example = operation_request_example(operation)
    generated_description = operation_description(operation, schema)

    merge_description(item, request, generated_description)
    ensure_raw_json_body(request, schema, example)
    merge_openapi_header_parameters(request, operation)
    normalize_request_headers(request)
    normalize_health_response_examples(item)


def walk_items(items: list[dict[str, Any]], openapi: dict[str, Any], operations: dict[tuple[str, str], dict[str, Any]]) -> None:
    for item in items:
        if "item" in item and isinstance(item["item"], list):
            walk_items(item["item"], openapi, operations)
        else:
            update_item_from_openapi(item, openapi, operations)


def generate_collection(openapi: dict[str, Any], overlay: dict[str, Any], *, from_scratch: bool = False) -> dict[str, Any]:
    collection = copy.deepcopy(overlay)
    operations = build_operation_index(openapi)
    walk_items(collection.get("item", []), openapi, operations)
    remove_duplicate_operation_items(collection.get("item", []))
    append_missing_openapi_operations(collection, openapi)

    overlay_note = "without overlay. " if from_scratch else "with examples/scripts preserved from the Postman collection overlay. "
    collection.setdefault("info", {})["description"] = (
        "Generated from platform/contracts/openapi_oms_microservices.json "
        f"{overlay_note}OpenAPI is the source of truth for request body schemas."
    )
    return collection


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openapi", type=Path, default=DEFAULT_OPENAPI)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_COLLECTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_COLLECTION)
    parser.add_argument(
        "--from-scratch",
        action="store_true",
        help="Create the Postman collection from OpenAPI only and ignore --overlay.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    openapi = load_json(args.openapi)
    overlay = empty_collection(openapi) if args.from_scratch else load_json(args.overlay)
    collection = generate_collection(openapi, overlay, from_scratch=args.from_scratch)
    write_json(args.output, collection)


if __name__ == "__main__":
    main()
