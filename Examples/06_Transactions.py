import logging  # Выводим лог на консоль и в файл
from datetime import datetime  # Дата и время
from time import sleep  # Задержка в секундах перед выполнением операций

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config, TradeServerCode, FutServerCode  # Файл конфигурации


logger = logging.getLogger('AlorPy.Transactions')  # Будем вести лог


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    ap_provider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету. Логин и Refresh Token берутся из файла Config.py
    ap_provider.OnError = lambda error: logger.error(error)  # Будем выводить ошибки торговли

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                        datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                        level=logging.DEBUG,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                        handlers=[logging.FileHandler('Transactions.log'), logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
    logging.Formatter.converter = lambda *args: datetime.now(tz=ap_provider.tz_msk).timetuple()  # В логе время указываем по МСК
    logging.getLogger('asyncio').setLevel(logging.CRITICAL + 1)  # Не пропускать в лог
    logging.getLogger('urllib3').setLevel(logging.CRITICAL + 1)  # события
    logging.getLogger('websockets').setLevel(logging.CRITICAL + 1)  # в этих библиотеках

    exchange = 'MOEX'  # Код биржи MOEX или SPBX

    symbol = 'SBER'  # Тикер
    trade_server_code = TradeServerCode  # Торговый сервер РЦБ
    portfolio = Config.PortfolioStocks  # Портфель фондового рынка

    # Алор понимает только такой формат фьючерсов. В остальных случаях он возвращает None после постановки заявки. Заявку не ставит
    # symbol = 'SI-3.24'  # Для фьючерсов: <Код тикера>-<Месяц экспирации: 3, 6, 9, 12>.<Две последнии цифры года>
    # symbol = 'RTS-3.24'
    # trade_server_code = FutServerCode  # Торговый сервер фьючерсов
    # portfolio = Config.PortfolioFutures  # Портфель фьючерсов

    si = ap_provider.get_symbol(exchange, symbol)  # Получаем информацию о тикере
    logger.debug(si)
    min_step = si['minstep']  # Минимальный шаг цены

    quotes = ap_provider.get_quotes(f'{exchange}:{symbol}')[0]  # Последнюю котировку получаем через запрос
    last_price = quotes['last_price']  # Последняя цена сделки
    logger.info(f'Последняя цена сделки {exchange}.{symbol}: {last_price}')

    # Обработчики подписок
    ap_provider.OnOrder = lambda response: logger.info(f'Заявка - {response["data"]}')  # Обработка заявок
    ap_provider.OnStopOrder = lambda response: logger.info(f'Стоп заявка - {response["data"]}')  # Обработка стоп заявок
    ap_provider.OnPosition = lambda response: logger.info(f'Позиция - {response["data"]}')  # Обработка позиций
    ap_provider.OnTrade = lambda response: logger.info(f'Сделка - {response["data"]}')  # Обработка сделок

    # Создание подписок
    orders_guid = ap_provider.orders_get_and_subscribe_v2(portfolio, exchange)  # Подписка на заявки
    logger.info(f'Подписка на заявки {orders_guid} создана')
    stop_orders_guid = ap_provider.stop_orders_get_and_subscribe(portfolio, exchange)  # Подписка на стоп заявки
    logger.info(f'Подписка на стоп заявки {stop_orders_guid} создана')
    positions_guid = ap_provider.positions_get_and_subscribe_v2(portfolio, exchange)  # Подписка на позиции
    logger.info(f'Подписка на позиции {positions_guid} создана')
    trades_guid = ap_provider.trades_get_and_subscribe_v2(portfolio, exchange)  # Подписка на сделки
    logger.info(f'Подписка на сделки {trades_guid} создана')

    sleep(10)  # Ждем 10 секунд

    # Новая рыночная заявка (открытие позиции)
    # logger.info(f'Заявка {exchange}.{symbol} на покупку минимального лота по рыночной цене')
    # response = ap_provider.create_market_order(portfolio, exchange, symbol, 'buy', 1)
    # logger.debug(response)
    # logger.info(f'Номер заявки: {response["orderNumber"]}')
    #
    # sleep(10)  # Ждем 10 секунд

    # Новая рыночная заявка (закрытие позиции)
    # logger.info(f'Заявка {exchange}.{symbol} на продажу минимального лота по рыночной цене')
    # response = ap_provider.create_market_order(portfolio, exchange, symbol, 'sell', 1)
    # logger.debug(response)
    # logger.info(f'Номер заявки: {response["orderNumber"]}')
    #
    # sleep(10)  # Ждем 10 секунд

    # Новая лимитная заявка
    limit_price = last_price * 0.99  # Лимитная цена на 1% ниже последней цены сделки
    limit_price = limit_price // min_step * min_step  # Округляем цену кратно минимальному шагу цены
    logger.info(f'Заявка {exchange}.{symbol} на покупку минимального лота по лимитной цене {limit_price}')
    response = ap_provider.create_limit_order(portfolio, exchange, symbol, 'buy', 1, limit_price)
    logger.debug(response)
    order_id = response['orderNumber']  # Номер заявки
    logger.info(f'Номер заявки: {order_id}')

    sleep(10)  # Ждем 10 секунд

    # Удаление существующей лимитной заявки
    logger.info(f'Удаление заявки: {order_id}')
    response = ap_provider.delete_order(portfolio, exchange, order_id, False)
    logger.info(f'Статус: {response}')

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
    logger.info(f'Заявка {exchange}.{symbol} на покупку минимального лота по стоп цене {stop_price}')
    response = ap_provider.create_stop_loss_order(trade_server_code, account, portfolio, exchange, symbol, 'buy', 1, stop_price)
    logger.debug(response)
    order_id = response['orderNumber']  # Номер заявки
    logger.info(f'Номер заявки: {order_id}')

    sleep(10)  # Ждем 10 секунд

    # Удаление существующей стоп заявки
    logger.info(f'Удаление стоп заявки: {order_id}')
    response = ap_provider.delete_stop_order(trade_server_code, portfolio, order_id, True)
    logger.info(f'Статус: {response}')

    sleep(10)  # Ждем 10 секунд

    # Отмена подписок
    logger.info(f'Подписка на заявки {ap_provider.unsubscribe(orders_guid)} отменена')
    logger.info(f'Подписка на стоп заявки {ap_provider.unsubscribe(stop_orders_guid)} отменена')
    logger.info(f'Подписка на позиции {ap_provider.unsubscribe(positions_guid)} отменена')
    logger.info(f'Подписка на сделки {ap_provider.unsubscribe(trades_guid)} отменена')

    # Сброс обработчиков подписок
    ap_provider.OnOrder = ap_provider.default_handler  # Заявки
    ap_provider.OnStopOrder = ap_provider.default_handler  # Стоп заявки
    ap_provider.OnPosition = ap_provider.default_handler  # Позиции
    ap_provider.OnTrade = ap_provider.default_handler  # Сделки

    # Выход
    ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket
