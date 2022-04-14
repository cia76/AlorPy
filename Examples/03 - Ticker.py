from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from Config import Config  # Файл конфигурации


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    apProvider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету. Логин и Refresh Token берутся из файла Config.py
    # apProvider = AlorPy(Config.DemoUserName, Config.DemoRefreshToken, True)  # Подключаемся к демо счету

    exchange = 'MOEX'  # Биржа
    symbol = 'GAZP'  # Тикер
    # symbol = 'SiM2'  # Для фьючерсов: <Код тикера><Месяц экспирации: 3-H, 6-M, 9-U, 12-Z><Последняя цифра года>
    # symbol = 'RIM2'

    # Данные тикера и его торговый счет
    symbolInfo = apProvider.GetSymbol(exchange, symbol)  # Получаем информацию о тикере
    print(f'Информация о тикере {symbolInfo["primary_board"]}.{symbolInfo["symbol"]} ({symbolInfo["shortname"]}) на бирже {symbolInfo["exchange"]}:')
    print(f'Валюта: {symbolInfo["currency"]}')
    decimals = max(0, str(symbolInfo["minstep"])[::-1].find("."))  # Из шага цены получаем кол-во знаков после запятой
    print(f'Кол-во десятичных знаков: {decimals}')
    print(f'Лот: {symbolInfo["lotsize"]}')
    print(f'Шаг цены: {symbolInfo["minstep"]}')
