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
    datanames = ('TQBR.SBER', 'TQBR.VTBR', 'RFUD.SiH4', 'RFUD.RIH4')  # Кортеж тикеров

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
        logger.info(f'- Лот: {si["lotsize"]}')
        min_step = si['minstep']  # Шаг цены
        logger.info(f'- Шаг цены: {min_step}')
        decimals = int(log10(1 / min_step) + 0.99)  # Из шага цены получаем кол-во десятичных знаков
        logger.info(f'- Кол-во десятичных знаков: {decimals}')

    ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket
