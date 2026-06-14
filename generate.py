# =============================================================================
#  generate.py — ОДИН ПОЛНЫЙ ЦИКЛ ДЛЯ ОДНОЙ КАРТИНКИ (Этап 4)
#
#  Что делает (пока — часть 4.1-4.3):
#    1. Открывает браузер с сохранённой сессией (логин не нужен).
#    2. Заходит на дашборд, открывает рабочую зону "Из фото в видео".
#    3. Загружает картинку из INPUT.
#    4. Определяет ориентацию (16:9 / 9:16) и жмёт нужную кнопку.
#    5. Вписывает фиксированный промпт.
#    6. Нажимает "Сгенерировать".
#
#  Скачивание готового видео и перенос в DONE добавим следующими под-шагами,
#  когда увидим вживую кнопку скачивания и индикатор генерации.
# =============================================================================

import os                                         # работа с путями и файлами
import time                                       # для замера, сколько шла генерация
from playwright.sync_api import sync_playwright   # движок браузера

import config                       # все наши настройки и селекторы
from orientation import get_orientation   # определение 16:9 / 9:16 по картинке


# -----------------------------------------------------------------------------
#  ПОМОЩНИК: превращает кортеж-селектор из config в реальный локатор Playwright.
#
#  В config селекторы записаны единообразно, например:
#     ("role", "button", "Войти")              -> page.get_by_role("button", name="Войти")
#     ("css", 'input[type="file"]')            -> page.locator('input[type="file"]')
#     ("placeholder", "Например")              -> page.get_by_placeholder("Например")
#     ("role_partial", "button", "Генерация")  -> поиск по ЧАСТИ имени (exact=False)
#
#  Эта функция избавляет нас от повторения кода — пишем loc(page, "имя_селектора").
# -----------------------------------------------------------------------------
def loc(page, name):
    """Берёт селектор по имени из config.SELECTORS и возвращает локатор Playwright."""
    spec = config.SELECTORS[name]   # достаём кортеж, например ("role", "button", "Войти")
    kind = spec[0]                  # первый элемент — ТИП селектора

    if kind == "role":
        # spec = ("role", РОЛЬ, ИМЯ)  -> точное совпадение по имени.
        # exact=True важно для "Скачать": чтобы не зацепить "Скачать файл" из истории.
        return page.get_by_role(spec[1], name=spec[2], exact=True)

    if kind == "role_partial":
        # spec = ("role_partial", РОЛЬ, ЧАСТЬ_ИМЕНИ) -> совпадение по части текста
        return page.get_by_role(spec[1], name=spec[2], exact=False)

    if kind == "css":
        # spec = ("css", "CSS-селектор")
        return page.locator(spec[1])

    if kind == "placeholder":
        # spec = ("placeholder", "текст подсказки в поле")
        return page.get_by_placeholder(spec[1])

    if kind == "text":
        # spec = ("text", "видимый текст")
        return page.get_by_text(spec[1])

    # Если попался незнакомый тип — честно падаем с понятной ошибкой.
    raise ValueError(f"Неизвестный тип селектора '{kind}' у '{name}'")

# -----------------------------------------------------------------------------
#  ПОМОЩНИК: открыть страницу с НЕСКОЛЬКИМИ ПОПЫТКАМИ.
#
#  Сайт ai.gptml.ru бывает медленным и открывается не с первого раза.
#  Чтобы скрипт не падал из-за одного неудачного захода — пробуем несколько раз.
#  Сколько попыток и пауза между ними — берутся из config.
# -----------------------------------------------------------------------------
def open_page_with_retry(page, url):
    """Пытается открыть url до config.PAGE_OPEN_ATTEMPTS раз. Возвращает True при успехе."""
    attempts = config.PAGE_OPEN_ATTEMPTS      # сколько всего попыток
    for attempt in range(1, attempts + 1):    # считаем попытки с 1
        try:
            print(f"Открываю {url} (попытка {attempt} из {attempts})...")
            page.goto(url)                    # пробуем открыть
            print("✅ Страница открылась.")
            return True                       # получилось — выходим
        except Exception as e:
            # Не получилось — сообщаем и (если попытки ещё есть) ждём и пробуем снова.
            print(f"⚠️ Не удалось открыть с попытки {attempt}: {e}")
            if attempt < attempts:
                print(f"Жду {config.PAGE_OPEN_RETRY_SEC} сек и пробую снова...")
                time.sleep(config.PAGE_OPEN_RETRY_SEC)
    # Все попытки исчерпаны — сообщаем о неудаче.
    print(f"❌ Страница так и не открылась за {attempts} попыток.")
    return False

def main():
    # --- Шаг 0: убедимся, что файл сессии на месте ---
    if not os.path.exists(config.STORAGE_STATE_FILE):
        print(f"ОШИБКА: нет файла сессии '{config.STORAGE_STATE_FILE}'.")
        print("Сначала запусти login.py и войди в аккаунт руками.")
        return

    # --- Шаг 0.1: берём ОДНУ тестовую картинку из папки INPUT ---
    # Собираем список файлов-картинок (по расширению).
    valid_ext = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
    files = [
        f for f in os.listdir(config.INPUT_DIR)
        if f.lower().endswith(valid_ext)
    ]
    if not files:
        print(f"ОШИБКА: в папке '{config.INPUT_DIR}' нет картинок.")
        print("Положи туда тестовую картинку и запусти снова.")
        return

    # Берём ПЕРВУЮ картинку из списка (на Этапе 4 обрабатываем только одну).
    image_name = files[0]
    image_path = os.path.join(config.INPUT_DIR, image_name)
    print(f"Тестовая картинка: {image_path}")

    # --- Шаг 0.2: заранее определяем ориентацию (16:9 или 9:16) ---
    orientation = get_orientation(image_path)   # вернёт "16_9" или "9_16"
    ratio_selector_name = f"ratio_{orientation}"   # имя селектора в config
    print(f"Ориентация картинки: {orientation} -> жмём кнопку '{ratio_selector_name}'")

    with sync_playwright() as p:
        # Видимое окно — чтобы ты глазами видел весь процесс.
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=config.STORAGE_STATE_FILE)
        page = context.new_page()

        # Общий таймаут на ожидание элементов (из config).
        page.set_default_timeout(config.PAGE_TIMEOUT_MS)

        # --- Шаг 1: открываем дашборд (с повтором, сайт бывает медленным) ---
        if not open_page_with_retry(page, config.DASHBOARD_URL):
            # Если дашборд так и не открылся — нет смысла продолжать.
            print("Прерываю: дашборд недоступен. Попробуй запустить позже.")
            browser.close()
            return

        # --- Шаг 2: открываем карточку "Генерация видео" ---
        print("Открываю карточку 'Генерация видео'...")
        loc(page, "video_card").click()

        # --- Шаг 3: переключаемся в режим "Из фото в видео" ---
        print("Переключаюсь в режим 'Из фото в видео'...")
        loc(page, "mode_photo_to_video").click()

        # --- Шаг 4: загружаем картинку ---
        # set_input_files грузит файл прямо в скрытое поле <input type=file>,
        # клик по области загрузки при этом не нужен.
        print(f"Загружаю картинку: {image_name}")
        loc(page, "image_upload").set_input_files(image_path)

        # --- Шаг 5: вписываем фиксированный промпт ---
        print(f"Ввожу промпт: '{config.PROMPT_TEXT}'")
        loc(page, "prompt_field").fill(config.PROMPT_TEXT)

        # --- Шаг 6: выбираем нужное соотношение сторон ---
        print(f"Жму кнопку соотношения: {ratio_selector_name}")
        loc(page, ratio_selector_name).click()

        # --- Шаг 7: нажимаем "Сгенерировать" ---
        # Если кнопка ещё не активна — Playwright сам подождёт активации
        # в пределах общего таймаута, прежде чем кликнуть.
        print("Нажимаю 'Сгенерировать'...")
        loc(page, "generate_button").click()

        print("\n✅ Генерация запущена. Жду готовности видео (5-15 минут)...")

        # --- Шаг 8: ОЖИДАНИЕ ГОТОВНОСТИ (надёжный способ, без путаницы со старым видео) ---
        #
        # Идея: следим за индикатором "У вас уже есть заявка в работе".
        #   1) Сначала ждём, пока он ПОЯВИТСЯ -> значит НАША генерация стартовала.
        #   2) Потом ждём, пока он ИСЧЕЗНЕТ -> значит генерация ЗАВЕРШИЛАСЬ.
        # Так мы не перепутаем новое видео со старым результатом на странице.
        # Лимиты ожидания теперь берём из config (а не "зашиты" в коде).
        busy = loc(page, "busy_indicator")   # подсказка "заявка в работе"

        # 8.1 — ждём ПОЯВЛЕНИЯ индикатора (генерация началась).
        # Лимит ожидания старта — из config.WAIT_FOR_START_MS.
        print("Жду подтверждения, что генерация началась...")
        busy.wait_for(state="visible", timeout=config.WAIT_FOR_START_MS)
        print("✅ Генерация началась (появилась подсказка 'заявка в работе').")

        # Засекаем время начала — чтобы потом показать, сколько всё заняло.
        start_time = time.time()

        # 8.2 — ждём ИСЧЕЗНОВЕНИЯ индикатора (генерация закончилась).
        # Вот тут уходит основное время — 5-15 минут. Лимит — из config.WAIT_FOR_VIDEO_MS.
        print("Жду окончания генерации (5-15 минут)...")
        busy.wait_for(state="hidden", timeout=config.WAIT_FOR_VIDEO_MS)

        # Считаем, сколько шла генерация, и выводим в минутах:секундах.
        elapsed = int(time.time() - start_time)        # сколько прошло секунд
        minutes, seconds = divmod(elapsed, 60)         # переводим в мин:сек
        print(f"✅ Генерация завершена за {minutes} мин {seconds} сек (подсказка пропала).")

        # --- Шаг 9: убеждаемся, что кнопка "Скачать" на месте ---
        # После завершения в блоке "Результат генерации" должна быть ссылка "Скачать".
        download_link = loc(page, "download_button")
        download_link.wait_for(state="visible", timeout=config.PAGE_TIMEOUT_MS)
        print("✅ Кнопка 'Скачать' на месте.")

        # --- Шаг 10: СКАЧИВАНИЕ ВИДЕО В OUTPUT ---
        # "Скачать" — это ССЫЛКА. Скачивание ловим через expect_download():
        # вооружаемся ожиданием, кликаем по ссылке, Playwright перехватывает файл.
        print("Скачиваю видео...")
        with page.expect_download(timeout=config.PAGE_TIMEOUT_MS) as download_info:
            download_link.click()
        download = download_info.value

        # Имя файла — ТАКОЕ, КАКОЕ ОТДАЛ САЙТ (не переименовываем) — требование проекта.
        suggested_name = download.suggested_filename
        save_path = os.path.join(config.OUTPUT_DIR, suggested_name)
        download.save_as(save_path)
        print(f"✅ Видео сохранено: {save_path}")

        # --- Шаг 11: ПЕРЕНОС ОБРАБОТАННОЙ КАРТИНКИ В DONE ---
        # Чтобы при следующем запуске эта картинка не подтянулась заново.
        done_path = os.path.join(config.DONE_DIR, image_name)
        os.replace(image_path, done_path)   # перемещает файл между папками
        print(f"✅ Картинка перенесена в DONE: {done_path}")

        print("\n🎉 Полный цикл для одной картинки завершён успешно!")

        browser.close()


if __name__ == "__main__":
    main()
