# STRATA, альтернативное демо: сценарий видео (ICSE 2027 Tool Demonstration)

Идея: один рабочий интерфейс на весь ролик.
Слева редактор кода, справа диагноз и консоль. Все выводы консоли: настоящие
прогоны `strata` CLI (перенесены из `demo/strata_scroll_demo.html`).

Страницы:

| Файл | Что это |
|---|---|
| `demo/alt/about.html` | проектная страница в формате вопросов и ответов, большая кнопка «Open the demo», ссылки на код, статью, видео, PITBench, скилл |
| `demo/alt/index.html` | рабочий стол: база, пример, «Run check», «Schema», «What is STRATA?», «Download skill» |
| `demo/alt/data.js` | записанные прогоны, программы, схема Olist с обоснованиями LLM, предсказания модели и агента, таблица PITBench, текст SKILL.md |
| `demo/alt/scenes.json` | текст сцен для озвучки в формате скилла `video-voiceover` |

Примеры в интерфейсе (все с записанными прогонами):

| База | Пример | Слой | Вердикт |
|---|---|---|---|
| Olist | Product features written by a code model | features | LEAK, затем Apply fix |
| Olist | Same program after the fix | features | CLEAN |
| Olist | Features that drop cancelled orders | features | UNCHECKABLE |
| RelBench F1 | Agent-written training script | model | LEAK, график по гонщикам |
| RelBench F1 | Same script, agent check | agent | CLEAN |
| RelBench Event | Script that turns user IDs into numbers | agent | UNCHECKABLE |
| Shop | Prediction table with customers who do not exist yet | task | LEAK |

Глубокие ссылки для записи и отладки: `index.html?ex=leaky&run=1`,
`?ex=fixed&run=1`, `?ex=status&run=1`, `?ex=model&run=1`, `?ex=agent&run=1`,
`?ex=agent_hashed&run=1`, `?ex=task&run=1`, `?modal=about`,
`?modal=schema&mode=llm`.

## Что ждёт трек

Видео 3–5 минут на YouTube, ссылка в конце abstract. Показать целевых
пользователей, задачу, рабочий процесс и результаты. Здесь: сцена 1 (задача),
2–9 (рабочий процесс), 10 (результаты).

## Подготовка

1. Открыть `demo/alt/` через любой статический сервер
   (`python3 -m http.server 8766 --directory demo/alt`), Chrome 1920×1080, масштаб 100 %.
2. Подсветка кликов в программе записи, курсор крупный. После каждого клика пауза в 1 секунду.
3. Звук пишется отдельно скиллом `video-voiceover` по `scenes.json`; длина каждой сцены
   в монтаже равна длине её звука (`durations.json`).
4. Перед записью один раз пройти все примеры, чтобы шрифты были в кэше, и перезагрузить.

## Сцены

Текст сцен совпадает с `scenes.json`; здесь действия и ориентировочный хронометраж
при 145 словах в минуту. Всего около 420 слов, 2:50–3:00.

### 1. Проектная страница (0:00–0:18)
**Действие:** `about.html`, верх страницы, курсор не двигать.
> Your pipeline may be peeking at the future, and STRATA shows you where. Coding agents now write whole pipelines over time-stamped data. The code runs, the score looks good, and the model can still use facts that appeared after the prediction time. STRATA runs the code on the data as it is and on the data as it was at time t, and reports where the two disagree.

### 2. Рабочий стол (0:18–0:32)
**Действие:** клик «Open the demo». Открывается `index.html` с `feature_program.py`. Курсор медленно слева направо: редактор, диагноз, консоль.
> This is the workbench. On the left, a feature program that a code model wrote for the Olist marketplace. On the right, the diagnosis and a console. Every console output is a recorded strata run on the real data.

### 3. LEAK (0:32–0:50)
**Действие:** клик «Run check». Команда печатается, вывод, карточка LEAK. Курсор на таблицу свидетелей, затем на подсвеченные строки 38–42 в редакторе.
> Run check. The verdict is leak. The witness names the time, the product, the column, both values, and the table the difference came from: reviews. The program cuts orders at t, but joins every review, including reviews written later.

### 4. Фикс и CLEAN (0:50–1:06)
**Действие:** клик «Apply fix»: редактор прыгает к зелёным строкам. Клик «Run check». Карточка CLEAN с таблицей 3×3.
> The suggested fix cuts reviews at their creation date. Apply it and run again. Clean at every tested time, for the witness run, for the canary with a rewritten future, and for the unknown-column probe.

### 5. UNCHECKABLE (1:06–1:24)
**Действие:** в «Example» выбрать «Features that drop cancelled orders». Клик «Run check». Курсор на список колонок в карточке.
> A second program drops cancelled orders. Olist keeps only the latest status, so the status at time t cannot be rebuilt from the data. STRATA answers uncheckable and lists the output columns that depend on it.

### 6. Схема (1:24–1:42)
**Действие:** клик «Schema». Клик «With the LLM agent». Клик по таблице `orders`. Курсор на текст обоснования, затем на строку `order_status`, snapshot. Закрыть.
> Where does STRATA know this from? From the availability schema, drafted from the raw files. With the LLM agent, every decision comes with a reason, and the order status is marked as a snapshot that is valid only at the end of the data.

### 7. Модель (1:42–2:06)
**Действие:** «Database» → RelBench F1, пример «Agent-written training script». Клик «Run check». Курсор на верхние строки графика, затем на строку с AUC.
> The model layer. An agent-written training script for RelBench Formula One, run exactly as it is, with and without the four hundred and twelve race results that came after t. Predictions move by up to zero point eight seven, and the AUC jumps from zero point seven one to zero point nine three. The metric alone would have missed this.

### 8. Агент (2:06–2:24)
**Действие:** «Database» → RelBench Event, единственный пример. Клик «Run check». Курсор на красные ячейки.
> The agent layer replaces every ID with a made-up one, twice. This script turns the IDs into numbers, so the two renamings disagree with each other. The output depends on the spelling of the ID, identity recall cannot be separated from that, and the answer is uncheckable.

### 9. Задача (2:24–2:32)
**Действие:** «Database» → Shop. Клик «Run check». Курсор на красные даты.
> The task table itself can leak. These three rows predict customers who only sign up later, and STRATA names each one.

### 10. Результаты и скилл (2:32–2:52)
**Действие:** клик «What is STRATA?». Прокрутить до таблицы результатов. Клик «Download SKILL.md», всплывает подтверждение. Конец.
> On eight databases with known answers, STRATA catches all forty-three leaking code changes and flags none of the fifty-five harmless ones. Download the skill file, and your coding agent runs the check before it reports a score.

Если запись выходит длиннее 3:30, убрать сцены 8 и 9.

## Перед загрузкой

- На кадрах нет личных путей и ключей API (консоль показывает укороченные пути).
- Ссылки «GitHub», «Paper», «Video» на обеих страницах пока ведут в `#`: вписать URL
  в `index.html` (`#lnkRepo`, `#lnkPaper`, `#lnkRepo2`, `#lnkPaper2`) и `about.html`
  (`#repo`, `#paper`, `#video`).
- YouTube: доступ по ссылке или открытый. Название: «STRATA: layer-by-layer point-in-time checks for ML pipelines (ICSE 2027 demo)».
- Ссылку вставить в конец abstract (`\todo{video URL}` в `paper/main (1).tex`).

## Пересборка данных

`data.js` собран из вшитых данных `demo/strata_scroll_demo.html` и `SKILL.md`.
Если прогоны перезаписываются, обновить константы `REC`, `PROG`, `TIMELINE`, `MODEL`,
`AGENT`, `SCHEMA`, `OLIST_KEYS`, `PB`, `SKILL` в том же формате.
