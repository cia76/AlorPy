import logging  # Выводим лог на консоль и в файл
from datetime import datetime  # Дата и время

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    logger = logging.getLogger('AlorPy.Accounts')  # Будем вести лог
    ap_provider = AlorPy()  # Подключаемся ко всем торговым счетам

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                        datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                        level=logging.DEBUG,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                        handlers=[logging.FileHandler('Accounts.log'), logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
    logging.Formatter.converter = lambda *args: datetime.now(tz=ap_provider.tz_msk).timetuple()  # В логе время указываем по МСК
    logging.getLogger('urllib3').setLevel(logging.CRITICAL + 1)  # Пропускаем события запросов

    # logger.info('Кол-во тикеров на бирже')
    # for exchange in ap_provider.exchanges:  # Пробегаемся по всем биржам
    #     securities = ap_provider.get_securities_exchange(exchange)  # Получаем все тикеры на бирже
    #     logger.info(f'- {exchange} {len(securities)}')
    #     boards = tuple(set(security['primary_board'] for security in securities))  # Все классы инструментов
    #     for board in boards:  # Пробегаемся по всем классам
    #         board_symbols = [security for security in securities if security['primary_board'] == board]
    #         logger.info(f'  - {board} {len(board_symbols)}')

    for account in ap_provider.accounts:  # Пробегаемся по всем счетам
        portfolio = account['portfolio']  # Портфель
        logger.info(f'Счет #{account["account_id"]}, Договор: {account["agreement"]}, Портфель: {portfolio}')
        for exchange in account['exchanges']:  # Пробегаемся по всем биржам
            logger.info(f'- Биржа {exchange}')
            for position in ap_provider.get_positions(portfolio, exchange, True):  # Пробегаемся по всем позициям без денежной позиции
                symbol = position['symbol']  # Тикер
                si = ap_provider.get_symbol(exchange, symbol)  # Информация о тикере
                size = position['qty'] * si['lotsize']  # Кол-во в штуках
                entry_price = ap_provider.alor_price_to_price(exchange, symbol, position['avgPrice'])  # Цена входа
                last_alor_price = ap_provider.price_to_alor_price(exchange, symbol, position['currentVolume'] / size)  # Последняя цена Алора
                last_price = ap_provider.alor_price_to_price(exchange, symbol, last_alor_price)  # Последняя цена
                logger.info(f'  - Позиция {si["board"]}.{symbol} ({position["shortName"]}) {size} @ {entry_price} / {last_price}')
            value = round(ap_provider.get_risk(portfolio, exchange)['portfolioLiquidationValue'], 2)  # Общая стоимость портфеля
            cash = next((position['volume'] for position in ap_provider.get_positions(portfolio, exchange, False) if position['symbol'] == 'RUB'), 0)  # Свободные средства через денежную позицию
            logger.info(f'  - Позиции {round(value - cash, 2)} + Свободные средства {cash} = {value}')
            orders = ap_provider.get_orders(portfolio, exchange)  # Получаем список активных заявок
            for order in orders:  # Пробегаемся по всем активным заявкам
                if order['status'] == 'working':  # Если заявка еще не исполнилась
                    logger.info(f'  - Заявка номер {order["id"]} {"Покупка" if order["side"] == "buy" else "Продажа"} {order["exchange"]}.{order["symbol"]} {order["qty"]} @ {order["price"]}')
            stop_orders = ap_provider.get_stop_orders(portfolio, exchange)  # Получаем список активных стоп заявок
            for stop_order in stop_orders:  # Пробегаемся по всем активным стоп заявкам
                if stop_order['status'] == 'working':  # Если заявка еще не исполнилась
                    logger.info(f'  - Стоп заявка номер {stop_order["id"]} {"Покупка" if stop_order["side"] == "buy" else "Продажа"} {stop_order["exchange"]}.{stop_order["symbol"]} {stop_order["qty"]} @ {stop_order["price"]}')

        ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket
