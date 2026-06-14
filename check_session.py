# =============================================================================
#  check_session.py — ПРОВЕРКА СОХРАНЁННОЙ СЕССИИ
#
#  Запускаешь после login.py. Скрипт открывает браузер, ПОДГРУЖАЯ сохранённый
#  файл storage_state.json, и сразу идёт на дашборд.
#  Если вход НЕ потребовался (дашборд открылся) — сессия рабочая. Успех.
#  Если нас выкинуло на страницу входа — сессия не подхватилась.
# =============================================================================

import os                                         # для проверки наличия файла
from playwright.sync_api import sync_playwright   # движок браузера
import config                                     # наши настройки


def main():
    # Сначала убедимся, что файл сессии вообще существует.
    if not os.path.exists(config.STORAGE_STATE_FILE):
        print(f"ОШИБКА: файл сессии '{config.STORAGE_STATE_FILE}' не найден.")
        print("Сначала запусти login.py и войди в аккаунт руками.")
        return

    with sync_playwright() as p:
        # Снова видимое окно, чтобы ты глазами увидел результат.
        browser = p.chromium.launch(headless=False)

        # ГЛАВНОЕ ОТЛИЧИЕ: создаём контекст, ПОДГРУЖАЯ сохранённую сессию.
        # storage_state = путь к нашему файлу с cookies входа.
        context = browser.new_context(storage_state=config.STORAGE_STATE_FILE)

        page = context.new_page()

        # Идём сразу на дашборд (не на логин!).
        print(f"Открываю дашборд: {config.DASHBOARD_URL}")
        page.goto(config.DASHBOARD_URL, timeout=config.PAGE_TIMEOUT_MS)

        # Дадим странице пару секунд устаканиться (на случай редиректов).
        page.wait_for_timeout(3000)

        # Смотрим, на каком адресе мы в итоге оказались.
        current_url = page.url
        print(f"\nТекущий адрес страницы: {current_url}")

        # Простая проверка: если в адресе есть 'login' — значит нас выкинуло
        # на вход, сессия НЕ сработала. Иначе считаем, что всё ок.
        if "login" in current_url.lower():
            print("РЕЗУЛЬТАТ: ❌ сессия НЕ подхватилась — нас перекинуло на вход.")
            print("Нужно заново запустить login.py.")
        else:
            print("РЕЗУЛЬТАТ: ✅ сессия РАБОТАЕТ — дашборд открылся без логина!")

        # Оставим окно открытым, чтобы ты сам глазами убедился.
        print("\nПосмотри на окно браузера. Когда закончишь — нажми Enter здесь.")
        input()

        browser.close()


if __name__ == "__main__":
    main()
