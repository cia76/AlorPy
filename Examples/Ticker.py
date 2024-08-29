import logging  # Выводим лог на консоль и в файл
from datetime import datetime  # Дата и время
from math import log10  # Кол-во десятичных знаков будем получать из шага цены через десятичный логарифм

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    logger = logging.getLogger('AlorPy.Ticker')  # Будем вести лог
    ap_provider = AlorPy()  # Подключаемся ко всем торговым счетам

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                        datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                        level=logging.DEBUG,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                        handlers=[logging.FileHandler('Ticker.log'), logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
    logging.Formatter.converter = lambda *args: datetime.now(tz=ap_provider.tz_msk).timetuple()  # В логе время указываем по МСК
    logging.getLogger('urllib3').setLevel(logging.CRITICAL + 1)  # Пропускаем события запросов

    # Формат короткого имени для фьючерсов: <Код тикера><Месяц экспирации: 3-H, 6-M, 9-U, 12-Z><Последняя цифра года>. Пример: SiU3, RIU3
    # Формат полного имени для фьючерсов: <Код тикера заглавными буквами>-<Месяц экспирации: 3, 6, 9, 12>.<Последние 2 цифры года>. Пример: SI-9.23, RTS-9.23
    datanames = ('TQBR.SBER', 'TQBR.HYDR', 'SPBFUT.SiU4', 'SPBFUT.RIU4', 'SPBFUT.BRU4', 'SPBFUT.CNYRUBF')  # Кортеж тикеров

    for dataname in datanames:  # Пробегаемся по всем тикерам
        board, symbol = ap_provider.dataname_to_board_symbol(dataname)  # Код режима торгов и тикер
        exchange = ap_provider.get_exchange(board, symbol)  # Биржа тикера
        if not exchange:  # Если биржа не получена (тикер не найден)
            logger.warning(f'Биржа для тикера {board}.{symbol} не найдена')
            continue  # то переходим к следующему тикеру, дальше не продолжаем
        si = ap_provider.get_symbol(exchange, symbol)  # Получаем информацию о тикере
        logger.debug(f'Ответ от сервера: {si}')
        logger.info(f'Информация о тикере {si["primary_board"]}.{si["symbol"]} ({si["shortname"]}, {si["type"]}) на бирже {si["exchange"]}')
        logger.info(f'- Валюта: {si["currency"]}')
        lot_size = si['lotsize'] if si['market'] == 'FOND' else si['facevalue']  # Лот для фондового и срочного/валютного рынков
        logger.info(f'- Лот: {lot_size}')
        min_price_step = si['minstep']  # Шаг цены
        logger.info(f'- Шаг цены: {min_price_step}')
        logger.info(f'- Кол-во десятичных знаков: {si["decimals"]}')
        trade_account = next((account for account in ap_provider.accounts if board in account['boards']), None)
        if not trade_account:  # Если торговый счет не найден
            logger.error('Торговый счет не найден')
        else:  # Торговый счет найден
            logger.info(f'- Торговый счет: #{trade_account["account_id"]}, Договор: {trade_account["agreement"]}, Портфель: {trade_account["portfolio"]} ({"Фондовый" if trade_account["type"] == "securities" else "Срочный" if trade_account["type"] == "derivatives" else "Валютный" if trade_account["type"] == "fx" else "Неизвестный"} рынок)')
        quotes = ap_provider.get_quotes(f'{exchange}:{symbol}')[0]  # Последнюю котировку получаем через запрос
        last_price = quotes['last_price'] if quotes else None  # Последняя цена сделки
        logger.info(f'- Последняя цена сделки: {last_price}')
        step_price = si['pricestep']  # Стоимость шага цены
        logger.info(f'- Стоимость шага цены: {step_price} руб.')
        if lot_size > 1 and step_price:  # Если есть лот и стоимость шага цены
            lot_price = last_price // min_price_step * step_price  # Цена за лот в рублях
            logger.info(f'- Цена за лот: {last_price} / {min_price_step} * {step_price} = {lot_price} руб.')
            pcs_price = lot_price / lot_size  # Цена за штуку в рублях
            logger.info(f'- Цена за штуку: {lot_price} / {lot_size} = {pcs_price} руб.')
            logger.info(f'- Последняя цена сделки: {ap_provider.price_to_alor_price(exchange, symbol, pcs_price)} из цены за штуку в рублях')

    ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket
