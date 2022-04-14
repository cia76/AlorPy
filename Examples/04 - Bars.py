from time import time
import os.path
import pandas as pd

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from Config import Config  # Файл конфигурации


def SaveCandlesToFile(exchange='MOEX', symbols=('SBER',), timeFrame='D', secondsFrom=0):
    for symbol in symbols:  # Пробегаемся по всем тикерам
        fileName = f'..\\..\\DataAlor\\{exchange}.{symbol}_{timeFrame}.txt'
        isFileExists = os.path.isfile(fileName)  # Существует ли файл
        if not isFileExists:  # Если файл не существует
            print(f'Файл {fileName} не найден и будет создан')
        else:  # Файл существует
            print(f'Получение файла {fileName}')
            fileBars = pd.read_csv(fileName, sep='\t', index_col='datetime')  # Считываем файл в DataFrame
            fileBars.index = pd.to_datetime(fileBars.index, format='%d.%m.%Y %H:%M')  # Переводим индекс в формат datetime
            print(f'- Первая запись файла: {fileBars.index[0]}')
            print(f'- Последняя запись файла: {fileBars.index[-1]}')
            print(f'- Кол-во записей в файле: {len(fileBars)}')

        newBars = apProvider.GetHistory(exchange, symbol, timeFrame, secondsFrom)['history']  # Получаем все бары
        pdBars = pd.DataFrame.from_dict(pd.json_normalize(newBars), orient='columns')  # Внутренние колонки даты/времени разворачиваем в отдельные колонки
        pdBars['datetime'] = pd.to_datetime(pdBars['time'], unit='s')  # Дата и время в UTC для дневных бар и выше
        if type(timeFrame) is not str:  # Для внутридневных баров
            pdBars['datetime'] = pdBars['datetime'].dt.tz_localize('UTC').dt.tz_convert(apProvider.tzMsk).dt.tz_localize(None)  # Переводим в рыночное время МСК
        pdBars.index = pdBars['datetime']  # Это будет индексом
        pdBars = pdBars[['open', 'high', 'low', 'close', 'volume']]  # Отбираем нужные колонки
        pdBars.index.name = 'datetime'  # Ставим название индекса даты/времени
        pdBars.volume = pd.to_numeric(pdBars.volume, downcast='integer')  # Объемы могут быть только целыми
        print(f'- Первая запись в Alor: {pdBars.index[0]}')
        print(f'- Последняя запись в Alor: {pdBars.index[-1]}')
        print(f'- Кол-во записей в Alor: {len(pdBars)}')

        if isFileExists:  # Если файл существует
            pdBars = pd.concat([fileBars, pdBars]).drop_duplicates(keep='last').sort_index()  # Объединяем файл с данными из QUIK, убираем дубликаты, сортируем заново
        pdBars.to_csv(fileName, sep='\t', date_format='%d.%m.%Y %H:%M')
        print(f'- В файл {fileName} сохранено записей: {len(pdBars)}')


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    startTime = time()  # Время начала запуска скрипта
    apProvider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету. Логин и Refresh Token берутся из файла Config.py
    # apProvider = AlorPy(Config.DemoUserName, Config.DemoRefreshToken, True)  # Подключаемся к демо счету

    # symbols = ('SBER', 'GMKN', 'GAZP', 'LKOH', 'TATN', 'YNDX', 'TCSG', 'ROSN', 'NVTK', 'MVID',
    #            'CHMF', 'POLY', 'OZON', 'ALRS', 'MAIL', 'MTSS', 'NLMK', 'MAGN', 'PLZL', 'MGNT',
    #            'MOEX', 'TRMK', 'RUAL', 'SNGS', 'AFKS', 'SBERP', 'SIBN', 'FIVE', 'SNGSP', 'AFLT',
    #            'IRAO', 'PHOR', 'TATNP', 'VTBR', 'QIWI', 'CBOM', 'FEES', 'BELU', 'TRNFP', 'FIXP',
    #            'SiH2', 'RIH2')  # TOP 40 акций ММВБ + Si + RI

    symbols = ('SBER',)
    secondsFrom = 0  # В первый раз нужно взять всю историю по этим тикерам. Скрипт будет выполняться около 15-и минут!
    # secondsFrom = int(datetime(2022, 4, 1, tzinfo=timezone.utc).timestamp())  # В дальнейшем можно обновляться с нужной даты. Это займет около 10-и минут из-за больших объемов истории
    SaveCandlesToFile(symbols=symbols, secondsFrom=secondsFrom)  # Получаем дневные бары (с начала)
    SaveCandlesToFile(symbols=symbols, timeFrame=300, secondsFrom=secondsFrom)  # Получаем 5-и минутные бары (последние 4 года)
    SaveCandlesToFile(symbols=symbols, timeFrame=3600, secondsFrom=secondsFrom)  # Получаем часовые бары (последние 4 года)

    print(f'Скрипт выполнен за {(time() - startTime):.2f} с')
