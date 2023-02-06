from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config  # Файл конфигурации


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    apProvider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету. Логин и Refresh Token берутся из файла Config.py
    # apProvider = AlorPy(Config.DemoUserName, Config.DemoRefreshToken, True)  # Подключаемся к демо счету

    exchange = 'MOEX'  # Биржа
    symbol = 'SBER'  # Тикер
    # symbol = 'SiH3'  # Для фьючерсов: <Код тикера><Месяц экспирации: 3-H, 6-M, 9-U, 12-Z><Последняя цифра года>
    # symbol = 'RIH3'

    # Данные тикера и его торговый счет
    si = apProvider.GetSymbol(exchange, symbol)  # Получаем информацию о тикере
    # print(si)
    print(f'Информация о тикере {si["primary_board"]}.{si["symbol"]} ({si["shortname"]}) на бирже {si["exchange"]}:')
    print(f'Валюта: {si["currency"]}')
    decimals = max(0, str(si['minstep'])[::-1].find('.'))  # Из шага цены получаем кол-во знаков после запятой
    print(f'Кол-во десятичных знаков: {decimals}')
    print(f'Лот: {si["lotsize"]}')
    print(f'Шаг цены: {si["minstep"]}')
