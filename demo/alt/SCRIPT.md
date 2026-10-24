# STRATA, альтернативное демо: сценарий видео (ICSE 2027 Tool Demonstration)

Идея: ролик идёт с проектной страницы (лендинга) в рабочий стол с записанными
прогонами и заканчивается финальной карточкой. Все выводы консоли в рабочем
столе: настоящие прогоны `strata` CLI.

Страницы:

| Файл | Что это |
|---|---|
| `demo/alt/about.html` | проектная страница: название статьи, слайдер по одному продукту, пять слоёв, правило, схема, результаты, ссылки |
| `demo/alt/index.html` | рабочий стол: база, пример, «Run check», «Schema», «Download skill», тумблер Recorded/Live |
| `demo/alt/live.html`, `live_glue.py`, `data/olist/` | живой запуск: модель по ключу OpenRouter пишет программу или схему, проверка STRATA идёт в браузере (Pyodide) на выборке из 3000 заказов Olist; в ролик не входит |
| `demo/alt/end.html` | финальная карточка |
| `demo/alt/data.js` | записанные прогоны, программы, схема Olist с обоснованиями LLM, предсказания модели и агента, текст SKILL.md |
| `demo/alt/scenes.json` | текст сцен для озвучки в формате скилла `video-voiceover` |

Все страницы открывать с сервера от корня репо:
`python3 -m http.server 8767`, затем `http://127.0.0.1:8767/demo/alt/about.html`.

Глубокие ссылки для отладки рабочего стола: `index.html?ex=leaky&run=1`,
`?ex=fixed&run=1`, `?ex=status&run=1`, `?ex=model&run=1`, `?ex=agent&run=1`,
`?ex=agent_hashed&run=1`, `?ex=task&run=1`, `?modal=schema&mode=llm`.

## Что ждёт трек

Видео 3–5 минут на YouTube, ссылка в конце abstract. Показать целевых
пользователей, задачу, рабочий процесс и результаты. Здесь: сцены 1–4 (задача
и результаты, лендинг), 5–11 (рабочий процесс, рабочий стол), 12 (карточка).

## Подготовка

1. Chrome 1920×1080, масштаб 100 %. Три вкладки заранее: `about.html` (вверху),
   `index.html`, `end.html`. Переходы между вкладками монтируются встык.
2. Подсветка кликов в программе записи, курсор крупный. После каждого клика пауза в 1 секунду.
   Прокрутка лендинга плавная, колесом, без рывков.
3. Звук пишется отдельно скиллом `video-voiceover` по `scenes.json`; длина каждой сцены
   в монтаже равна длине её звука (`durations.json`).
4. Перед записью один раз пройти все примеры рабочего стола, чтобы шрифты были в кэше,
   и перезагрузить страницы.

## Сцены

Текст сцен совпадает с `scenes.json`; здесь действия и ориентировочный хронометраж
при 145 словах в минуту. Всего около 500 слов, 3:20–3:30.

### Лендинг

### 1. Заголовок (0:00–0:16)
**Действие:** `about.html`, верх страницы: название статьи, подзаголовок, авторы. Курсор не двигать.
> STRATA is a point-in-time checker for machine learning pipelines over time-stamped relational data, made for code that coding agents write. It runs the code on the data as it is and on the data as it was at prediction time, and reports where the two disagree.

### 2. Слайдер (0:16–0:38)
**Действие:** прокрутить до слайдера. Медленно тянуть t от 2017-10 к 2018-01-01: отзыв краснеет, в таблице 4 против 3, вердикт LEAK.
> One product from the Olist marketplace, its orders and their reviews. A feature that counts reviews of past orders also counts this review, written after t. In the data as of t, it does not exist yet: four against three. That difference is the witness STRATA reports.

### 3. Пять слоёв и правило (0:38–0:58)
**Действие:** прокрутить до таблицы слоёв, курсор по пяти строкам, затем до правила крупным шрифтом.
> The future can get in at five places: the task table, the features, the training rows of the model, the examples given to a language model, and the agent's own memory of the entities. One rule covers all five: the output on the full database must equal the output on the database as of t.

### 4. Схема и результаты, переход (0:58–1:18)
**Действие:** прокрутить мимо команд до таблицы «Results», задержаться на первой строке. Вернуться наверх, клик «Open the demo».
> All STRATA needs is one short schema per database, drafted from the raw files and reviewed once. On eight benchmark databases it caught all forty-three leaking code changes and flagged none of the fifty-five harmless ones. Now the demo.

### Рабочий стол

### 5. Обзор (1:18–1:30)
**Действие:** открывается `index.html` с `feature_program.py`. Курсор медленно: редактор, диагноз, консоль.
> The workbench. On the left, a feature program that a code model wrote for Olist. On the right, the diagnosis and a console. Every console output is a recorded strata run on the real data.

### 6. LEAK (1:30–1:46)
**Действие:** клик «Run check». Команда печатается, вывод, карточка LEAK. Курсор на первую строку свидетелей, затем на подсвеченные строки редактора.
> Run check. The verdict is leak. The witness names the time, the product, the column, both values, and the table the difference came from: reviews. The program cuts orders at t, but joins every review, including the ones written later.

### 7. Фикс и CLEAN (1:46–2:00)
**Действие:** клик «Apply fix»: редактор прыгает к зелёным строкам. Клик «Run check». Карточка CLEAN с таблицей 3×3.
> The suggested fix cuts reviews at their creation date. Apply it, run again. Clean at every tested time, for the witness run, for the canary with a rewritten future, and for the unknown-column probe.

### 8. UNCHECKABLE (2:00–2:16)
**Действие:** в «Example» выбрать «Features that drop cancelled orders». Клик «Run check». Курсор на список колонок.
> A second program drops cancelled orders. Olist keeps only the latest status, so the status at t cannot be rebuilt from the data. STRATA answers uncheckable and lists the output columns that depend on it.

### 9. Схема (2:16–2:32)
**Действие:** клик «Schema». Клик «With the LLM agent». Клик по таблице `orders`. Курсор на обоснование, затем на строку `order_status`, snapshot. Закрыть.
> The schema behind these verdicts is drafted from the raw files. With the language model agent, every decision comes with a reason, and the order status is marked as a snapshot, valid only at the end of the data.

### 10. Модель (2:32–2:56)
**Действие:** «Database» → RelBench F1, пример «Agent-written training script». Клик «Run check». Курсор на верхние строки графика, затем на строку с AUC.
> The model layer. A training script written by a coding agent for RelBench Formula One, run exactly as it is, with and without the four hundred and twelve race results that came after t. Predictions move by up to zero point eight seven, and the AUC jumps from zero point seven one to zero point nine three. The metric alone would have missed this.

### 11. Агент (2:56–3:08)
**Действие:** «Database» → RelBench Event. Клик «Run check». Курсор на красные ячейки.
> The agent layer replaces every ID with a made-up one, twice. This script turns the IDs into numbers, so the two renamings disagree, and the answer is uncheckable.

### Финал

### 12. Карточка (3:08–3:24)
**Действие:** `end.html`, держать кадр до конца фразы, затем 2 секунды тишины.
> Five layers, one rule, and exit codes a coding agent can act on. Install STRATA, draft the schema, drop the skill file into your agent, and it runs the check before it reports a score.

Если запись выходит длиннее 4:00, убрать сцену 11.

## Перед загрузкой

- На кадрах нет личных путей и ключей API (консоль показывает укороченные пути).
- Ссылки «GitHub», «Paper», «Video» на страницах пока ведут в `#`: вписать URL в
  `index.html` и `live.html` (`#lnkRepo`, `#lnkPaper`), `about.html` (`#repo`, `#paper`,
  `#video`) и в подвал `end.html`.
- YouTube: доступ по ссылке или открытый. Название: «STRATA: layer-by-layer point-in-time checks for ML pipelines (ICSE 2027 demo)».
- Ссылку вставить в конец abstract (`\todo{video URL}` в `paper/main (1).tex`).

## Пересборка данных

`data.js` собран из вшитых данных `demo/strata_scroll_demo.html` и `SKILL.md`.
Если прогоны перезаписываются, обновить константы `REC`, `PROG`, `TIMELINE`, `MODEL`,
`AGENT`, `SCHEMA`, `OLIST_KEYS`, `PB`, `SKILL` в том же формате.
