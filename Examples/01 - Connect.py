from datetime import datetime
from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config  # Файл конфигурации


def PrintNewBar(response):
    seconds = response['data']['time']  # Время в Alor OpenAPI V2 передается в секундах, прошедших с 01.01.1970 00:00 UTC
    dtMsk = datetime.utcfromtimestamp(seconds) if type(tf) is str else apProvider.UTCTimeStampToMskDatetime(seconds)  # Дневные бары и выше ставим на начало дня по UTC. Остальные - по МСК
    print(f'{datetime.now().strftime("%d.%m.%Y %H:%M:%S")} - {dtMsk} - Open = {response["data"]["open"]}, High = {response["data"]["high"]}, Low = {response["data"]["low"]}, Close = {response["data"]["close"]}, Volume = {response["data"]["volume"]}')


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    apProvider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету. Логин и Refresh Token берутся из файла Config.py
    # apProvider = AlorPy(Config.DemoUserName, Config.DemoRefreshToken, True)  # Подключаемся к демо счету

    # AlorPy - Singleton класс. Будет создан 1 экземпляр класса, на него будут все ссылки
    apProvider2 = AlorPy(Config.UserName, Config.RefreshToken)  # AlorPy - это Singleton класс. При попытке создания нового экземпляра получим ссылку на уже имеющийся экземпляр
    print(f'Экземпляры класса совпадают: {apProvider2 is apProvider}')

    # Проверяем работу API запрос/ответ. Запрашиваем и получаем время на сервере
    secondsFrom = apProvider.GetTime()  # Время в Alor OpenAPI V2 передается в секундах, прошедших с 01.01.1970 00:00 UTC
    print(f'Дата и время на сервере: {apProvider.UTCTimeStampToMskDatetime(secondsFrom)}')  # В AlorPy это время можно перевести в МСК для удобства восприятия

    # Проверяем работу WebSocket. Подписываемся на новые бары
    # Сначала получим все сформированные бары с заданного времени. Затем будем получать несформированные бары до их завершения
    exchange = 'MOEX'  # Код биржи MOEX или SPBX
    symbol = 'SBER'  # Тикер
    # symbol = 'SiH3'  # Для фьючерсов: <Код тикера><Месяц экспирации: 3-H, 6-M, 9-U, 12-Z><Последняя цифра года>
    tf = 60  # 60 = 1 минута, 300 = 5 минут, 3600 = 1 час, 'D' = день, 'W' = неделя, 'M' = месяц, 'Y' = год
    secondsFrom = apProvider.MskDatetimeToUTCTimeStamp(datetime(2023, 1, 16))  # С заданной даты/времени МСК, в секундах, прошедших с 01.01.1970 00:00 UTC
    apProvider.OnNewBar = PrintNewBar  # Перед подпиской перехватим ответы
    guid = apProvider.BarsGetAndSubscribe(exchange, symbol, tf, secondsFrom)  # Подписываемся на бары, получаем guid подписки
    print(f'На бирже {exchange} тикер {symbol} подписан на новые бары через WebSocket на временнОм интервале {tf}. Код подписки {guid}')

    # Выход
    input('Enter - выход\n')
    apProvider.Unsubscribe(guid)  # Отписываемся от получения новых баров
    print(f'Отмена подписки {guid}. Закрытие WebSocket по всем правилам займет некоторое время')
    apProvider.CloseWebSocket()  # Перед выходом закрываем соединение с WebSocket
