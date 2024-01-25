# Чтобы получить Refresh Token:
# 0. Для получения тестового логина/пароля демо счета оставить заявку в Telegram на https://t.me/AlorOpenAPI
# 1. Зарегистрироваться на https://alor.dev/login
# 2. Выбрать "Токены для доступа к API"

# Для реального счета:
# 1. Привязать торговый аккаунт
# 2. Выписать токен

# Для демо счета:
# 1. Пройти по ссылке "Токены для ведения торгов в тестовом контуре" - "Begin OAuth authorization flow"
# 2. Ввести тестовый логин/пароль. Нажать "Разрешить"

# Как заполнять переменные портфелей PortfolioStocks, PortfolioFutures, PortfolioFx:
# 1. Запустить скрипт "Examples/02_Accounts.py"
# 2. Получить портфели для всех рынков
# 3. Заполнить переменные полученными значениями

# Коды торговых серверов для стоп заявок:
TradeServerCode = 'TRADE'  # Рынок Ценных Бумаг
ITradeServerCode = 'ITRADE'  # Рынок Иностранных Ценных Бумаг
FutServerCode = 'FUT1'  # Фьючерсы
OptServerCode = 'OPT1'  # Опционы
FxServerCode = 'FX1'  # Валютный рынок


class ConfigBase:
    """Заготовка счета"""
    UserName: str  # Имя пользователя
    RefreshToken: str  # Токен

    PortfolioStocks: str  # Портфель фондового рынка
    PortfolioFutures: str  # Портфель срочного рынка
    PortfolioFx: str  # Портфель валютного рынка

    Accounts = {}  # Привязка портфелей к биржам
    Boards = {}  # Привязка портфелей/серверов для стоп заявок к площадкам


Config = ConfigBase()  # Торговый счет
Config.UserName = 'P061904'
Config.RefreshToken = 'b9bc4d19-8a5c-4074-aa21-f9f8528aef76'  # до Fri Mar 08 2024 16:00:09 GMT+0500
Config.PortfolioStocks = 'D61904'  # Фондовый рынок
Config.PortfolioFutures = '7500PST'  # Срочный рынок
Config.PortfolioFx = 'G28601'  # Валютный рынок
Config.Accounts = {  # Привязка портфелей к биржам
    Config.PortfolioStocks: ('MOEX', 'SPBX',),  # Фондовый рынок на Московской Бирже (RUB) и СПб Бирже (USD)
    Config.PortfolioFutures: ('MOEX',),  # Срочный рынок на Московской Бирже (RUB)
    Config.PortfolioFx: ('MOEX',)}  # Валютный рынок на Московской Бирже (RUB)
Config.Boards = {  # Привязка портфелей/серверов для стоп заявок к площадкам
    'TQBR': (Config.PortfolioStocks, TradeServerCode),  # Т+ Акции и ДР
    'TQOB': (Config.PortfolioStocks, TradeServerCode),  # МБ ФР: Т+: Гособлигации
    'TQCB': (Config.PortfolioStocks, TradeServerCode),  # МБ ФР: Т+: Облигации
    'RFUD': (Config.PortfolioFutures, FutServerCode)}  # FORTS: Фьючерсы

ConfigIIA = ConfigBase()  # Индивидуальный инвестиционный счет (ИИС)
ConfigIIA.UserName = 'P061905'
ConfigIIA.RefreshToken = 'f482ad5f-4781-4afc-91a7-2d4d1acfed10'  # до Fri Mar 08 2024 16:01:37 GMT+0500
ConfigIIA.PortfolioStocks = 'D61905'  # Фондовый рынок
ConfigIIA.PortfolioFutures = '7500PSU'  # Срочный рынок
ConfigIIA.PortfolioFx = 'G28602'  # Валютный рынок
ConfigIIA.Accounts = {  # Привязка портфелей к биржам
    ConfigIIA.PortfolioStocks: ('MOEX', 'SPBX',),  # Фондовый рынок на Московской Бирже (RUB) и СПб Бирже (USD)
    ConfigIIA.PortfolioFutures: ('MOEX',),  # Срочный рынок на Московской Бирже (RUB)
    ConfigIIA.PortfolioFx: ('MOEX',)}  # Валютный рынок на Московской Бирже (RUB)
ConfigIIA.Boards = {  # Привязка портфелей/серверов для стоп заявок к площадкам
    'TQBR': (ConfigIIA.PortfolioStocks, TradeServerCode),  # Т+ Акции и ДР
    'TQOB': (ConfigIIA.PortfolioStocks, TradeServerCode),  # МБ ФР: Т+: Гособлигации
    'TQCB': (ConfigIIA.PortfolioStocks, TradeServerCode),  # МБ ФР: Т+: Облигации
    'RFUD': (ConfigIIA.PortfolioFutures, FutServerCode)}  # FORTS: Фьючерсы

ConfigDemo = ConfigBase()  # Демо счет для тестирования
ConfigDemo.UserName = 'P053930'  # Пароль: 1234567
ConfigDemo.RefreshToken = 'cb85336a-7c63-4058-a3d2-ababee3fa660'
ConfigDemo.PortfolioStocks = 'D00003'  # Фондовый рынок
ConfigDemo.PortfolioFutures = '7500003'  # Срочный рынок
ConfigDemo.PortfolioFx = 'G00003'  # Валютный рынок
ConfigDemo.Accounts = {  # Привязка портфелей к биржам
    ConfigDemo.PortfolioStocks: ('MOEX', 'SPBX',),  # Фондовый рынок на Московской Бирже (RUB) и СПб Бирже (USD)
    ConfigDemo.PortfolioFutures: ('MOEX',),  # Срочный рынок на Московской Бирже (RUB)
    ConfigDemo.PortfolioFx: ('MOEX',)}  # Валютный рынок на Московской Бирже (RUB)
ConfigDemo.Boards = {  # Привязка портфелей/серверов для стоп заявок к площадкам
    'TQBR': (ConfigDemo.PortfolioStocks, TradeServerCode),  # Т+ Акции и ДР
    'TQOB': (ConfigDemo.PortfolioStocks, TradeServerCode),  # МБ ФР: Т+: Гособлигации
    'TQCB': (ConfigDemo.PortfolioStocks, TradeServerCode),  # МБ ФР: Т+: Облигации
    'RFUD': (ConfigDemo.PortfolioFutures, FutServerCode)}  # FORTS: Фьючерсы
