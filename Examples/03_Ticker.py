from math import log10  # Кол-во десятичных знаков будем получать из шага цены через десятичный логарифм

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config  # Файл конфигурации


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    ap_provider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету

    exchange = 'MOEX'  # Биржа
    # Формат короткого имени для фьючерсов: <Код тикера><Месяц экспирации: 3-H, 6-M, 9-U, 12-Z><Последняя цифра года>. Пример: SiU3, RIU3
    # Формат полного имени для фьючерсов: <Код тикера заглавными буквами>-<Месяц экспирации: 3, 6, 9, 12>.<Последние 2 цифры года>. Пример: SI-9.23, RTS-9.23
    symbols = ('SBER', 'VTBR', 'SiU3', 'RIU3')  # Кортеж кодов тикеров

    for symbol in symbols:  # Пробегаемся по всем тикерам
        si = ap_provider.get_symbol(exchange, symbol)  # Получаем информацию о тикере
        # print('Ответ от сервера:', si)
        print(f'Информация о тикере {si["primary_board"]}.{si["symbol"]} ({si["shortname"]}, {si["type"]}) на бирже {si["exchange"]}:')
        print(f'Валюта: {si["currency"]}')
        min_step = si['minstep']  # Шаг цены
        decimals = int(log10(1 / min_step) + 0.99)  # Из шага цены получаем кол-во десятичных знаков
        print(f'Кол-во десятичных знаков: {decimals}')
        print(f'Лот: {si["lotsize"]}')
        print(f'Шаг цены: {min_step}')
