import logging  # Выводим лог на консоль и в файл
from datetime import datetime, timedelta  # Дата и время, временной интервал

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config, ConfigIIA, ConfigDemo  # Файл конфигурации


logger = logging.getLogger('AlorPy.Connect')  # Будем вести лог


# noinspection PyShadowingNames
def log_bar(response):  # Вывод в лог полученного бара
    seconds = response['data']['time']  # Время в Alor OpenAPI V2 передается в секундах, прошедших с 01.01.1970 00:00 UTC
    dt_msk = datetime.utcfromtimestamp(seconds) if type(tf) is str else ap_provider.utc_timestamp_to_msk_datetime(seconds)  # Дневные бары и выше ставим на начало дня по UTC. Остальные - по МСК
    str_dt_msk = dt_msk.strftime('%d.%m.%Y') if type(tf) is str else dt_msk.strftime('%d.%m.%Y %H:%M:%S')  # Для дневных баров и выше показываем только дату. Для остальных - дату и время по МСК
    guid = response['guid']  # Код подписки
    subscription = ap_provider.subscriptions[guid]  # Подписка
    logger.info(f'{subscription["exchange"]}.{subscription["code"]} ({subscription["tf"]}) - {str_dt_msk} - Open = {response["data"]["open"]}, High = {response["data"]["high"]}, Low = {response["data"]["low"]}, Close = {response["data"]["close"]}, Volume = {response["data"]["volume"]}')


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    ap_provider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету
    # ap_provider = AlorPy(ConfigIIA.UserName, ConfigIIA.RefreshToken)  # Подключаемся к торговому счету ИИС
    # ap_provider = AlorPy(ConfigDemo.UserName, ConfigDemo.RefreshToken, True)  # Подключаемся к демо счету

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                        datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                        level=logging.DEBUG,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                        handlers=[logging.FileHandler('Connect.log'), logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
    logging.Formatter.converter = lambda *args: datetime.now(tz=ap_provider.tz_msk).timetuple()  # В логе время указываем по МСК
    logging.getLogger('asyncio').setLevel(logging.CRITICAL + 1)  # Не пропускать в лог
    logging.getLogger('urllib3').setLevel(logging.CRITICAL + 1)  # события
    logging.getLogger('websockets').setLevel(logging.CRITICAL + 1)  # в этих библиотеках

    # Проверяем работу запрос/ответ
    seconds_from = ap_provider.get_time()  # Время в Alor OpenAPI V2 передается в секундах, прошедших с 01.01.1970 00:00 UTC
    logger.info(f'Дата и время на сервере: {ap_provider.utc_timestamp_to_msk_datetime(seconds_from):%d.%m.%Y %H:%M:%S}')  # В AlorPy это время можно перевести в МСК для удобства восприятия

    # Проверяем работу подписок
    exchange = 'MOEX'  # Код биржи MOEX или SPBX
    symbol = 'SBER'  # Тикер
    # symbol = 'SiH4'  # Для фьючерсов: <Код тикера><Месяц экспирации: 3-H, 6-M, 9-U, 12-Z><Последняя цифра года>
    tf = 60  # 60 = 1 минута, 300 = 5 минут, 3600 = 1 час, 'D' = день, 'W' = неделя, 'M' = месяц, 'Y' = год
    days = 3  # Кол-во последних календарных дней, за которые берем историю
    # tf = 'D'  # 1 день
    # days = 7  # Кол-во последних календарных дней, за которые берем историю

    ap_provider.OnEntering = lambda: logger.info('OnEntering. Начало входа (Thread)')
    ap_provider.OnEnter = lambda: logger.info('OnEnter. Вход (Thread)')
    ap_provider.OnConnect = lambda: logger.info('OnConnect. Подключение к серверу (Task)')
    ap_provider.OnResubscribe = lambda: logger.info('OnResubscribe. Возобновление подписок (Task)')
    ap_provider.OnReady = lambda: logger.info('OnReady. Готовность к работе (Task)')
    ap_provider.OnDisconnect = lambda: logger.info('OnDisconnect. Отключение от сервера (Task)')
    ap_provider.OnTimeout = lambda: logger.info('OnTimeout. Таймаут (Task)')
    ap_provider.OnError = lambda response: logger.info(f'OnError. {response} (Task)')
    ap_provider.OnCancel = lambda: logger.info('OnCancel. Отмена (Task)')
    ap_provider.OnExit = lambda: logger.info('OnExit. Выход (Thread)')
    ap_provider.OnNewBar = log_bar  # Перед подпиской перехватим ответы

    seconds_from = ap_provider.msk_datetime_to_utc_timestamp(datetime.now() - timedelta(days=days))  # За последние дни. В секундах, прошедших с 01.01.1970 00:00 UTC
    guid = ap_provider.bars_get_and_subscribe(exchange, symbol, tf, seconds_from, 1_000_000)  # Подписываемся на бары, получаем guid подписки
    subscription = ap_provider.subscriptions[guid]  # Получаем данные подписки
    logger.info(f'Подписка на сервере: {guid} {subscription}')
    logger.info(f'На бирже {subscription["exchange"]} тикер {subscription["code"]} подписан на новые бары через WebSocket на временнОм интервале {subscription["tf"]}. Код подписки {guid}')

    # Выход
    input('\nEnter - выход\n')
    ap_provider.unsubscribe(guid)  # Отписываемся от получения новых баров
    logger.info(f'Отмена подписки {guid}. Закрытие WebSocket по всем правилам займет некоторое время')
    ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket
