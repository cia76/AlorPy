import logging  # Выводим лог на консоль и в файл
from datetime import datetime  # Дата и время

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config, ConfigIIA, ConfigDemo  # Файлы конфигурации


logger = logging.getLogger('AlorPy.Accounts')  # Будем вести лог


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    ap_providers = []  # Счета будем хранить в виде списка
    ap_providers.append((Config.UserName, Config.RefreshToken,))  # Торговый счет
    ap_providers.append((ConfigIIA.UserName, ConfigIIA.RefreshToken,))  # ИИС
    # ap_providers.append((ConfigDemo.UserName, ConfigDemo.RefreshToken,))  # Демо счет для тестов

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                        datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                        level=logging.DEBUG,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                        handlers=[logging.FileHandler('Accounts.log'), logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
    logging.Formatter.converter = lambda *args: datetime.now(tz=ap_provider.tz_msk).timetuple()  # В логе время указываем по МСК
    logging.getLogger('urllib3').setLevel(logging.CRITICAL + 1)  # Пропускаем события запросов

    ap_provider = AlorPy(ap_providers[0][0], ap_providers[0][1])  # Подключаемся к торговому счету
    logger.info('Кол-во тикеров на бирже')
    for exchange in ap_provider.exchanges:  # Пробегаемся по всем биржам
        securities = ap_provider.get_securities_exchange(exchange)  # Получаем все тикеры на бирже
        logger.info(f'- {exchange} {len(securities)}')
        boards = tuple(set(security['primary_board'] for security in securities))  # Все классы инструментов
        for board in boards:  # Пробегаемся по всем классам
            board_symbols = [security for security in securities if security['primary_board'] == board]
            logger.info(f'  - {board} {len(board_symbols)}')

    for user_name, refresh_token in ap_providers:  # Пробегаемся по всем счетам
        logger.info(f'Учетная запись {user_name}')
        ap_provider = AlorPy(user_name, refresh_token)  # Подключаемся к счету
        portfolios = ap_provider.get_portfolios()  # Портфели: Фондовый рынок / Фьючерсы и опционы / Валютный рынок
        for p in portfolios:  # Пробегаемся по всем портфелям
            portfolio_name = portfolios[p][0]['portfolio']  # Название портфеля
            account = portfolios[p][0]['tks']  # Счет
            logger.info(f'- {p}: Портфель {portfolio_name}, Счет {account}')
            trade_servers_info = portfolios[p][0]['tradeServersInfo']  # Торговый сервер
            logger.info('  - Торговые серверы')
            for trade_server_info in trade_servers_info:  # Пробегаемся по всем торговым серверам
                logger.info(f'    - {trade_server_info["tradeServerCode"]} для контрактов {trade_server_info["contracts"]}')
            for exchange in ap_provider.exchanges:  # Пробегаемся по всем биржам
                logger.info(f'    - Биржа {exchange}')
                positions = ap_provider.get_positions(portfolio_name, exchange, True)  # Позиции без денежной позиции
                for position in positions:  # Пробегаемся по всем позициям
                    symbol = position['symbol']  # Тикер
                    symbol_info = ap_provider.get_symbol(exchange, symbol)  # Информация о тикере
                    size = position['qty'] * symbol_info['lotsize']  # Кол-во в штуках
                    entry_price = round(position['volume'] / size, 2)  # Цена входа
                    pl = position['unrealisedPl'] * symbol_info['priceMultiplier']  # Бумажная прибыль/убыток
                    last_price = round((position['volume'] + pl) / size, 2)  # Последняя цена
                    logger.info(f'      - Позиция {position["shortName"]} ({symbol}) {size} @ {entry_price} / {last_price}')
                money = ap_provider.get_money(portfolio_name, exchange)  # Денежная позиция
                logger.info(f'      - Позиции {round(money["portfolio"] - money["cash"], 2)} + Свободные средства {money["cash"]} = {round(money["portfolio"], 2)}')
                orders = ap_provider.get_orders(portfolio_name, exchange)  # Получаем список активных заявок
                for order in orders:  # Пробегаемся по всем активным заявкам
                    logger.info(f'      - Заявка номер {order["id"]} {"Покупка" if order["side"] == "buy" else "Продажа"} {order["exchange"]}.{order["symbol"]} {order["qty"]} @ {order["price"]}')
                stop_orders = ap_provider.get_stop_orders(portfolio_name, exchange)  # Получаем список активных стоп заявок
                for stop_order in stop_orders:  # Пробегаемся по всем активным стоп заявкам
                    logger.info(f'      - Стоп заявка номер {stop_order["id"]} {"Покупка" if stop_order["side"] == "buy" else "Продажа"} {stop_order["exchange"]}.{stop_order["symbol"]} {stop_order["qty"]} @ {stop_order["price"]}')

    ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket
