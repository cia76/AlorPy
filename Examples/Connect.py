import logging  # Выводим лог на консоль и в файл
from datetime import datetime, timedelta, UTC

from AlorPy import AlorPy  # Работа с АЛОР Брокер API


# noinspection PyShadowingNames
def on_new_bar(response):  # Обработчик события прихода нового бара
    response_data = response['data']  # Данные бара
    utc_timestamp = response_data['time']  # Время в АЛОР Брокер API передается в секундах, прошедших с 01.01.1970 00:00 UTC
    dt_msk = datetime.fromtimestamp(utc_timestamp, UTC) if type(tf) is str else ap_provider.timestamp_to_msk_datetime(utc_timestamp)  # Дневные бары и выше ставим на начало дня по UTC. Остальные - по МСК
    str_dt_msk = dt_msk.strftime('%d.%m.%Y') if type(tf) is str else dt_msk.strftime('%d.%m.%Y %H:%M:%S')  # Для дневных баров и выше показываем только дату. Для остальных - дату и время по МСК
    # subscription = ap_provider.subscriptions[response['guid']]  # Получаем данные подписки
    logger.info(f'{str_dt_msk} O:{response_data["open"]} H:{response_data["high"]} L:{response_data["low"]} C:{response_data["close"]} V:{response_data["volume"]}')


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    logger = logging.getLogger('AlorPy.Connect')  # Будем вести лог
    ap_provider = AlorPy()  # Подключаемся ко всем торговым счетам
    # ap_provider = AlorPy(demo=True)  # Подключаемся к демо счетам

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                        datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                        level=logging.INFO,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                        handlers=[logging.FileHandler('Connect.log', encoding='utf-8'), logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
    logging.Formatter.converter = lambda *args: datetime.now(tz=ap_provider.tz_msk).timetuple()  # В логе время указываем по МСК
    logging.getLogger('asyncio').setLevel(logging.CRITICAL + 1)  # Не пропускать в лог
    logging.getLogger('urllib3').setLevel(logging.CRITICAL + 1)  # события
    logging.getLogger('websockets').setLevel(logging.CRITICAL + 1)  # в этих библиотеках

    # Проверяем работу запрос/ответ
    dt_local = datetime.now(ap_provider.tz_msk)  # Текущее время
    seconds_from = float(ap_provider.get_time())  # Время в АЛОР Брокер API передается в секундах, прошедших с 01.01.1970 00:00 UTC
    dt_server = datetime.fromtimestamp(seconds_from, ap_provider.tz_msk)  # Получаем время на сервере
    td = dt_server - dt_local  # Разница во времени в виде timedelta
    logger.info(f'Локальное время МСК : {dt_local:%d.%m.%Y %H:%M:%S}')
    logger.info(f'Время на сервере    : {dt_server:%d.%m.%Y %H:%M:%S}')
    logger.info(f'Разница во времени  : {td}')

    # Проверяем работу подписок
    exchange = 'MOEX'  # Код биржи MOEX или SPBX
    symbol = 'SBER'  # Тикер
    tf = 60  # 60 = 1 минута, 300 = 5 минут, 3600 = 1 час, 'D' = день, 'W' = неделя, 'M' = месяц, 'Y' = год
    days = 3  # Кол-во последних календарных дней, за которые берем историю
    logger.info(f'Подписка на {tf} бары тикера: {exchange}.{symbol} с историей в днях: {days}')
    ap_provider.on_new_bar.subscribe(on_new_bar)  # Подписываемся на новые бары
    seconds_from = ap_provider.msk_datetime_to_timestamp(datetime.now() - timedelta(days=days))  # За последние дни. В секундах, прошедших с 01.01.1970 00:00 UTC
    guid = ap_provider.bars_get_and_subscribe(exchange, symbol, tf, seconds_from=seconds_from, frequency=1_000_000_000)  # Подписываемся на бары, получаем guid подписки
    subscription = ap_provider.subscriptions[guid]  # Получаем данные подписки
    logger.info(f'Подписка на сервере: {guid} {subscription}')
    logger.info(f'На бирже {subscription["exchange"]} тикер {subscription["code"]} подписан на новые бары через WebSocket на временнОм интервале {subscription["tf"]}. Код подписки {guid}')

    # Выход
    input('\nEnter - выход\n')
    ap_provider.on_new_bar.unsubscribe(on_new_bar)  # Отменяем подписку на новые бары
    ap_provider.unsubscribe(guid)  # Отписываемся от получения новых баров
    logger.info(f'Отмена подписки {guid}. Закрытие WebSocket по всем правилам займет некоторое время')
    ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket
