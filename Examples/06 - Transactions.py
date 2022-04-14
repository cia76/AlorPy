import time

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from Config import Config  # Файл конфигурации


def PrintCallback(response):
    print(response)


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    apProvider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету. Логин и Refresh Token берутся из файла Config.py
    # apProvider = AlorPy(Config.DemoUserName, Config.DemoRefreshToken, True)  # Подключаемся к демо счету

    exchange = 'MOEX'  # Код биржи MOEX или SPBX

    # Для РЦБ
    symbol = 'SBER'  # Тикер
    tradeServerCode = Config.TradeServerCode  # Торговый сервер РЦБ
    portfolio = Config.PortfolioStocks  # Портфель фондового рынка
    account = Config.AccountStocks  # Счет фондового рынка

    # Для фьючерсов
    # symbol = 'SiH2'  # Для фьючерсов: <Код тикера><Месяц экспирации: 3-H, 6-M, 9-U, 12-Z><Последняя цифра года>
    # tradeServerCode = Config.FutServerCode  # Торговый сервер фьючерсов
    # portfolio = Config.PortfolioFutures  # Портфель фьючерсов
    # account = Config.AccountFutures  # Счет фьючерсов

    symbolInfo = apProvider.GetSymbol(exchange, symbol)  # Получаем информацию о тикере
    minStep = symbolInfo["minstep"]  # Минимальный шаг цены

    quotes = apProvider.GetQuotes(f'{exchange}:{symbol}')[0]  # Последнюю котировку получаем через запрос
    lastPrice = quotes["last_price"]  # Последняя цена сделки
    print(f'Последняя цена сделки {exchange}.{symbol}: {lastPrice}')

    apProvider.OnOrder = PrintCallback  # Заявки
    apProvider.OnStopOrder = PrintCallback  # Стоп заявки
    apProvider.OnPosition = PrintCallback  # Позиции
    apProvider.OnTrade = PrintCallback  # Сделки
    ordersGuid = apProvider.OrdersGetAndSubscribeV2(portfolio, exchange)  # Заявки
    stopOrderGuid = apProvider.StopOrdersGetAndSubscribe(portfolio, exchange)  # Стоп заявки
    positionsGuid = apProvider.PositionsGetAndSubscribeV2(portfolio, exchange)  # Позиции
    tradesGuid = apProvider.TradesGetAndSubscribeV2(portfolio, exchange)  # Сделки

    # Новая лимитная заявка
    limitPrice = lastPrice * 0.99  # Лимитная цена на 1% ниже последней цены сделки
    limitPrice = round(limitPrice / minStep) * minStep  # Округляем цену кратно минимальному шагу цены
    print(f'Заявка {exchange}.{symbol} на покупку минимального лота по лимитной цене {limitPrice}')
    response = apProvider.CreateLimitOrder(portfolio, exchange, symbol, 'buy', 1, limitPrice)
    orderId = response['orderNumber']  # Номер заявки
    print(f'Номер заявки: {orderId}')
    time.sleep(10)

    # Удаление существующей лимитной заявки
    print(f'Удаление заявки: {orderId}')
    response = apProvider.DeleteOrder(portfolio, exchange, orderId, False)
    time.sleep(10)

    # Новая стоп заявка
    stopPrice = lastPrice * 1.01  # Стоп цена на 1% выше последней цены сделки
    stopPrice = round(stopPrice / minStep) * minStep  # Округляем цену кратно минимальному шагу цены
    print(f'Заявка {exchange}.{symbol} на покупку минимального лота по стоп цене {stopPrice}')
    response = apProvider.CreateStopLossOrder(tradeServerCode, account, portfolio, exchange, symbol, 'buy', 1, stopPrice)
    orderId = response['orderNumber']  # Номер заявки
    time.sleep(10)

    # Удаление существующей стоп заявки
    print(f'Удаление заявки: {orderId}')
    response = apProvider.DeleteStopOrder(tradeServerCode, portfolio, orderId, True)
    time.sleep(10)

    # Выход
    apProvider.OnOrder = apProvider.DefaultHandler  # Заявки
    apProvider.OnStopOrder = apProvider.DefaultHandler  # Стоп заявки
    apProvider.OnPosition = apProvider.DefaultHandler  # Позиции
    apProvider.OnTrade = apProvider.DefaultHandler  # Сделки

    apProvider.CloseWebSocket()  # Перед выходом закрываем соединение с WebSocket
