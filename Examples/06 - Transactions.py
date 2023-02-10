from time import sleep  # Задержка в секундах перед выполнением операций

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config  # Файл конфигурации


opcodes = {'OrdersGetAndSubscribeV2': 'Заявка',
           'StopOrdersGetAndSubscribe': 'Стоп заявка',
           'PositionsGetAndSubscribeV2': 'Позиция',
           'TradesGetAndSubscribeV2': 'Сделка'}

def PrintCallback(response):
    """"Обработчик подписок"""
    opcode = response['subscription']['opcode']  # Тип подписки
    exchange = response['subscription']['exchange']  # Код биржи
    portfolio = response['subscription']['portfolio']  # Портфель
    data = response['data']  # Данные подписки
    print(f'{opcodes[opcode]}({exchange}, {portfolio}) - {data}')


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    apProvider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету. Логин и Refresh Token берутся из файла Config.py
    # apProvider = AlorPy(Config.DemoUserName, Config.DemoRefreshToken, True)  # Подключаемся к демо счету

    exchange = 'MOEX'  # Код биржи MOEX или SPBX

    # Для РЦБ
    symbol = 'SBER'  # Тикер
    tradeServerCode = Config.TradeServerCode  # Торговый сервер РЦБ
    portfolio = Config.PortfolioStocks  # Портфель фондового рынка

    # Для фьючерсов
    # symbol = 'SiH3'  # Для фьючерсов: <Код тикера><Месяц экспирации: 3-H, 6-M, 9-U, 12-Z><Последняя цифра года>
    # symbol = 'RIH3'
    # tradeServerCode = Config.FutServerCode  # Торговый сервер фьючерсов
    # portfolio = Config.PortfolioFutures  # Портфель фьючерсов

    si = apProvider.GetSymbol(exchange, symbol)  # Получаем информацию о тикере
    minStep = si['minstep']  # Минимальный шаг цены

    quotes = apProvider.GetQuotes(f'{exchange}:{symbol}')[0]  # Последнюю котировку получаем через запрос
    lastPrice = quotes['last_price']  # Последняя цена сделки
    print(f'Последняя цена сделки {exchange}.{symbol}: {lastPrice}')

    # Обработчики подписок
    apProvider.OnOrder = PrintCallback  # Обработка заявок
    apProvider.OnStopOrder = PrintCallback  # Обработка стоп заявок
    apProvider.OnPosition = PrintCallback  # Обработка позиций
    apProvider.OnTrade = PrintCallback  # Обработка сделок

    # Создание подписок
    ordersGuid = apProvider.OrdersGetAndSubscribeV2(portfolio, exchange)  # Подписка на заявки
    print(f'Подписка на заявки {ordersGuid} создана')
    stopOrdersGuid = apProvider.StopOrdersGetAndSubscribe(portfolio, exchange)  # Подписка на стоп заявки
    print(f'Подписка на стоп заявки {stopOrdersGuid} создана')
    positionsGuid = apProvider.PositionsGetAndSubscribeV2(portfolio, exchange)  # Подписка на позиции
    print(f'Подписка на позиции {positionsGuid} создана')
    tradesGuid = apProvider.TradesGetAndSubscribeV2(portfolio, exchange)  # Подписка на сделки
    print(f'Подписка на сделки {tradesGuid} создана')

    sleep(10)  # Ждем 10 секунд

    # Новая рыночная заявка (открытие позиции)
    # print(f'Заявка {exchange}.{symbol} на покупку минимального лота по рыночной цене')
    # response = apProvider.CreateMarketOrder(portfolio, exchange, symbol, 'buy', 1)
    # print(response)

    # sleep(10)  # Ждем 10 секунд

    # Новая рыночная заявка (закрытие позиции)
    # print(f'Заявка {exchange}.{symbol} на продажу минимального лота по рыночной цене')
    # response = apProvider.CreateMarketOrder(portfolio, exchange, symbol, 'sell', 1)
    # print(response)
    #
    # sleep(10)  # Ждем 10 секунд

    # Новая лимитная заявка
    limitPrice = lastPrice * 0.99  # Лимитная цена на 1% ниже последней цены сделки
    limitPrice = limitPrice // minStep * minStep  # Округляем цену кратно минимальному шагу цены
    print(f'Заявка {exchange}.{symbol} на покупку минимального лота по лимитной цене {limitPrice}')
    response = apProvider.CreateLimitOrder(portfolio, exchange, symbol, 'buy', 1, limitPrice)
    orderId = response['orderNumber']  # Номер заявки
    print(f'Номер заявки: {orderId}')

    sleep(10)  # Ждем 10 секунд

    # Удаление существующей лимитной заявки
    print(f'Удаление заявки: {orderId}')
    response = apProvider.DeleteOrder(portfolio, exchange, orderId, False)
    print(f'Статус: {response}')

    sleep(10)  # Ждем 10 секунд

    # Новая стоп заявка
    portfolios = apProvider.GetPortfolios()  # Получаем все портфели
    account = None  # Счет получим из портфеля
    for p in portfolios:  # Пробегаемся по всем портфелям
        if portfolios[p][0]['portfolio'] == portfolio:  # Если это наш портфель
            account = portfolios[p][0]['tks']  # то получаем из него счет
            break  # Счет найден, дальше поиск вести не нужно
    stopPrice = lastPrice * 1.01  # Стоп цена на 1% выше последней цены сделки
    stopPrice = stopPrice // minStep * minStep  # Округляем цену кратно минимальному шагу цены
    print(f'Заявка {exchange}.{symbol} на покупку минимального лота по стоп цене {stopPrice}')
    response = apProvider.CreateStopLossOrder(tradeServerCode, account, portfolio, exchange, symbol, 'buy', 1, stopPrice)
    orderId = response['orderNumber']  # Номер заявки

    sleep(10)  # Ждем 10 секунд

    # Удаление существующей стоп заявки
    print(f'Удаление заявки: {orderId}')
    response = apProvider.DeleteStopOrder(tradeServerCode, portfolio, orderId, True)
    print(f'Статус: {response}')

    sleep(10)  # Ждем 10 секунд

    # Отмена подписок
    print(f'Подписка на заявки {apProvider.Unsubscribe(ordersGuid)} отменена')
    print(f'Подписка на стоп заявки {apProvider.Unsubscribe(stopOrdersGuid)} отменена')
    print(f'Подписка на позиции {apProvider.Unsubscribe(positionsGuid)} отменена')
    print(f'Подписка на сделки {apProvider.Unsubscribe(tradesGuid)} отменена')

    # Сброс обработчиков подписок
    apProvider.OnOrder = apProvider.DefaultHandler  # Заявки
    apProvider.OnStopOrder = apProvider.DefaultHandler  # Стоп заявки
    apProvider.OnPosition = apProvider.DefaultHandler  # Позиции
    apProvider.OnTrade = apProvider.DefaultHandler  # Сделки

    apProvider.CloseWebSocket()  # Перед выходом закрываем соединение с WebSocket
