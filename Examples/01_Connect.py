from datetime import datetime, timedelta  # Дата и время
import logging  # Выводим данные на консоль и в файл
from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config, ConfigDemo  # Файл конфигурации


def print_bar(response):
    """Вывод на консоль полученного бара"""
    seconds = response['data']['time']  # Время в Alor OpenAPI V2 передается в секундах, прошедших с 01.01.1970 00:00 UTC
    dt_msk = datetime.utcfromtimestamp(seconds) if type(tf) is str else ap_provider.utc_timestamp_to_msk_datetime(seconds)  # Дневные бары и выше ставим на начало дня по UTC. Остальные - по МСК
    str_dt_msk = dt_msk.strftime('%d.%m.%Y') if type(tf) is str else dt_msk.strftime('%d.%m.%Y %H:%M:%S')  # Для дневных баров и выше показываем только дату. Для остальных - дату и время по МСК
    guid = response['guid']  # Код подписки
    subscription = ap_provider.subscriptions[guid]  # Подписка
    logging.info(f'{subscription["exchange"]}.{subscription["code"]} ({subscription["tf"]}) - {str_dt_msk} - Open = {response["data"]["open"]}, High = {response["data"]["high"]}, Low = {response["data"]["low"]}, Close = {response["data"]["close"]}, Volume = {response["data"]["volume"]}')


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    ap_provider = AlorPy(Config.UserName, Config.RefreshToken)  # Провайдер работает со счетом по токену (из файла Config.py) Подключаемся к торговому счету
    # ap_provider2 = AlorPy(ConfigDemo.UserName, ConfigDemo.RefreshToken, True)  # Подключаемся к демо счету. Для каждого счета будет создан свой экземпляр AlorPy
    # print(f'\nЭкземпляры класса совпадают: {ap_provider2 is ap_provider}')
    # ap_provider2.CloseWebSocket()  # Второй провайдер больше не нужен. Закрываем его поток подписок

    logging.root.name = 'AlorPyConnect'  # Название лога
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%d.%m.%Y %H:%M:%S',  # Формат сообщения и даты
                        level=logging.INFO, handlers=[logging.FileHandler('AlorPyConnect.log'), logging.StreamHandler()])  # Уровень логируемых событий. Лог записываем в файл и выводим на консоль
    logging.Formatter.converter = lambda *args: datetime.now(tz=ap_provider.tz_msk).timetuple()  # В логе время указываем по МСК

    # Проверяем работу запрос/ответ
    seconds_from = ap_provider.get_time()  # Время в Alor OpenAPI V2 передается в секундах, прошедших с 01.01.1970 00:00 UTC
    logging.info(f'Дата и время на сервере: {ap_provider.utc_timestamp_to_msk_datetime(seconds_from)}')  # В AlorPy это время можно перевести в МСК для удобства восприятия

    # Проверяем работу подписок
    exchange = 'MOEX'  # Код биржи MOEX или SPBX
    symbol = 'SBER'  # Тикер
    # symbol = 'SiU3'  # Для фьючерсов: <Код тикера><Месяц экспирации: 3-H, 6-M, 9-U, 12-Z><Последняя цифра года>
    tf = 60  # 60 = 1 минута, 300 = 5 минут, 3600 = 1 час, 'D' = день, 'W' = неделя, 'M' = месяц, 'Y' = год
    days = 3  # Кол-во последних календарных дней, за которые берем историю

    ap_provider.OnEntering = lambda: logging.info('OnEntering. Начало входа (Thread)')
    ap_provider.OnEnter = lambda: logging.info('OnEnter. Вход (Thread)')
    ap_provider.OnConnect = lambda: logging.info('OnConnect. Подключение к серверу (Task)')
    ap_provider.OnResubscribe = lambda: logging.info('OnResubscribe. Возобновление подписок (Task)')
    ap_provider.OnReady = lambda: logging.info('OnReady. Готовность к работе (Task)')
    ap_provider.OnDisconnect = lambda: logging.info('OnDisconnect. Отключение от сервера (Task)')
    ap_provider.OnTimeout = lambda: logging.info('OnTimeout. Таймаут (Task)')
    ap_provider.OnError = lambda response: logging.info(f'OnError. {response} (Task)')
    ap_provider.OnCancel = lambda: logging.info('OnCancel. Отмена (Task)')
    ap_provider.OnExit = lambda: logging.info('OnExit. Выход (Thread)')
    ap_provider.OnNewBar = print_bar  # Перед подпиской перехватим ответы

    seconds_from = ap_provider.msk_datetime_to_utc_timestamp(datetime.now() - timedelta(days=days))  # За последние дни. В секундах, прошедших с 01.01.1970 00:00 UTC
    guid = ap_provider.bars_get_and_subscribe(exchange, symbol, tf, seconds_from, 1_000_000)  # Подписываемся на бары, получаем guid подписки
    subscription = ap_provider.subscriptions[guid]  # Получаем данные подписки
    logging.info(f'Подписка на сервере: {guid} {subscription}')
    logging.info(f'На бирже {subscription["exchange"]} тикер {subscription["code"]} подписан на новые бары через WebSocket на временнОм интервале {subscription["tf"]}. Код подписки {guid}')

    # Выход
    input('\nEnter - выход\n')
    ap_provider.unsubscribe(guid)  # Отписываемся от получения новых баров
    logging.info(f'Отмена подписки {guid}. Закрытие WebSocket по всем правилам займет некоторое время')
    ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket
