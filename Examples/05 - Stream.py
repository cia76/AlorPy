import time  # Подписка на события по времени

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config  # Файл конфигурации


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    ap_provider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету

    exchange = 'MOEX'  # Код биржи MOEX или SPBX
    symbol = 'SBER'  # Тикер
    # symbol = 'SiH3'  # Для фьючерсов: <Код тикера><Месяц экспирации: 3-H, 6-M, 9-U, 12-Z><Последняя цифра года>

    # Стакан
    print(f'Текущий стакан {exchange}.{symbol}')
    order_book = ap_provider.get_order_book(exchange, symbol)  # Текущий стакан с максимальной глубиной 20 получаем через запрос
    print(order_book)
    if order_book['bids'] and order_book['asks']:
        print(f'bids от {order_book["bids"][0]} до {order_book["bids"][-1]}, asks от {order_book["asks"][0]} до {order_book["asks"][-1]}')

    print('\nВизуализация стакана котировок')
    asks = order_book['asks'][::-1]  # Продажи
    for i in range(len(asks)):  # Пробегаемся по всем продажам
        volume = asks[i]['volume']  # Объем
        price = asks[i]['price']  # Цена
        print(f"{volume:7} \t {price:9}")

    bids = order_book['bids']  # Покупки
    for i in range(len(bids)):  # Пробегаемся по всем покупкам
        volume = bids[i]['volume']  # Объем
        price = bids[i]['price']  # Цена
        print(f"\t\t\t {price:9} \t {volume:7}")

    if len(asks) > 0 and len(bids) > 0:  # Если в стакане что-то есть
        closest_ask_to_sell = asks[-1]  # Лучшая цена продажи
        closest_bid_to_buy = bids[0]  # Лучшая цена покупки
        print(f'\nЛучшее предложение, продажа по: {closest_ask_to_sell}, покупка по: {closest_bid_to_buy}\n')

    sleep_secs = 5  # Кол-во секунд получения стакана
    print(f'Подписка на стакан {exchange}.{symbol}')
    ap_provider.OnChangeOrderBook = lambda response: print(response)  # Перехватываем обработку события изменения стакана
    guid = ap_provider.order_book_get_and_subscribe(exchange, symbol)  # Получаем код пописки
    print(f'Код подписки: {guid}')
    print(f'{sleep_secs} секунд стакана')
    time.sleep(sleep_secs)  # Ждем кол-во секунд получения стакана
    print(f'Отмена подписки на стакан: {ap_provider.unsubscribe(guid)}')  # Отписываеся от стакана
    ap_provider.OnChangeOrderBook = ap_provider.default_handler  # Возвращаем обработчик по умолчанию

    # Котировки
    print(f'Текущие котировки {exchange}.{symbol}')
    quotes = ap_provider.get_quotes(f'{exchange}:{symbol}')[0]  # Последнюю котировку получаем через запрос
    print(quotes)
    print(f'Последняя цена сделки: {quotes["last_price"]}')

    sleep_secs = 5  # Кол-во секунд получения котировок
    print(f'Подписка на котировки {exchange}.{symbol}')
    ap_provider.OnNewQuotes = lambda response: print(response)  # Перехватываем обработку события прихода новой котировки
    guid = ap_provider.quotes_subscribe(exchange, symbol)  # Получаем код пописки
    print(f'Код подписки: {guid}')
    print(f'{sleep_secs} секунд котировок')
    time.sleep(sleep_secs)  # Ждем кол-во секунд получения обезличенных сделок
    print(f'Отмена подписки на котировки: {ap_provider.unsubscribe(guid)}')  # Отписываеся от стакана
    ap_provider.OnNewQuotes = ap_provider.default_handler  # Возвращаем обработчик по умолчанию

    # Выход
    ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket
