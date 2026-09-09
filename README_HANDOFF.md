# PAP2 4.5.0 — slice 2: endpoint CLOSED server correction review-candidate

Полный контекст — в `PAP2_S2_HANDOFF.md`. Авторитетны фактические исходники
этого дерева, карта и дизайн; evidence текущего review лежит в `review-close-1/`.

## Основание

Последний опубликованный development commit ветки `s2-block25`:

`04182769f2554483c90162cdd02c9c1c5433304c`

Он соответствует CLEAN S4 Review 2. `main` не сдвинут, rollout отсутствует,
стенд pro2 остаётся на slice 1.

## Зачем нужен этот кандидат

При подготовке extension 2.12.0 обнаружился cross-layer blocker `MAP-053`:
`tabs.onRemoved` обязан сообщать server terminal `CLOSED`, но в S4 сервере
существовал только внутренний `EndpointRegistry.close()` без HTTP route.
Обычный `ENDPOINT` poll использовать нельзя — он означает observe/ONLINE.

Этот кандидат добавляет только минимальную серверную половину:

`POST /api/endpoints/close?extensionVersion=2.12.0&browserEpoch=...&endpointId=...`

Контракт:

- bearer auth обязателен;
- protocol version обязана быть `2.12.0`;
- browserEpoch обязана быть текущим CONTROL owner;
- endpointId обязан принадлежать той же epoch;
- foreign/non-owner отказан до endpoint mutation;
- `CLOSED`/`EXPIRED` terminal и повторный close не переписывает row;
- route не меняет delivery jobs;
- route остаётся доступным при delivery `BARRIER`, потому что это control-plane cleanup.

Карта дополнена `MAP-089`; отдельная server-code acceptance `ACC-S2-038=PASS`.
End-to-end `ACC-S2-020/021` остаются `PLANNED` до extension-side `tabs.onRemoved`.

## Проверка

    python -m pytest -q tests/test_slice2_endpoint_close_route.py

Ожидается `9 passed`.

    bash RUN_TESTS.sh

Ожидается `283 passed, 64 subtests passed`, `TESTS_RC=0`.

    python tools/verify_inventory.py
    python tools/verify_overlaps.py
    python tools/verify_map.py

Ожидается соответственно `177/0`, `10/0`, `216/0 VERIFIED_CLEAN`.

Также обязательны `py_compile`, `node --check` и `git diff --check` без
evidence-каталогов.

## Что не входит

- extension heartbeat correction;
- extension `tabs.onRemoved` implementation;
- `MAP-049`/`MAP-050`;
- rollout/live acceptance.

До независимого CLEAN текущий server correction не коммитить и не push'ить.
