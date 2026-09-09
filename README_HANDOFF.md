# PAP2 4.5.0 — slice 2: CONTROL_AGENT reconciliation-plan server correction

Полный контекст — в `PAP2_S2_HANDOFF.md`. Авторитетны фактические исходники,
карта и дизайн этого дерева. Evidence текущего review лежит в
`review-reconcile-1/`.

## Основание

Последний опубликованный development commit ветки `s2-block25`:

`86dc3b8d03b3c0841c103caed2d8c732d1494994`

Он включает CLEAN S4 и endpoint-CLOSED server correction. `main` остаётся на
`8fc773ce531100fb6e0765dfb49a10b3f8b4f2f8`; rollout отсутствует, стенд pro2
остаётся на slice 1.

## Зачем нужен этот кандидат

Extension 2.12.0 должен восстанавливать `profile-session:<sessionId>` reasons из
консоли. В опубликованном сервере `CONTROL_AGENT` выдаёт ownership/lease, но не
выдаёт reconciliation plan. Local cache, `/api/endpoints`, legacy `enabledTabs`
или открытые tabs источником истины быть не могут.

Кандидат добавляет `MAP-090`: успешный CONTROL owner получает `reconcilePlan`
с live `ProfileSession` и их enabled `ChatBinding`. Plan read-only и canonical:
сессии сортируются по `sessionId`, bindings по `bindingId`, `revision` —
`sha256:` канонического JSON `{sessions:[...]}`.

Whole-plan fail-closed:

- unreadable/malformed ProfileSession;
- две live session одного profile;
- повреждённый ChatBinding store/row;
- duplicate/ambiguous binding identity;
- binding.profileId drift

дают `RECONCILE_PLAN_UNPROVABLE` без частичного plan. Missing/deleted и disabled
binding просто не создают reason. Конфликтующая epoch plan не получает.

`ACC-S2-002=PASS`, `ACC-S2-003=PASS`, новая `ACC-S2-039=PASS`. Extension
`MAP-052/055` пока не закрываются этой server correction.

## Проверка

    python -m pytest -q tests/test_slice2_reconcile_plan.py

Ожидается `13 passed`. На неизменённом endpoint-close baseline тот же файл
должен быть RED.

    bash RUN_TESTS.sh

Ожидается `296 passed, 64 subtests passed`, `TESTS_RC=0`.

    python tools/verify_inventory.py
    python tools/verify_overlaps.py
    python tools/verify_map.py

Ожидается соответственно `177/0`, `10/0`, `218/0 VERIFIED_CLEAN`.

Также обязательны `py_compile`, `node --check` и `git diff --check` без
evidence-каталогов.

## Что не входит

- extension Package 1 (`MAP-051/055/052/054`);
- heartbeat/client protocol Package 2;
- `MAP-049`/`MAP-050`;
- rollout/live acceptance.

До независимого CLEAN эту correction не коммитить и не push'ить.
