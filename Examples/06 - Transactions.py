from time import sleep  # Задержка в секундах перед выполнением операций

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config, TradeServerCode, FutServerCode  # Файл конфигурации


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    ap_provider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету. Логин и Refresh Token берутся из файла Config.py
    ap_provider.OnError = lambda error: print(error)  # Будем выводить ошибки торговли

    exchange = 'MOEX'  # Код биржи MOEX или SPBX

    # Для РЦБ
    symbol = 'SBER'  # Тикер
    trade_server_code = TradeServerCode  # Торговый сервер РЦБ
    portfolio = Config.PortfolioStocks  # Портфель фондового рынка

    # Для фьючерсов
    # symbol = 'SI-6.23'  # Для фьючерсов: <Код тикера>-<Месяц экспирации: 3, 6, 9, 12>.<Две последнии цифры года>
    # symbol = 'RTS-6.23'
    # trade_server_code = FutServerCode  # Торговый сервер фьючерсов
    # portfolio = Config.PortfolioFutures  # Портфель фьючерсов

    si = ap_provider.get_symbol(exchange, symbol)  # Получаем информацию о тикере
    min_step = si['minstep']  # Минимальный шаг цены

    quotes = ap_provider.get_quotes(f'{exchange}:{symbol}')[0]  # Последнюю котировку получаем через запрос
    last_price = quotes['last_price']  # Последняя цена сделки
    print(f'Последняя цена сделки {exchange}.{symbol}: {last_price}')

    # Обработчики подписок
    ap_provider.OnOrder = lambda response: print(f'Заявка - {response["data"]}')  # Обработка заявок
    ap_provider.OnStopOrder = lambda response: print(f'Стоп заявка - {response["data"]}')  # Обработка стоп заявок
    ap_provider.OnPosition = lambda response: print(f'Позиция - {response["data"]}')  # Обработка позиций
    ap_provider.OnTrade = lambda response: print(f'Сделка - {response["data"]}')  # Обработка сделок

    # Создание подписок
    orders_guid = ap_provider.orders_get_and_subscribe_v2(portfolio, exchange)  # Подписка на заявки
    print(f'Подписка на заявки {orders_guid} создана')
    stop_orders_guid = ap_provider.stop_orders_get_and_subscribe(portfolio, exchange)  # Подписка на стоп заявки
    print(f'Подписка на стоп заявки {stop_orders_guid} создана')
    positions_guid = ap_provider.positions_get_and_subscribe_v2(portfolio, exchange)  # Подписка на позиции
    print(f'Подписка на позиции {positions_guid} создана')
    trades_guid = ap_provider.trades_get_and_subscribe_v2(portfolio, exchange)  # Подписка на сделки
    print(f'Подписка на сделки {trades_guid} создана')

    sleep(10)  # Ждем 10 секунд

    # Новая рыночная заявка (открытие позиции)
    # print(f'Заявка {exchange}.{symbol} на покупку минимального лота по рыночной цене')
    # response = ap_provider.CreateMarketOrder(portfolio, exchange, symbol, 'buy', 1)
    # print(response)
    #
    # sleep(10)  # Ждем 10 секунд

    # Новая рыночная заявка (закрытие позиции)
    # print(f'Заявка {exchange}.{symbol} на продажу минимального лота по рыночной цене')
    # response = ap_provider.CreateMarketOrder(portfolio, exchange, symbol, 'sell', 1)
    # print(response)
    #
    # sleep(10)  # Ждем 10 секунд

    # Новая лимитная заявка
    limit_price = last_price * 0.99  # Лимитная цена на 1% ниже последней цены сделки
    limit_price = limit_price // min_step * min_step  # Округляем цену кратно минимальному шагу цены
    print(f'Заявка {exchange}.{symbol} на покупку минимального лота по лимитной цене {limit_price}')
    response = ap_provider.create_limit_order(portfolio, exchange, symbol, 'buy', 1, limit_price)
    order_id = response['orderNumber']  # Номер заявки
    print(f'Номер заявки: {order_id}')

    sleep(10)  # Ждем 10 секунд

    # Удаление существующей лимитной заявки
    print(f'Удаление заявки: {order_id}')
    response = ap_provider.delete_order(portfolio, exchange, order_id, False)
    print(f'Статус: {response}')

    sleep(10)  # Ждем 10 секунд

    # Новая стоп заявка
    portfolios = ap_provider.get_portfolios()  # Получаем все портфели
    account = None  # Счет получим из портфеля
    for p in portfolios:  # Пробегаемся по всем портфелям
        if portfolios[p][0]['portfolio'] == portfolio:  # Если это наш портфель
            account = portfolios[p][0]['tks']  # то получаем из него счет
            break  # Счет найден, дальше поиск вести не нужно
    stop_price = last_price * 1.01  # Стоп цена на 1% выше последней цены сделки
    stop_price = stop_price // min_step * min_step  # Округляем цену кратно минимальному шагу цены
    print(f'Заявка {exchange}.{symbol} на покупку минимального лота по стоп цене {stop_price}')
    response = ap_provider.create_stop_loss_order(trade_server_code, account, portfolio, exchange, symbol, 'buy', 1, stop_price)
    order_id = response['orderNumber']  # Номер заявки

    sleep(10)  # Ждем 10 секунд

    # Удаление существующей стоп заявки
    print(f'Удаление заявки: {order_id}')
    response = ap_provider.delete_stop_order(trade_server_code, portfolio, order_id, True)
    print(f'Статус: {response}')

    sleep(10)  # Ждем 10 секунд

    # Отмена подписок
    print(f'Подписка на заявки {ap_provider.unsubscribe(orders_guid)} отменена')
    print(f'Подписка на стоп заявки {ap_provider.unsubscribe(stop_orders_guid)} отменена')
    print(f'Подписка на позиции {ap_provider.unsubscribe(positions_guid)} отменена')
    print(f'Подписка на сделки {ap_provider.unsubscribe(trades_guid)} отменена')

    # Сброс обработчиков подписок
    ap_provider.OnOrder = ap_provider.default_handler  # Заявки
    ap_provider.OnStopOrder = ap_provider.default_handler  # Стоп заявки
    ap_provider.OnPosition = ap_provider.default_handler  # Позиции
    ap_provider.OnTrade = ap_provider.default_handler  # Сделки

    ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket
