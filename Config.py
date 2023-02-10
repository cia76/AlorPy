# Чтобы получить Refresh Token:
# 0. Для получения тестового логина/пароля демо счета оставить заявку в Telegram на https://t.me/AlorOpenAPI
# 1. Зарегистрироваться на https://alor.dev/login
# 2. Выбрать "Токены для доступа к API"

class Config:
    # Коды торговых серверов
    TradeServerCode = 'TRADE'  # Рынок Ценных Бумаг
    ITradeServerCode = 'ITRADE'  # Рынок Иностранных Ценных Бумаг
    FutServerCode = 'FUT1'  # Фьючерсы
    OptServerCode = 'OPT1'  # Опционы
    FxServerCode = 'FX1'  # Валютный рынок

    # Для реального счета:
    # 1. Привязать торговый аккаунт
    # 2. Выписать токен
    UserName = 'P000000'
    RefreshToken = 'ffffffff-ffff-ffff-ffff-ffffffffffff'

    # Как заполнять переменные портфелей/счетов:
    # 1. Запустить скрипт "02 - Accounts.py"
    # 2. Получить портфели/счета для всех рынков
    # 3. Заполнить переменные полученными значениями. Иначе, заявки выставляться не будут
    PortfolioStocks = 'D00000'  # Фондовый рынок - Портфель
    AccountStocks = 'L01-00000F00'  # Фондовый рынок - Счет
    PortfolioFutures = '0000PST'  # Срочный рынок - Портфель
    AccountFutures = '0000PST'  # Срочный рынок - Счет
    PortfolioFx = 'G00000'  # Валютный рынок - Портфель
    AccountFx = 'MB0000000000'  # Валютный рынок - Счет

    # Для демо счета:
    # 1. Пройти по ссылке "Токены для ведения торгов в тестовом контуре" - "Begin OAuth authorization flow"
    # 2. Ввести тестовый логин/пароль. Нажать "Разрешить"
    DemoUserName = 'P000000'
    DemoRefreshToken = 'ffffffff-ffff-ffff-ffff-ffffffffffff'

    # Как заполнять переменные портфелей/счетов:
    # 1. Запустить скрипт "02 - Accounts.py"
    # 2. Получить портфели/счета для всех рынков
    # 3. Заполнить переменные полученными значениями. Иначе, заявки выставляться не будут
    PortfolioStocks = 'D00000'  # Фондовый рынок - Портфель
    DemoAccountStocks = 'L01-00000F00'  # Фондовый рынок - Счет
    DemoPortfolioFutures = '0000000'  # Срочный рынок - Портфель
    DemoAccountFutures = '0000000'  # Срочный рынок - Счет
    DemoPortfolioFx = 'G00000'  # Валютный рынок - Портфель
    DemoAccountFx = 'MB0000000000'  # Валютный рынок - Счет
