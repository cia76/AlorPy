from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config  # Файл конфигурации


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    ap_provider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету

    exchange = 'MOEX'  # Биржа
    symbol = 'SBER'  # Тикер
    # symbol = 'SiH3'  # Тикер можно искать по короткому имени. Для фьючерсов: <Код тикера><Месяц экспирации: 3-H, 6-M, 9-U, 12-Z><Последняя цифра года>
    # symbol = 'SI-3.23'  # Формат полного имени для фьючерсов: <Код тикера заглавными буквами>-<Месяц экспирации: 3, 6, 9, 12>.<Последние 2 цифры года>
    # symbol = 'RIH3'
    # symbol = 'RTS-3.23'

    # Данные тикера и его торговый счет
    si = ap_provider.get_symbol(exchange, symbol)  # Получаем информацию о тикере
    print('Ответ от сервера:', si)
    print(f'Информация о тикере {si["primary_board"]}.{si["symbol"]} ({si["shortname"]}, {si["type"]}) на бирже {si["exchange"]}:')
    print(f'Валюта: {si["currency"]}')
    decimals = max(0, str(si['minstep'])[::-1].find('.'))  # Из шага цены получаем кол-во знаков после запятой
    print(f'Кол-во десятичных знаков: {decimals}')
    print(f'Лот: {si["lotsize"]}')
    print(f'Шаг цены: {si["minstep"]}')
