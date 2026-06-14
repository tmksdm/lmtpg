# =============================================================================
#  generate.py — ЦИКЛ ДЛЯ ОДНОЙ КАРТИНКИ + ПОВТОРЫ ПРИ ОШИБКЕ (Этап 6, v2)
#
#  НАДЁЖНАЯ ЛОГИКА (после живой диагностики):
#    - Главный сигнал состояния — кнопка "Сгенерировать":
#        disabled = фото не готово ИЛИ генерация идёт;
#        enabled  = сайт готов принять генерацию.
#    - После загрузки картинки ЖДЁМ, пока кнопка станет активной (≈5 сек).
#      Не стала за WAIT_FOR_BUTTON_ENABLED_MS -> картинка не загрузилась
#      (глюк сайта) -> ошибка попытки -> перезаход с нуля.
#    - Клик "Сгенерировать" сам ждёт активации, поэтому ФАКТ клика = старт.
#      Подсказку "заявка в работе" больше НЕ ждём как условие (она ненадёжна).
#    - Окончание генерации ловим по тому, что кнопка СНОВА стала enabled.
#    - Кнопка "Скачать" появилась -> успех (видео в OUTPUT, картинка в DONE);
#      не появилась -> ошибка -> повтор (до MAX_ATTEMPTS), иначе в FAILED.
#
#  Пока обрабатываем ОДНУ картинку (первую из INPUT). Полный батч — Этап 7.
# =============================================================================

import os                                         # работа с путями и файлами
import time                                       # замер времени генерации
import random                                     # случайная задержка перед повтором
from playwright.sync_api import sync_playwright   # движок браузера

import config                              # все наши настройки и селекторы
from orientation import get_orientation    # определение 16:9 / 9:16 по картинке


# -----------------------------------------------------------------------------
#  ПОМОЩНИК: кортеж-селектор из config -> локатор Playwright. (без изменений)
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
#  ПОМОЩНИК: открыть страницу с НЕСКОЛЬКИМИ ПОПЫТКАМИ. (без изменений)
# -----------------------------------------------------------------------------
def open_page_with_retry(page, url):
    """Пытается открыть url до config.PAGE_OPEN_ATTEMPTS раз. Возвращает True при успехе."""
    attempts = config.PAGE_OPEN_ATTEMPTS
    for attempt in range(1, attempts + 1):
        try:
            print(f"Открываю {url} (попытка {attempt} из {attempts})...")
            page.goto(url)
            print("✅ Страница открылась.")
            return True
        except Exception as e:
            print(f"⚠️ Не удалось открыть с попытки {attempt}: {e}")
            if attempt < attempts:
                print(f"Жду {config.PAGE_OPEN_RETRY_SEC} сек и пробую снова...")
                time.sleep(config.PAGE_OPEN_RETRY_SEC)
    print(f"❌ Страница так и не открылась за {attempts} попыток.")
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
    print(f"Ориентация: {orientation} -> кнопка '{ratio_selector_name}'")

    # --- Шаг 1: открываем дашборд (с повтором, сайт бывает медленным) ---
    if not open_page_with_retry(page, config.DASHBOARD_URL):
        print("⚠️ Дашборд не открылся — считаю эту попытку ошибкой.")
        return "error"

    # --- Шаг 2: карточка "Генерация видео" ---
    print("Открываю карточку 'Генерация видео'...")
    loc(page, "video_card").click()

    # --- Шаг 3: режим "Из фото в видео" ---
    print("Переключаюсь в режим 'Из фото в видео'...")
    loc(page, "mode_photo_to_video").click()

    # --- Шаг 4: загружаем картинку ---
    print(f"Загружаю картинку: {image_name}")
    loc(page, "image_upload").set_input_files(image_path)

    # --- Шаг 5: вписываем промпт ---
    print(f"Ввожу промпт: '{config.PROMPT_TEXT}'")
    loc(page, "prompt_field").fill(config.PROMPT_TEXT)

    # --- Шаг 6: выбираем соотношение сторон ---
    print(f"Жму кнопку соотношения: {ratio_selector_name}")
    loc(page, ratio_selector_name).click()

    # --- Шаг 7: ЖДЁМ, пока кнопка "Сгенерировать" станет АКТИВНОЙ ---
    # Это и есть подтверждение, что картинка реально загрузилась (≈5 сек).
    # Если кнопка НЕ активировалась за отведённое время — картинка не
    # загрузилась (известный глюк сайта) -> считаем попытку ошибкой.
    gen = loc(page, "generate_button")
    print("Жду, пока кнопка 'Сгенерировать' станет активной (картинка грузится)...")
    try:
        # Ждём именно состояния "enabled" у кнопки.
        gen.wait_for(state="visible", timeout=config.WAIT_FOR_BUTTON_ENABLED_MS)
        # wait_for(visible) не проверяет enabled, поэтому опрашиваем enabled сами.
        deadline = time.time() + config.WAIT_FOR_BUTTON_ENABLED_MS / 1000
        while time.time() < deadline:
            if gen.is_enabled():
                break
            time.sleep(0.5)
        if not gen.is_enabled():
            print("❌ Кнопка 'Сгенерировать' не стала активной — картинка не загрузилась.")
            return "error"
    except Exception:
        print("❌ Не дождался активной кнопки 'Сгенерировать' — картинка не загрузилась.")
        return "error"
    print("✅ Кнопка активна — картинка загрузилась.")

    # --- Шаг 8: запускаем генерацию ---
    # Клик сам дождётся кликабельности; раз он прошёл — генерация СТАРТОВАЛА.
    print("Нажимаю 'Сгенерировать'...")
    gen.click()
    print("✅ Генерация запущена.")

    # Для информации (НЕ как условие) глянем подсказку "заявка в работе".
    try:
        if loc(page, "busy_indicator").is_visible():
            print("ℹ️ Подсказка 'заявка в работе' видна (доп. подтверждение).")
    except Exception:
        pass

    start_time = time.time()   # засекаем длительность генерации

    # --- Шаг 9: ЖДЁМ ОКОНЧАНИЯ генерации по кнопке ---
    # Пока генерация идёт — кнопка "Сгенерировать" disabled.
    # Когда сайт снова готов — кнопка опять становится enabled. Это и есть
    # сигнал "генерация завершилась". Опрашиваем её раз в несколько секунд.
    print("Жду окончания генерации (5-15 минут)...")
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
        # За максимальное время кнопка так и не разблокировалась — что-то зависло.
        print("❌ Генерация не завершилась за отведённый максимум — считаю ошибкой.")
        return "error"

    elapsed = int(time.time() - start_time)
    minutes, seconds = divmod(elapsed, 60)
    print(f"Генерация завершилась за {minutes} мин {seconds} сек. Проверяю результат...")

    # --- Шаг 10: ДЕТЕКТОР УСПЕХА/ОШИБКИ по кнопке "Скачать" ---
    download_link = loc(page, "download_button")
    try:
        download_link.wait_for(state="visible", timeout=config.WAIT_FOR_DOWNLOAD_MS)
    except Exception:
        # Кнопки "Скачать" нет — генерация не удалась (глюк сайта), можно повторить.
        print("❌ Кнопка 'Скачать' не появилась — генерация завершилась ОШИБКОЙ.")
        try:
            body_text = page.locator("body").inner_text(timeout=5000)
            lines = [ln.strip() for ln in body_text.splitlines() if ln.strip()]
            tail = " | ".join(lines)[-300:]
            print(f"ℹ️ Что видно на странице (хвост текста): ...{tail}")
        except Exception:
            print("ℹ️ Текст страницы прочитать не удалось (не критично).")
        return "error"

    print("✅ Кнопка 'Скачать' на месте — генерация удалась.")

    # --- Шаг 11: СКАЧИВАЕМ ВИДЕО В OUTPUT ---
    print("Скачиваю видео...")
    with page.expect_download(timeout=config.PAGE_TIMEOUT_MS) as download_info:
        download_link.click()
    download = download_info.value
    suggested_name = download.suggested_filename   # имя как отдал сайт
    save_path = os.path.join(config.OUTPUT_DIR, suggested_name)
    download.save_as(save_path)
    print(f"✅ Видео сохранено: {save_path}")

    return "success"


# -----------------------------------------------------------------------------
#  ГЛАВНАЯ ФУНКЦИЯ: одна картинка, попытки до MAX_ATTEMPTS. (логика как в v1)
# -----------------------------------------------------------------------------
def main():
    if not os.path.exists(config.STORAGE_STATE_FILE):
        print(f"ОШИБКА: нет файла сессии '{config.STORAGE_STATE_FILE}'.")
        print("Сначала запусти login.py и войди в аккаунт руками.")
        return

    valid_ext = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
    files = [f for f in os.listdir(config.INPUT_DIR) if f.lower().endswith(valid_ext)]
    if not files:
        print(f"ОШИБКА: в папке '{config.INPUT_DIR}' нет картинок.")
        return

    image_name = files[0]
    image_path = os.path.join(config.INPUT_DIR, image_name)
    print(f"Картинка в работе: {image_path}")
    print(f"Попыток на эту картинку (MAX_ATTEMPTS): {config.MAX_ATTEMPTS}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=config.STORAGE_STATE_FILE)
        page = context.new_page()
        page.set_default_timeout(config.PAGE_TIMEOUT_MS)

        result = "error"
        for attempt in range(1, config.MAX_ATTEMPTS + 1):
            print(f"\n===== ПОПЫТКА {attempt} из {config.MAX_ATTEMPTS} =====")
            try:
                result = process_one_image(page, image_path, image_name)
            except Exception as e:
                print(f"⚠️ Попытка {attempt} прервалась сбоем: {e}")
                result = "error"

            if result == "success":
                print(f"✅ Попытка {attempt} успешна.")
                break
            else:
                if attempt < config.MAX_ATTEMPTS:
                    # Перед повтором ждём СЛУЧАЙНУЮ паузу из диапазона config,
                    # чтобы поведение не выглядело "роботным" и не нагружать сайт.
                    pause = random.randint(config.DELAY_MIN_SEC, config.DELAY_MAX_SEC)
                    print(f"↻ Попытка {attempt} неудачна. "
                          f"Жду {pause} сек перед повтором (чтобы не выглядеть ботом)...")
                    time.sleep(pause)
                else:
                    print(f"❌ Попытка {attempt} неудачна. Попытки исчерпаны.")

        if result == "success":
            done_path = os.path.join(config.DONE_DIR, image_name)
            os.replace(image_path, done_path)
            print(f"\n🎉 УСПЕХ. Картинка перенесена в DONE: {done_path}")
        else:
            failed_path = os.path.join(config.FAILED_DIR, image_name)
            os.replace(image_path, failed_path)
            print(f"\n🛑 ВСЕ ПОПЫТКИ ПРОВАЛЕНЫ. Картинка перенесена в FAILED: {failed_path}")

        browser.close()


if __name__ == "__main__":
    main()
