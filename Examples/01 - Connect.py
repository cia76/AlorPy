from datetime import datetime, timedelta  # Дата и время
from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config, ConfigDemo  # Файл конфигурации


def print_new_bar(response):
    """Сначала получим все сформированные бары с заданного времени. Затем будем получать несформированные бары до их завершения"""
    seconds = response['data']['time']  # Время в Alor OpenAPI V2 передается в секундах, прошедших с 01.01.1970 00:00 UTC
    dt_msk = datetime.utcfromtimestamp(seconds) if type(tf) is str else ap_provider.UTCTimeStampToMskDatetime(seconds)  # Дневные бары и выше ставим на начало дня по UTC. Остальные - по МСК
    guid = response['guid']  # Код подписки
    subscription = ap_provider.subscriptions[guid]  # Подписка
    print(f'{datetime.now().strftime("%d.%m.%Y %H:%M:%S")} - {subscription["exchange"]}.{subscription["code"]} ({subscription["tf"]}) - {dt_msk} - Open = {response["data"]["open"]}, High = {response["data"]["high"]}, Low = {response["data"]["low"]}, Close = {response["data"]["close"]}, Volume = {response["data"]["volume"]}')


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    ap_provider = AlorPy(Config.UserName, Config.RefreshToken)  # Провайдер работает со счетом по токену (из файла Config.py) Подключаемся к торговому счету
    # ap_provider2 = AlorPy(ConfigDemo.UserName, ConfigDemo.RefreshToken, True)  # Подключаемся к демо счету. Для каждого счета будет создан свой экземпляр AlorPy
    # print(f'\nЭкземпляры класса совпадают: {ap_provider2 is ap_provider}')
    # ap_provider2.CloseWebSocket()  # Второй провайдер больше не нужен. Закрываем его поток подписок

    # Проверяем работу запрос/ответ
    seconds_from = ap_provider.GetTime()  # Время в Alor OpenAPI V2 передается в секундах, прошедших с 01.01.1970 00:00 UTC
    print(f'\nДата и время на сервере: {ap_provider.UTCTimeStampToMskDatetime(seconds_from)}')  # В AlorPy это время можно перевести в МСК для удобства восприятия

    # Проверяем работу подписок
    exchange = 'MOEX'  # Код биржи MOEX или SPBX
    symbol = 'SBER'  # Тикер
    # symbol = 'SiM3'  # Для фьючерсов: <Код тикера><Месяц экспирации: 3-H, 6-M, 9-U, 12-Z><Последняя цифра года>
    tf = 60  # 60 = 1 минута, 300 = 5 минут, 3600 = 1 час, 'D' = день, 'W' = неделя, 'M' = месяц, 'Y' = год
    days = 3  # Кол-во последних календарных дней, за которые берем историю

    ap_provider.OnEntering = lambda: print('- OnEntering. Начало входа (Thread)')
    ap_provider.OnEnter = lambda: print('- OnEnter. Вход (Thread)')
    ap_provider.OnConnect = lambda: print('- OnConnect. Подключение к серверу (Task)')
    ap_provider.OnResubscribe = lambda: print('- OnResubscribe. Возобновление подписок (Task)')
    ap_provider.OnReady = lambda: print('- OnReady. Готовность к работе (Task)')
    ap_provider.OnDisconnect = lambda: print('- OnDisconnect. Отключение от сервера (Task)')
    ap_provider.OnTimeout = lambda: print('- OnTimeout. Таймаут (Task)')
    ap_provider.OnError = lambda response: print(f'- OnError. {response} (Task)')
    ap_provider.OnCancel = lambda: print('- OnCancel. Отмена (Task)')
    ap_provider.OnExit = lambda: print('- OnExit. Выход (Thread)')
    ap_provider.OnNewBar = print_new_bar  # Перед подпиской перехватим ответы

    seconds_from = ap_provider.MskDatetimeToUTCTimeStamp(datetime.now() - timedelta(days=days))  # За последние дни. В секундах, прошедших с 01.01.1970 00:00 UTC
    guid = ap_provider.BarsGetAndSubscribe(exchange, symbol, tf, seconds_from)  # Подписываемся на бары, получаем guid подписки
    while guid not in ap_provider.subscriptions:  # Подписка идет в отдельном потоке. Возможно, ее еще нет
        pass  # Ждем, пока она не появится в справочнике подписок
    subscription = ap_provider.subscriptions[guid]  # Получаем данные подписки
    print('\nПодписка на сервере:', guid, subscription)
    print(f'На бирже {subscription["exchange"]} тикер {subscription["code"]} подписан на новые бары через WebSocket на временнОм интервале {subscription["tf"]}. Код подписки {guid}')

    # Выход
    input('Enter - выход\n')
    ap_provider.Unsubscribe(guid)  # Отписываемся от получения новых баров
    print(f'Отмена подписки {guid}. Закрытие WebSocket по всем правилам займет некоторое время')
    ap_provider.CloseWebSocket()  # Перед выходом закрываем соединение с WebSocket
