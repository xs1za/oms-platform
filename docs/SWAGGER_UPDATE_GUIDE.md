# Swagger UI Update Guide

Эта инструкция описывает, как опубликовать `platform/contracts/openapi_oms_microservices.json` в Swagger UI и как обновлять Swagger после изменения API-контрактов.

## Файлы

- `platform/contracts/openapi_oms_microservices.json` - source of truth для API-контрактов OMS1-OMS5.
- `platform/contracts/postman_oms_microservices_collection.json` - Postman collection, генерируется из OpenAPI плюс overlay.
- `platform/scripts/generate_postman_collection.py` - генератор Postman collection.

## Быстрый Локальный Запуск Swagger UI

Запустите Swagger UI через Docker из корня проекта:

```powershell
docker run --rm `
  --name oms-swagger-ui `
  -p 8088:8080 `
  -e SWAGGER_JSON=/spec/platform/contracts/openapi_oms_microservices.json `
  -v "${PWD}:/spec" `
  swaggerapi/swagger-ui:v5.17.14
```

Откройте:

```text
http://localhost:8088
```

Важно: Docker-образ `swaggerapi/swagger-ui` открывается в корне `/`. URL вида `http://localhost:8088/docs` для этого контейнера не используется. `/docs` - это URL встроенной документации FastAPI-сервиса, если конкретный сервис запущен напрямую.

Если нужен порт `8001`, запустите контейнер с другим port mapping:

```powershell
docker run --rm `
  --name oms-swagger-ui `
  -p 8001:8080 `
  -e SWAGGER_JSON=/spec/platform/contracts/openapi_oms_microservices.json `
  -v "${PWD}:/spec" `
  swaggerapi/swagger-ui:v5.17.14
```

Тогда откройте:

```text
http://localhost:8001
```

Если Docker на Windows не принимает `${PWD}`, используйте абсолютный путь:

```powershell
docker run --rm `
  --name oms-swagger-ui `
  -p 8088:8080 `
  -e SWAGGER_JSON=/spec/platform/contracts/openapi_oms_microservices.json `
  -v "D:/ProjectsDocker/extrawork:/spec" `
  swaggerapi/swagger-ui:v5.17.14
```

## Обновление Swagger UI После Изменения OpenAPI

1. Измените `platform/contracts/openapi_oms_microservices.json`.

2. Проверьте JSON:

```powershell
python -m json.tool platform/contracts/openapi_oms_microservices.json > $null
```

3. Обновите Postman collection, если она используется:

```powershell
python platform/scripts/generate_postman_collection.py
```

4. Проверьте Postman collection:

```powershell
python -m json.tool platform/contracts/postman_oms_microservices_collection.json > $null
```

5. Обновите страницу Swagger UI в браузере.

Если Swagger UI запущен через Docker с volume mount, файл читается из текущей рабочей директории. Обычно достаточно обновить страницу браузера.

Если браузер показывает старую схему, выполните hard refresh:

```text
Ctrl+F5
```

Если это не помогло, перезапустите контейнер Swagger UI.

## Создание Postman Collection С Нуля

Если нужно пересоздать Postman collection только из OpenAPI:

```powershell
python platform/scripts/generate_postman_collection.py `
  --from-scratch `
  --openapi platform/contracts/openapi_oms_microservices.json `
  --output platform/contracts/postman_oms_microservices_collection.json
```

Важно: режим `--from-scratch` не сохраняет ручные Postman scripts, custom examples и mock responses. Для обычной работы используйте overlay-режим:

```powershell
python platform/scripts/generate_postman_collection.py
```

## Авторизация В Swagger UI

Для endpoints с JWT:

1. Выполните request получения токена в `OMS1 Auth Service`.
2. Скопируйте `access_token`.
3. Нажмите `Authorize` в Swagger UI.
4. Введите токен в формате:

```text
Bearer <access_token>
```

5. Нажмите `Authorize`.

## Выбор Сервиса В Swagger UI

В OpenAPI заданы servers для OMS1-OMS5:

- `http://oms.local/oms1`
- `http://oms.local/oms2`
- `http://oms.local/oms3`
- `http://oms.local/oms4`
- `http://oms.local/oms5`

Перед `Try it out` выберите нужный server в верхней части Swagger UI.

Для локального kind/Ingress убедитесь, что в `hosts` есть запись:

```text
127.0.0.1 oms.local
```

## Публикация Swagger UI В Kubernetes

Создайте или обновите ConfigMap со спецификацией:

```powershell
kubectl create configmap oms-openapi `
  --from-file=platform/contracts/openapi_oms_microservices.json `
  -n oms `
  --dry-run=client `
  -o yaml | kubectl apply -f -
```

Пример Deployment и Service для Swagger UI:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oms-swagger-ui
  namespace: oms
spec:
  replicas: 1
  selector:
    matchLabels:
      app: oms-swagger-ui
  template:
    metadata:
      labels:
        app: oms-swagger-ui
    spec:
      containers:
        - name: swagger-ui
          image: swaggerapi/swagger-ui:v5.17.14
          ports:
            - containerPort: 8080
          env:
            - name: SWAGGER_JSON
              value: /openapi/openapi_oms_microservices.json
          volumeMounts:
            - name: openapi
              mountPath: /openapi
              readOnly: true
      volumes:
        - name: openapi
          configMap:
            name: oms-openapi
---
apiVersion: v1
kind: Service
metadata:
  name: oms-swagger-ui
  namespace: oms
spec:
  selector:
    app: oms-swagger-ui
  ports:
    - name: http
      port: 80
      targetPort: 8080
```

После обновления ConfigMap перезапустите pod, чтобы Swagger UI гарантированно увидел новую спецификацию:

```powershell
kubectl rollout restart deployment/oms-swagger-ui -n oms
kubectl rollout status deployment/oms-swagger-ui -n oms
```

Для локального доступа без Ingress можно использовать port-forward:

```powershell
kubectl port-forward service/oms-swagger-ui 8088:80 -n oms
```

Откройте:

```text
http://localhost:8088
```

## CORS Для Try It Out

Swagger UI выполняет `Try it out` из браузера. Если Swagger UI открыт на `http://localhost:8088`, а API вызывается на `http://oms.local`, браузер может заблокировать запрос из-за CORS.

Типичный симптом в Swagger UI:

```text
Undocumented
TypeError: NetworkError when attempting to fetch resource.
```

Если изучение схемы работает, но `Try it out` падает с CORS-ошибкой, используйте один из вариантов:

- включите CORS в OMS-сервисах для origin Swagger UI;
- опубликуйте Swagger UI через тот же host/Ingress, что и API;
- используйте Postman collection для выполнения запросов без браузерных CORS-ограничений.

В текущих манифестах CORS включен на Ingress для локального Swagger UI:

```powershell
kubectl apply -f platform/k8s/ingress.yaml
```

После применения проверьте наличие CORS headers:

```powershell
curl.exe -i -H "Origin: http://localhost:8088" http://oms.local/oms1/health/live
```

В ответе должен быть заголовок:

```text
Access-Control-Allow-Origin: http://localhost:8088
```

## Рекомендуемый Workflow

1. Меняйте API-контракт в `platform/contracts/openapi_oms_microservices.json`.
2. Проверяйте JSON через `python -m json.tool`.
3. Запускайте `python platform/scripts/generate_postman_collection.py`.
4. Обновляйте Swagger UI: refresh браузера, restart контейнера или rollout restart в Kubernetes.
5. Импортируйте обновленные OpenAPI/Postman файлы в Postman при необходимости.
