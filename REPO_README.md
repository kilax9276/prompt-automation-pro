# Prompt Automation Pro 2 — снимок исходников для продолжения разработки

Снимок соответствует **фактически работающему стенду** на 2026-09-05.

## Что здесь

```
server.py, platform_manager.py, activate_console_release.py,
start_platform.sh, install_platform_requirements.sh,
requirements-console.txt, VERSION-platform, README.md
                                платформа pro2, перебрендированная с pro1

console_releases/4.4.0/         консоль 4.4.0 r7 — активный релиз
extension/                      расширение Prompt Automation Pro 2 2.11.6 — установлено
packaging/                      установщик релиза и манифесты
docs/PAP2_4.5.0_DESIGN.md       закрытый дизайн 4.5.0, редакция 34
console-current.json.example    пример маркера активного релиза
```

## Соответствие серверу

```
/home/ext_disk/prompt_automation_pro2/
  server.py, platform_manager.py, ...        = корень этого репозитория
  console_releases/4.4.0/                    = console_releases/4.4.0
  console_releases/4.3.5/                    отсутствует здесь: это база форка,
                                             на сервере остаётся для отката
  runtime/                                   не входит: токен и pid
  data/                                      не входит: Run
  config/                                    не входит: профили, привязки, секреты
```

Расширение на Windows: `d:\work\extentions\prompt_automation_pro2\` = `extension/`.

## Живое состояние стенда

```
pro2   receiver  8867  prompt-automation-pro2-receiver  2.10.0
       консоль   8871  prompt-automation-pro2-console   4.4.0 r7
pro1   receiver  8767  claude-protocol-receiver         2.10.0
       консоль   8771  prompt-automation-console        4.3.5
```

pro1 — отдельный работающий стенд, в 4.5.0 не затрагивается.

## Запуск

```
bash start_platform.sh
```

Скрипт вычисляет корень из своего расположения, создаёт токен при отсутствии,
пишет маркер активного релиза и запускает менеджер платформы, который поднимает
receiver и консоль.

## Правила разработки

Дизайн 4.5.0 закрыт на редакции 34. Архитектурные решения по ходу реализации не
добавляются. Если код делает принятый контракт невыполнимым — срез блокируется,
факт записывается открытой строкой в журнал решений документа.

`executor.py` и `protocol_engine.py` меняются только в ломающем срезе 5.
