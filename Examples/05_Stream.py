import logging  # Выводим лог на консоль и в файл
from datetime import datetime  # Дата и время
from time import sleep  # Подписка на события по времени

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config  # Файл конфигурации


logger = logging.getLogger('AlorPy.Stream')  # Будем вести лог


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    ap_provider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                        datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                        level=logging.DEBUG,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                        handlers=[logging.FileHandler('Stream.log'), logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
    logging.Formatter.converter = lambda *args: datetime.now(tz=ap_provider.tz_msk).timetuple()  # В логе время указываем по МСК
    logging.getLogger('asyncio').setLevel(logging.CRITICAL + 1)  # Не пропускать в лог
    logging.getLogger('urllib3').setLevel(logging.CRITICAL + 1)  # события
    logging.getLogger('websockets').setLevel(logging.CRITICAL + 1)  # в этих библиотеках

    exchange = 'MOEX'  # Код биржи MOEX или SPBX
    symbol = 'SBER'  # Тикер
    # symbol = 'SiH4'  # Для фьючерсов: <Код тикера><Месяц экспирации: 3-H, 6-M, 9-U, 12-Z><Последняя цифра года>

    # Стакан
    logger.info(f'Текущий стакан {exchange}.{symbol}')
    order_book = ap_provider.get_order_book(exchange, symbol)  # Текущий стакан с максимальной глубиной 20 получаем через запрос
    logger.debug(order_book)
    if order_book['bids'] and order_book['asks']:
        logger.info(f'bids от {order_book["bids"][0]} до {order_book["bids"][-1]}, asks от {order_book["asks"][0]} до {order_book["asks"][-1]}')

    logger.info('Визуализация стакана котировок')
    asks = order_book['asks'][::-1]  # Продажи в обратном порядке
    for ask in asks:  # Пробегаемся по всем продажам
        logger.info(f'{ask["volume"]:7} \t {ask["price"]:9}')  # Объем и цена
    bids = order_book['bids']  # Покупки
    for bid in bids:  # Пробегаемся по всем покупкам
        logger.info(f'\t\t\t {bid["price"]:9} \t {bid["volume"]:7}')  # Цена и объем

    if len(asks) > 0 and len(bids) > 0:  # Если в стакане что-то есть
        closest_ask_to_sell = asks[-1]  # Лучшая цена продажи
        closest_bid_to_buy = bids[0]  # Лучшая цена покупки
        logger.info(f'Лучшее предложение, продажа по: {closest_ask_to_sell}, покупка по: {closest_bid_to_buy}')

    sleep_secs = 5  # Кол-во секунд получения стакана
    logger.info(f'{sleep_secs} секунд стакана')
    ap_provider.OnChangeOrderBook = lambda response: logger.info(f'Стакан - {response["data"]}')  # Обработка стакана
    guid = ap_provider.order_book_get_and_subscribe(exchange, symbol)  # Получаем код пописки
    logger.info(f'Подписка на стакан {guid} тикера {exchange}.{symbol} создана')
    sleep(sleep_secs)  # Ждем кол-во секунд получения стакана
    logger.info(f'Подписка на стакан {ap_provider.unsubscribe(guid)} отменена')  # Отписываеся от стакана
    ap_provider.OnChangeOrderBook = ap_provider.default_handler  # Возвращаем обработчик по умолчанию

    # Котировки
    logger.info(f'Текущие котировки {exchange}.{symbol}')
    quotes = ap_provider.get_quotes(f'{exchange}:{symbol}')[0]  # Последнюю котировку получаем через запрос
    logger.debug(quotes)
    logger.info(f'Последняя цена сделки: {quotes["last_price"]}')

    sleep_secs = 5  # Кол-во секунд получения котировок
    logger.info(f'{sleep_secs} секунд котировок')
    ap_provider.OnNewQuotes = lambda response: logger.info(f'Котировка - {response["data"]}')  # Обработка котировок
    guid = ap_provider.quotes_subscribe(exchange, symbol)  # Получаем код пописки
    logger.info(f'Подписка на котировки {guid} тикера {exchange}.{symbol} создана')
    sleep(sleep_secs)  # Ждем кол-во секунд получения обезличенных сделок
    logger.info(f'Подписка на котировки {ap_provider.unsubscribe(guid)} отменена')  # Отписываеся от котировок
    ap_provider.OnNewQuotes = ap_provider.default_handler  # Возвращаем обработчик по умолчанию

    # Выход
    ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket
