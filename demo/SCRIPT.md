# STRATA: сценарий видео для ICSE 2027 Tool Demonstration

Страница: `demo/strata_scroll_demo.html` (одна страница с прокруткой). Все выводы терминала на странице — настоящие прогоны `strata` CLI на реальных данных, интерактивные части пересчитываются в браузере.

## Что ждёт трек

По CFP ICSE 2027 Tool Demonstration and Data Showcase: видео 3–5 минут на YouTube, ссылка в конце abstract, качество видео оценивается отдельно. По ICSE 2026 Demonstrations: показать целевых пользователей, задачу, рабочий процесс и результаты проверки. В сценарии это сцены 1–2 (пользователи и задача), 3–8 (рабочий процесс), 9 (проверка).

## Подготовка

1. Chrome, окно 1920×1080, масштаб 110 %. Открыть страницу, прокрутить в самый верх.
2. Включить подсветку кликов в программе записи, курсор крупный.
3. Темп речи около 145 слов в минуту; после каждого действия пауза в 1 секунду.
4. Звук пишется отдельно, без музыки. Субтитры для YouTube загрузить из текста ниже.
5. Перед записью один раз пройти раздел «Features» до конца и перезагрузить страницу, чтобы шрифты были в кэше.

## Сцены

### 1. Проблема (0:00–0:22)
**Действие:** страница вверху, курсор не двигать.
> Coding agents now write whole machine-learning pipelines over relational data. The code runs, the tests pass and the score looks good. A model built to predict what happens after a date t can still use facts that only appeared after t. Such a model fails once it is deployed, and nothing in the code or the metrics shows why.

### 2. Пять мест (0:22–0:45)
**Действие:** клик «Layers» в верхнем меню. Курсор медленно по пяти строкам слева, затем на формулу справа.
> The future can get in at five places: the task table, the features, the model's training rows, the examples given to an LLM, and the agent's own knowledge of the entities. A check of one place passes a pipeline that leaks in another. STRATA checks all five with one rule, without reading the code: the output on the full database must equal the output on the database as it was at t.

### 3. Время t (0:45–1:10)
**Действие:** клик «Time». Медленно тянуть ползунок от 2017-10 к 2018-01-01: таблица справа переходит в LEAK, на графике появляется красный квадрат. Затем к 2018-05 и обратно на 2018-01-01.
> One product from the Olist marketplace, its orders and their reviews. As t moves forward, more orders lie in the past. A feature that counts reviews of past orders also counts this red review, written after t. In the database as it was at t, the review does not exist, so the two counts differ: four against three. That difference is the witness STRATA reports.

### 4. Схема (1:10–1:38)
**Действие:** клик «Schema». Нажать «Rules only», затем «With the LLM agent». Кликнуть таблицу orders, затем reviews. Курсор на жёлтый блок с вопросом.
> STRATA needs to know, for each table, when a row appears and which values arrive later. strata init drafts this schema from the raw files. Rules based on names and dates miss columns that are overwritten with the latest value, such as the order status. An optional LLM agent proposes each decision with a reason, STRATA tests it against the data, and open questions go to the person who knows the data.

### 5. Признаки (1:38–2:30)
**Действие:** клик «Features». Нажать «Run check», дождаться карточки LEAK, курсор на таблицу свидетелей и на подсвеченную строку кода. Нажать «Apply fix», затем «Run check again», дождаться CLEAN. Выбрать «Program that reads order_status», нажать «Run check», дождаться UNCHECKABLE, курсор на объяснение.
> A code model wrote this feature program. Running the check: LEAK. The witness names the product, the time, both values, and the table the difference came from: reviews. The suggested fix cuts reviews at their creation date. After the fix, the program gives the same result on the full data and on the data as of every tested time, so the verdict is CLEAN. A second program filters orders by their status. Olist keeps only the latest status, so the status at t cannot be rebuilt from the data. The program may be correct or may leak, and the data cannot tell which. STRATA reports UNCHECKABLE instead of a false CLEAN.

### 6. Модель (2:30–3:00)
**Действие:** клик «Model». Курсор на верхние строки графика (самые большие сдвиги), затем на строку с AUC. Нажать «By driver», потом «Largest change first».
> The model layer. A coding agent wrote a training script for a RelBench Formula 1 task: will each driver qualify in the top three within a month? STRATA runs the script as it is, once with the race results known at the prediction time and once with 412 later results added. Grey is the prediction without the later results, red is with them. Predictions move by up to 0.87, and the quality of the model jumps from 0.71 to 0.93. A high score alone proves nothing.

### 7. Агент (3:00–3:28)
**Действие:** клик «Identity». Script A: три столбца совпадают, вердикт CLEAN. Нажать «Script B: Event users»: красные ячейки, вердикт UNCHECKABLE, курсор на текст справа.
> The agent layer asks whether a model recognises who an entity is instead of learning from the data. STRATA replaces every ID with a made-up one and keeps everything else. Script A gives the same predictions, so it is CLEAN. Script B turns the ID text into numbers, so even the two made-up renamings disagree. That is a dependence on how IDs are written, not knowledge of real users, and STRATA reports UNCHECKABLE rather than a false alarm.

### 8. Задача (3:28–3:46)
**Действие:** клик «Features», прокрутить до подраздела «4.3 Can the task table itself leak?», нажать «show». Курсор на красные даты в колонке «Signed up».
> The task table itself can leak. These three rows predict customers on June first, but the customers sign up later. A row like this tells the model that the customer will exist. STRATA compares every task row with the customer's creation date from the schema and names each one.

### 9. Результаты (3:46–4:35)
**Действие:** клик «Results». Переключать карточки детекторов слева направо: «Cut rows at t» → «Also hide late dates» → «Features only» → «Any change is a leak» → «STRATA», на каждой задержаться на строке под таблицей. В «7.2 The changed pipelines» выбрать «Hand label: harmless», затем «Kind of change: drop_cutoff». Курсор на таблицу «7.4 Three more corpora».
> STRATA was tested on eight databases with known answers. In each reference pipeline, one time comparison was changed at a time, and every changed version was labelled by hand as a leak or as harmless. Cutting rows at t finds 11 of 25 leaking programs. Hiding late dates finds 16, and both miss every overwritten value. Checking features only catches 8 of 43 leaking changes. Treating any change as a leak also flags all 55 harmless ones. STRATA finds every leak and flags no harmless change. On code written by models and agents, it found 16 leaks that a checker built for one database had passed, and all 27 agent training runs learn from rows after t.

Итого около 4:35. Если запись выходит длиннее 5:00, в сценах 5 и 9 оставить первые три предложения.

## Перед загрузкой

- На кадрах нет личных путей и ключей API.
- YouTube: доступ по ссылке или открытый. Название: «STRATA: layer-by-layer point-in-time checks for ML pipelines (ICSE 2027 demo)».
- Ссылку вставить в конец abstract (`\todo{video URL}` в `paper/main (1).tex`).

## Пересборка страницы

Скрипты `capture.py`, `capture_data.py`, `build.py` в репо пока не лежат; команды ниже ждут их в `demo/`.

```bash
python demo/capture.py        # перезапускает команды STRATA -> scenes.json
python demo/capture_data.py   # данные интерактивных частей -> data.json
python demo/build.py          # встраивает всё в index.html
cp demo/index.html demo/strata_scroll_demo.html
```
