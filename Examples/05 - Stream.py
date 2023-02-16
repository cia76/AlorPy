import time  # Подписка на события по времени

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config  # Файл конфигурации


def PrintCallback(response):
    print(response)


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    apProvider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету. Логин и Refresh Token берутся из файла Config.py
    # apProvider = AlorPy(Config.DemoUserName, Config.DemoRefreshToken, True)  # Подключаемся к демо счету

    exchange = 'MOEX'  # Код биржи MOEX или SPBX
    symbol = 'SBER'  # Тикер
    # symbol = 'SiM2'  # Для фьючерсов: <Код тикера><Месяц экспирации: 3-H, 6-M, 9-U, 12-Z><Последняя цифра года>

    # Стакан
    print(f'Текущий стакан {exchange}.{symbol}')
    orderBook = apProvider.GetOrderBook(exchange, symbol)  # Текущий стакан с максимальной глубиной 20 получаем через запрос
    print(orderBook)
    if orderBook['bids'] and orderBook['asks']:
        print(f'bids от {orderBook["bids"][0]} до {orderBook["bids"][-1]}, asks от {orderBook["asks"][0]} до {orderBook["asks"][-1]}')
        
    print("\nСтакан котировок: визуализируем...\n")    
    asks = orderBook['asks'][::-1]
    for i in range(len(asks)):
        volume = asks[i]['volume']
        price = asks[i]['price']
        print(f"{volume:7} \t {price:9}")
    
    bids = orderBook['bids']
    for i in range(len(bids)):
        volume = bids[i]['volume']
        price = bids[i]['price']
        print(f"\t\t\t {price:9} \t {volume:7}")

    closest_ask_to_sell = asks[-1]
    closest_bid_to_buy = bids[0]
    print(f"\nЛучшее предложение, продажа по: {closest_ask_to_sell}, покупка по: {closest_bid_to_buy}\n")

    sleepSec = 5  # Кол-во секунд получения стакана
    print(f'Подписка на стакан {exchange}.{symbol}')
    apProvider.OnChangeOrderBook = PrintCallback  # Перехватываем обработку события изменения стакана
    guid = apProvider.OrderBookGetAndSubscribe(exchange, symbol)  # Получаем код пописки
    print(f'Код подписки: {guid}')
    print(f'{sleepSec} секунд стакана')
    time.sleep(sleepSec)  # Ждем кол-во секунд получения стакана
    print(f'Отмена подписки на стакан: {apProvider.Unsubscribe(guid)}')  # Отписываеся от стакана
    apProvider.OnChangeOrderBook = apProvider.DefaultHandler  # Возвращаем обработчик по умолчанию

    # Котировки
    print(f'Текущие котировки {exchange}.{symbol}')
    quotes = apProvider.GetQuotes(f'{exchange}:{symbol}')[0]  # Последнюю котировку получаем через запрос
    print(quotes)
    print(f'Последняя цена сделки: {quotes["last_price"]}')

    sleepSec = 5  # Кол-во секунд получения котировок
    print(f'Подписка на котировки {exchange}.{symbol}')
    apProvider.OnNewQuotes = PrintCallback  # Перехватываем обработку события прихода новой котировки
    guid = apProvider.QuotesSubscribe(exchange, symbol)  # Получаем код пописки
    print(f'Код подписки: {guid}')
    print(f'{sleepSec} секунд котировок')
    time.sleep(sleepSec)  # Ждем кол-во секунд получения обезличенных сделок
    print(f'Отмена подписки на котировки: {apProvider.Unsubscribe(guid)}')  # Отписываеся от стакана
    apProvider.OnNewQuotes = apProvider.DefaultHandler  # Возвращаем обработчик по умолчанию

    # Выход
    apProvider.CloseWebSocket()  # Перед выходом закрываем соединение с WebSocket
