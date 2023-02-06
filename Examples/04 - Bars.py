from time import time
import os.path
import pandas as pd

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config  # Файл конфигурации


def SaveCandlesToFile(exchange='MOEX', symbols=('SBER',), timeFrame='D', secondsFrom=0,
                      skipFirstDate=False, skipLastDate=False, fourPriceDoji=False):
    """Получение баров, объединение с имеющимися барами в файле (если есть), сохранение баров в файл

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbols: Коды тикеров в виде кортежа
        :param str timeFrame: Длительность таймфрейма в секундах или код ("D" - дни, "W" - недели, "M" - месяцы, "Y" - годы)
        :param int secondsFrom: Дата и время UTC в секундах для первого запрашиваемого бара
        :param skipFirstDate: Убрать бары на первую полученную дату
        :param skipLastDate: Убрать бары на последнюю полученную дату
        :param fourPriceDoji: Оставить бары с дожи 4-х цен
        """
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
        if type(timeFrame) is not str:  # Для внутридневных баров (timeFmame число)
            pdBars['datetime'] = pdBars['datetime'].dt.tz_localize('UTC').dt.tz_convert(apProvider.tzMsk).dt.tz_localize(None)  # Переводим в рыночное время МСК
        pdBars.index = pdBars['datetime']  # Это будет индексом
        pdBars = pdBars[['open', 'high', 'low', 'close', 'volume']]  # Отбираем нужные колонки
        pdBars.index.name = 'datetime'  # Ставим название индекса даты/времени
        pdBars.volume = pd.to_numeric(pdBars.volume, downcast='integer')  # Объемы могут быть только целыми
        if skipFirstDate:  # Если убираем бары на первую дату
            lenWithFirstDate = len(pdBars)  # Кол-во баров до удаления на первую дату
            firstDate = pdBars.index[0].date()  # Первая дата
            pdBars.drop(pdBars[(pdBars.index.date == firstDate)].index, inplace=True)  # Удаляем их
            print(f'- Удалено баров на первую дату {firstDate}: {lenWithFirstDate - len(pdBars)}')
        if skipLastDate:  # Если убираем бары на последнюю дату
            lenWithLastDate = len(pdBars)  # Кол-во баров до удаления на последнюю дату
            lastDate = pdBars.index[-1].date()  # Последняя дата
            pdBars.drop(pdBars[(pdBars.index.date == lastDate)].index, inplace=True)  # Удаляем их
            print(f'- Удалено баров на последнюю дату {lastDate}: {lenWithLastDate - len(pdBars)}')
        if not fourPriceDoji:  # Если удаляем дожи 4-х цен
            lenWithDoji = len(pdBars)  # Кол-во баров до удаления дожи
            pdBars.drop(pdBars[(pdBars.high == pdBars.low)].index, inplace=True)  # Удаляем их по условия High == Low
            print('- Удалено дожи 4-х цен:', lenWithDoji - len(pdBars))
        print(f'- Первая запись в Alor: {pdBars.index[0]}')
        print(f'- Последняя запись в Alor: {pdBars.index[-1]}')
        print(f'- Кол-во записей в Alor: {len(pdBars)}')

        if isFileExists:  # Если файл существует
            pdBars = pd.concat([fileBars, pdBars]).drop_duplicates(keep='last').sort_index()  # Объединяем файл с данными из Alor, убираем дубликаты, сортируем заново
        pdBars.to_csv(fileName, sep='\t', date_format='%d.%m.%Y %H:%M')
        print(f'- В файл {fileName} сохранено записей: {len(pdBars)}')


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    startTime = time()  # Время начала запуска скрипта
    # apProvider = AlorPy(Config.DemoUserName, Config.DemoRefreshToken, True)  # Подключаемся к демо счету
    apProvider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету. Логин и Refresh Token берутся из файла Config.py

    # symbols = ('SBER', 'GAZP',)
    symbols = ('GAZP', 'LKOH', 'SBER', 'NVTK', 'YNDX', 'GMKN', 'ROSN', 'MTLR', 'MGNT', 'CHMF',
               'PHOR', 'VTBR', 'TCSG', 'PLZL', 'ALRS', 'MAGN', 'CBOM', 'SMLT', 'MVID', 'AFLT',
               'SNGS', 'SBERP', 'NLMK', 'RUAL', 'MTSS', 'TATN', 'MOEX', 'VKCO', 'MTLRP', 'AFKS',
               'SNGSP', 'PIKK', 'ISKJ', 'OZON', 'POLY', 'HYDR', 'RASP', 'IRAO', 'SIBN', 'FESH')  # TOP 40 акций ММВБ

    secondsFrom = 0  # В первый раз нужно взять всю историю по этим тикерам. Скрипт будет выполняться около 15-и минут!
    # secondsFrom = int(apProvider.tzMsk.localize(datetime(2022, 12, 20)).timestamp())  # В дальнейшем можно обновляться с нужной даты. Это займет около 10-и минут из-за больших объемов истории
    # skipLastDate = True  # Если получаем данные внутри сессии, то не берем бары за дату незавершенной сессии
    skipLastDate = False  # Если получаем данные, когда рынок не работает, то берем все бары
    SaveCandlesToFile(symbols=symbols, secondsFrom=secondsFrom, skipLastDate=skipLastDate)  # Получаем дневные бары (с начала)
    # SaveCandlesToFile(symbols=symbols, timeFrame=60, fourPriceDoji=True)  # Получаем минутные бары (с 11.12.2007)
    # SaveCandlesToFile(symbols=symbols, timeFrame=300, secondsFrom=secondsFrom, skipLastDate=skipLastDate)  # Получаем 5-и минутные бары (с 11.12.2007)
    # SaveCandlesToFile(symbols=symbols, timeFrame=3600, secondsFrom=secondsFrom, skipLastDate=skipLastDate)  # Получаем часовые бары (с 11.12.2007)

    print(f'Скрипт выполнен за {(time() - startTime):.2f} с')
