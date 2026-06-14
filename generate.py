# =============================================================================
#  generate.py — ПОЛНЫЙ БАТЧ-ЦИКЛ ПО ВСЕЙ ПАПКЕ INPUT (Этап 7)
#
#  ЧТО ДЕЛАЕТ:
#    - Берёт картинки из INPUT по очереди.
#    - Для каждой: цикл попыток до MAX_ATTEMPTS (логика как на Этапе 6).
#        успех            -> видео в OUTPUT, картинка в DONE;
#        все попытки мимо  -> картинка в FAILED.
#    - Между РАЗНЫМИ картинками — случайная пауза (BATCH_DELAY_MIN/MAX_SEC).
#    - Браузер открывается ОДИН раз на весь батч (быстрее, сессия не теряется).
#    - Весь прогресс пишется И в консоль, И в лог-файл (logs/), см. logger.py.
#    - Цикл сам завершается, когда в INPUT не осталось картинок.
#
#  НАДЁЖНАЯ ЛОГИКА ОДНОЙ ГЕНЕРАЦИИ (после живой диагностики, Этап 6):
#    - Главный сигнал состояния — кнопка "Сгенерировать":
#        disabled = фото не готово ИЛИ генерация идёт;  enabled = сайт готов.
#    - После загрузки картинки ЖДЁМ, пока кнопка станет активной (≈5 сек).
#    - Клик "Сгенерировать" сам ждёт активации, поэтому ФАКТ клика = старт.
#    - Окончание генерации ловим по тому, что кнопка СНОВА стала enabled.
#    - Кнопка "Скачать" появилась -> успех; не появилась -> ошибка -> повтор.
# =============================================================================

import os                                         # работа с путями и файлами
import time                                       # замер времени генерации
import random                                     # случайные задержки
from playwright.sync_api import sync_playwright   # движок браузера

import config                              # все наши настройки и селекторы
from orientation import get_orientation    # определение 16:9 / 9:16 по картинке
from logger import log                     # печать в консоль + запись в лог-файл


# -----------------------------------------------------------------------------
#  ПОМОЩНИК: кортеж-селектор из config -> локатор Playwright.
# -----------------------------------------------------------------------------
def loc(page, name):
    """Берёт селектор по имени из config.SELECTORS и возвращает локатор Playwright."""
    spec = config.SELECTORS[name]
    kind = spec[0]

    if kind == "role":
        # exact=True важно для "Скачать": чтобы не зацепить "Скачать файл" из истории.
        return page.get_by_role(spec[1], name=spec[2], exact=True)
    if kind == "role_partial":
        return page.get_by_role(spec[1], name=spec[2], exact=False)
    if kind == "css":
        return page.locator(spec[1])
    if kind == "placeholder":
        return page.get_by_placeholder(spec[1])
    if kind == "text":
        return page.get_by_text(spec[1])

    raise ValueError(f"Неизвестный тип селектора '{kind}' у '{name}'")


# -----------------------------------------------------------------------------
#  ПОМОЩНИК: открыть страницу с НЕСКОЛЬКИМИ ПОПЫТКАМИ.
# -----------------------------------------------------------------------------
def open_page_with_retry(page, url):
    """Пытается открыть url до config.PAGE_OPEN_ATTEMPTS раз. Возвращает True при успехе."""
    attempts = config.PAGE_OPEN_ATTEMPTS
    for attempt in range(1, attempts + 1):
        try:
            log(f"Открываю {url} (попытка {attempt} из {attempts})...")
            page.goto(url)
            log("✅ Страница открылась.")
            return True
        except Exception as e:
            log(f"⚠️ Не удалось открыть с попытки {attempt}: {e}")
            if attempt < attempts:
                log(f"Жду {config.PAGE_OPEN_RETRY_SEC} сек и пробую снова...")
                time.sleep(config.PAGE_OPEN_RETRY_SEC)
    log(f"❌ Страница так и не открылась за {attempts} попыток.")
    return False


# -----------------------------------------------------------------------------
#  ОДНА ПОПЫТКА генерации для ОДНОЙ картинки. Возвращает "success" / "error".
#  Картинку тут НЕ переносим — это решает вызывающий код.
# -----------------------------------------------------------------------------
def process_one_image(page, image_path, image_name):
    """Одна полная попытка генерации. Возвращает 'success' или 'error'."""

    # Заранее определяем ориентацию (16:9 или 9:16) по размерам картинки.
    orientation = get_orientation(image_path)        # "16_9" или "9_16"
    ratio_selector_name = f"ratio_{orientation}"     # имя селектора в config
    log(f"Ориентация: {orientation} -> кнопка '{ratio_selector_name}'")

    # --- Шаг 1: открываем дашборд (с повтором, сайт бывает медленным) ---
    if not open_page_with_retry(page, config.DASHBOARD_URL):
        log("⚠️ Дашборд не открылся — считаю эту попытку ошибкой.")
        return "error"

    # --- Шаг 2: карточка "Генерация видео" ---
    log("Открываю карточку 'Генерация видео'...")
    loc(page, "video_card").click()

    # --- Шаг 3: режим "Из фото в видео" ---
    log("Переключаюсь в режим 'Из фото в видео'...")
    loc(page, "mode_photo_to_video").click()

    # --- Шаг 4: загружаем картинку ---
    log(f"Загружаю картинку: {image_name}")
    loc(page, "image_upload").set_input_files(image_path)

    # --- Шаг 5: вписываем промпт ---
    log(f"Ввожу промпт: '{config.PROMPT_TEXT}'")
    loc(page, "prompt_field").fill(config.PROMPT_TEXT)

    # --- Шаг 6: выбираем соотношение сторон ---
    log(f"Жму кнопку соотношения: {ratio_selector_name}")
    loc(page, ratio_selector_name).click()

    # --- Шаг 7: ЖДЁМ, пока кнопка "Сгенерировать" станет АКТИВНОЙ ---
    # Это и есть подтверждение, что картинка реально загрузилась (≈5 сек).
    gen = loc(page, "generate_button")
    log("Жду, пока кнопка 'Сгенерировать' станет активной (картинка грузится)...")
    try:
        gen.wait_for(state="visible", timeout=config.WAIT_FOR_BUTTON_ENABLED_MS)
        # wait_for(visible) не проверяет enabled, поэтому опрашиваем enabled сами.
        deadline = time.time() + config.WAIT_FOR_BUTTON_ENABLED_MS / 1000
        while time.time() < deadline:
            if gen.is_enabled():
                break
            time.sleep(0.5)
        if not gen.is_enabled():
            log("❌ Кнопка 'Сгенерировать' не стала активной — картинка не загрузилась.")
            return "error"
    except Exception:
        log("❌ Не дождался активной кнопки 'Сгенерировать' — картинка не загрузилась.")
        return "error"
    log("✅ Кнопка активна — картинка загрузилась.")

    # --- Шаг 8: запускаем генерацию ---
    # Клик сам дождётся кликабельности; раз он прошёл — генерация СТАРТОВАЛА.
    log("Нажимаю 'Сгенерировать'...")
    gen.click()
    log("✅ Генерация запущена.")

    # Для информации (НЕ как условие) глянем подсказку "заявка в работе".
    try:
        if loc(page, "busy_indicator").is_visible():
            log("ℹ️ Подсказка 'заявка в работе' видна (доп. подтверждение).")
    except Exception:
        pass

    start_time = time.time()   # засекаем длительность генерации

    # --- Шаг 9: ЖДЁМ ОКОНЧАНИЯ генерации по кнопке ---
    # Пока генерация идёт — кнопка "Сгенерировать" disabled.
    # Когда сайт снова готов — кнопка опять enabled. Опрашиваем раз в 5 сек.
    log("Жду окончания генерации (5-15 минут)...")
    deadline = time.time() + config.WAIT_FOR_VIDEO_MS / 1000
    finished = False
    while time.time() < deadline:
        try:
            if gen.is_enabled():
                finished = True
                break
        except Exception:
            # Если на миг не смогли прочитать состояние — не страшно, пробуем ещё.
            pass
        time.sleep(5)   # опрос раз в 5 секунд (не долбим страницу)

    if not finished:
        log("❌ Генерация не завершилась за отведённый максимум — считаю ошибкой.")
        return "error"

    elapsed = int(time.time() - start_time)
    minutes, seconds = divmod(elapsed, 60)
    log(f"Генерация завершилась за {minutes} мин {seconds} сек. Проверяю результат...")

    # --- Шаг 10: ДЕТЕКТОР УСПЕХА/ОШИБКИ по кнопке "Скачать" ---
    download_link = loc(page, "download_button")
    try:
        download_link.wait_for(state="visible", timeout=config.WAIT_FOR_DOWNLOAD_MS)
    except Exception:
        # Кнопки "Скачать" нет — генерация не удалась (глюк сайта), можно повторить.
        log("❌ Кнопка 'Скачать' не появилась — генерация завершилась ОШИБКОЙ.")
        try:
            body_text = page.locator("body").inner_text(timeout=5000)
            lines = [ln.strip() for ln in body_text.splitlines() if ln.strip()]
            tail = " | ".join(lines)[-300:]
            log(f"ℹ️ Что видно на странице (хвост текста): ...{tail}")
        except Exception:
            log("ℹ️ Текст страницы прочитать не удалось (не критично).")
        return "error"

    log("✅ Кнопка 'Скачать' на месте — генерация удалась.")

    # --- Шаг 11: СКАЧИВАЕМ ВИДЕО В OUTPUT ---
    log("Скачиваю видео...")
    with page.expect_download(timeout=config.PAGE_TIMEOUT_MS) as download_info:
        download_link.click()
    download = download_info.value
    suggested_name = download.suggested_filename   # имя как отдал сайт
    save_path = os.path.join(config.OUTPUT_DIR, suggested_name)
    download.save_as(save_path)
    log(f"✅ Видео сохранено: {save_path}")

    return "success"


# -----------------------------------------------------------------------------
#  ОБРАБОТКА ОДНОЙ КАРТИНКИ С ПОВТОРАМИ + ПЕРЕНОС в DONE/FAILED.
#  (Вынесено из старого main(), чтобы батч-цикл переиспользовал эту логику.)
#  Возвращает "success" или "error" (по итогу всех попыток).
# -----------------------------------------------------------------------------
def handle_image_with_retries(page, image_path, image_name):
    """Гоняет картинку до MAX_ATTEMPTS попыток и разносит её в DONE или FAILED."""
    log(f"Попыток на эту картинку (MAX_ATTEMPTS): {config.MAX_ATTEMPTS}")

    result = "error"
    for attempt in range(1, config.MAX_ATTEMPTS + 1):
        log(f"----- ПОПЫТКА {attempt} из {config.MAX_ATTEMPTS} для '{image_name}' -----")
        try:
            result = process_one_image(page, image_path, image_name)
        except Exception as e:
            log(f"⚠️ Попытка {attempt} прервалась сбоем: {e}")
            result = "error"

        if result == "success":
            log(f"✅ Попытка {attempt} успешна.")
            break
        else:
            if attempt < config.MAX_ATTEMPTS:
                # Перед ПОВТОРОМ упавшей картинки — своя случайная пауза.
                pause = random.randint(config.DELAY_MIN_SEC, config.DELAY_MAX_SEC)
                log(f"↻ Попытка {attempt} неудачна. "
                    f"Жду {pause} сек перед повтором (чтобы не выглядеть ботом)...")
                time.sleep(pause)
            else:
                log(f"❌ Попытка {attempt} неудачна. Попытки исчерпаны.")

    # Разносим картинку по итогу: успех -> DONE, провал -> FAILED.
    if result == "success":
        done_path = os.path.join(config.DONE_DIR, image_name)
        os.replace(image_path, done_path)
        log(f"🎉 УСПЕХ. Картинка перенесена в DONE: {done_path}")
    else:
        failed_path = os.path.join(config.FAILED_DIR, image_name)
        os.replace(image_path, failed_path)
        log(f"🛑 ВСЕ ПОПЫТКИ ПРОВАЛЕНЫ. Картинка перенесена в FAILED: {failed_path}")

    return result


# -----------------------------------------------------------------------------
#  СПИСОК КАРТИНОК В INPUT (отсортированный, только поддерживаемые форматы).
# -----------------------------------------------------------------------------
def list_input_images():
    """Возвращает отсортированный список имён картинок в INPUT."""
    valid_ext = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
    files = [f for f in os.listdir(config.INPUT_DIR) if f.lower().endswith(valid_ext)]
    files.sort()   # стабильный порядок (по алфавиту), чтобы шли предсказуемо
    return files


# -----------------------------------------------------------------------------
#  ГЛАВНАЯ ФУНКЦИЯ: ПОЛНЫЙ БАТЧ по всей папке INPUT.
# -----------------------------------------------------------------------------
def main():
    # 1) Должна быть сохранённая сессия (логин делается отдельно через login.py).
    if not os.path.exists(config.STORAGE_STATE_FILE):
        log(f"ОШИБКА: нет файла сессии '{config.STORAGE_STATE_FILE}'.")
        log("Сначала запусти login.py и войди в аккаунт руками.")
        return

    # 2) Берём текущий список картинок. Если пусто — сразу выходим.
    files = list_input_images()
    if not files:
        log(f"В папке '{config.INPUT_DIR}' нет картинок. Делать нечего — выхожу.")
        return

    total = len(files)
    log("==================================================")
    log(f"СТАРТ БАТЧА. Картинок в INPUT: {total}")
    log("==================================================")

    # 3) Браузер открываем ОДИН раз на весь батч.
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=config.STORAGE_STATE_FILE)
        page = context.new_page()
        page.set_default_timeout(config.PAGE_TIMEOUT_MS)

        success_count = 0   # счётчик успешных
        failed_count = 0    # счётчик проваленных

        # 4) Идём по картинкам по очереди. index — номер для лога (1..total).
        for index, image_name in enumerate(files, start=1):
            image_path = os.path.join(config.INPUT_DIR, image_name)

            log("")  # пустая строка-разделитель для читабельности лога
            log(f"########## КАРТИНКА {index} из {total}: {image_name} ##########")

            # Полная обработка одной картинки (с попытками и переносом).
            result = handle_image_with_retries(page, image_path, image_name)
            if result == "success":
                success_count += 1
            else:
                failed_count += 1

            log(f"ПРОГРЕСС: обработано {index} из {total} "
                f"(успешно: {success_count}, провалено: {failed_count}).")

            # 5) ПАУЗА перед СЛЕДУЮЩЕЙ картинкой (только если она есть).
            #    Между разными картинками — свой диапазон BATCH_DELAY_*.
            if index < total:
                pause = random.randint(config.BATCH_DELAY_MIN_SEC,
                                       config.BATCH_DELAY_MAX_SEC)
                log(f"⏸ Пауза {pause} сек перед следующей картинкой...")
                time.sleep(pause)

        # 6) Итоги батча.
        log("")
        log("==================================================")
        log(f"БАТЧ ЗАВЕРШЁН. Всего: {total} | "
            f"успешно: {success_count} | провалено: {failed_count}.")
        log("Успешные -> DONE, проваленные -> FAILED.")
        log("==================================================")

        browser.close()


if __name__ == "__main__":
    main()
