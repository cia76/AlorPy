import logging  # Выводим лог на консоль и в файл
from datetime import datetime  # Дата и время
from math import log10  # Кол-во десятичных знаков будем получать из шага цены через десятичный логарифм

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config  # Файл конфигурации


logger = logging.getLogger('AlorPy.Ticker')  # Будем вести лог


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    ap_provider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                        datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                        level=logging.DEBUG,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                        handlers=[logging.FileHandler('Ticker.log'), logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
    logging.Formatter.converter = lambda *args: datetime.now(tz=ap_provider.tz_msk).timetuple()  # В логе время указываем по МСК
    logging.getLogger('urllib3').setLevel(logging.CRITICAL + 1)  # Пропускаем события запросов

    exchange = 'MOEX'  # Биржа
    # Формат короткого имени для фьючерсов: <Код тикера><Месяц экспирации: 3-H, 6-M, 9-U, 12-Z><Последняя цифра года>. Пример: SiU3, RIU3
    # Формат полного имени для фьючерсов: <Код тикера заглавными буквами>-<Месяц экспирации: 3, 6, 9, 12>.<Последние 2 цифры года>. Пример: SI-9.23, RTS-9.23
    symbols = ('SBER', 'VTBR', 'SiH4', 'RIH4')  # Кортеж кодов тикеров

    for symbol in symbols:  # Пробегаемся по всем тикерам
        si = ap_provider.get_symbol(exchange, symbol)  # Получаем информацию о тикере
        logger.debug(f'Ответ от сервера: {si}')
        logger.info(f'Информация о тикере {si["primary_board"]}.{si["symbol"]} ({si["shortname"]}, {si["type"]}) на бирже {si["exchange"]}:')
        logger.info(f'- Валюта: {si["currency"]}')
        min_step = si['minstep']  # Шаг цены
        decimals = int(log10(1 / min_step) + 0.99)  # Из шага цены получаем кол-во десятичных знаков
        logger.info(f'- Кол-во десятичных знаков: {decimals}')
        logger.info(f'- Лот: {si["lotsize"]}')
        logger.info(f'- Шаг цены: {min_step}')

    ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket
