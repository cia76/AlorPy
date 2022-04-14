# Чтобы получить Refresh Token:
# 0. Для получения тестового логина/пароля демо счета оставить заявку на openapi@alor.ru
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
    PortfolioStocks = 'D00000'  # Фондовый рынок
    AccountStocks = 'L01-00000F00'
    PortfolioFutures = '0000PST'  # Срочный рынок
    AccountFutures = '0000PST'
    PortfolioFx = 'G00000'  # Валютный рынок
    AccountFx = 'MB0000000000'

    # Для демо счета:
    # 1. Пройти по ссылке "Токены для ведения торгов в тестовом контуре" - "Begin OAuth authorization flow"
    # 2. Ввести тестовый логин/пароль. Нажать "Разрешить"
    DemoUserName = 'P000000'
    DemoRefreshToken = 'ffffffff-ffff-ffff-ffff-ffffffffffff'
    PortfolioStocks = 'D00000'  # Фондовый рынок
    DemoAccountStocks = 'L01-00000F00'
    DemoPortfolioFutures = '0000000'  # Срочный рынок
    DemoAccountFutures = '0000000'
    DemoPortfolioFx = 'G00000'  # Валютный рынок
    DemoAccountFx = 'MB0000000000'
