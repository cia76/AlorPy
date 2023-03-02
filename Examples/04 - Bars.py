from datetime import datetime
from time import time
import os.path
import pandas as pd

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config  # Файл конфигурации


def SaveCandlesToFile(exchange='MOEX', symbols=('SBER',), timeFrame='D', secondsFrom=0,
                      skipFirstDate=False, skipLastDate=False, fourPriceDoji=False):
    """Получение баров, объединение с имеющимися барами в файле (если есть), сохранение баров в файл

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param tuple symbols: Коды тикеров в виде кортежа
        :param str timeFrame: Длительность таймфрейма в секундах или код ("D" - дни, "W" - недели, "M" - месяцы, "Y" - годы)
        :param int secondsFrom: Дата и время UTC в секундах для первого запрашиваемого бара
        :param skipFirstDate: Убрать бары на первую полученную дату
        :param skipLastDate: Убрать бары на последнюю полученную дату
        :param fourPriceDoji: Оставить бары с дожи 4-х цен
        """
    for symbol in symbols:  # Пробегаемся по всем тикерам
        file_name = f'..\\..\\DataAlor\\{exchange}.{symbol}_{timeFrame}.txt'
        file_exists = os.path.isfile(file_name)  # Существует ли файл
        if not file_exists:  # Если файл не существует
            print(f'Файл {file_name} не найден и будет создан')
        else:  # Файл существует
            print(f'Получение файла {file_name}')
            file_bars = pd.read_csv(file_name, sep='\t', index_col='datetime')  # Считываем файл в DataFrame
            file_bars.index = pd.to_datetime(file_bars.index, format='%d.%m.%Y %H:%M')  # Переводим индекс в формат datetime
            print(f'- Первая запись файла: {file_bars.index[0]}')
            print(f'- Последняя запись файла: {file_bars.index[-1]}')
            print(f'- Кол-во записей в файле: {len(file_bars)}')
        new_bars = apProvider.GetHistory(exchange, symbol, timeFrame, secondsFrom)['history']  # Получаем все бары
        pd_bars = pd.DataFrame.from_dict(pd.json_normalize(new_bars), orient='columns')  # Внутренние колонки даты/времени разворачиваем в отдельные колонки
        pd_bars['datetime'] = pd.to_datetime(pd_bars['time'], unit='s')  # Дата и время в UTC для дневных бар и выше
        if type(timeFrame) is not str:  # Для внутридневных баров (timeFmame число)
            pd_bars['datetime'] = pd_bars['datetime'].dt.tz_localize('UTC').dt.tz_convert(apProvider.tzMsk).dt.tz_localize(None)  # Переводим в рыночное время МСК
        pd_bars.index = pd_bars['datetime']  # Это будет индексом
        pd_bars = pd_bars[['open', 'high', 'low', 'close', 'volume']]  # Отбираем нужные колонки
        pd_bars.index.name = 'datetime'  # Ставим название индекса даты/времени
        pd_bars.volume = pd.to_numeric(pd_bars.volume, downcast='integer')  # Объемы могут быть только целыми
        if skipFirstDate:  # Если убираем бары на первую дату
            len_with_first_date = len(pd_bars)  # Кол-во баров до удаления на первую дату
            first_date = pd_bars.index[0].date()  # Первая дата
            pd_bars.drop(pd_bars[(pd_bars.index.date == first_date)].index, inplace=True)  # Удаляем их
            print(f'- Удалено баров на первую дату {first_date}: {len_with_first_date - len(pd_bars)}')
        if skipLastDate:  # Если убираем бары на последнюю дату
            len_with_last_date = len(pd_bars)  # Кол-во баров до удаления на последнюю дату
            last_date = pd_bars.index[-1].date()  # Последняя дата
            pd_bars.drop(pd_bars[(pd_bars.index.date == last_date)].index, inplace=True)  # Удаляем их
            print(f'- Удалено баров на последнюю дату {last_date}: {len_with_last_date - len(pd_bars)}')
        if not fourPriceDoji:  # Если удаляем дожи 4-х цен
            len_with_doji = len(pd_bars)  # Кол-во баров до удаления дожи
            pd_bars.drop(pd_bars[(pd_bars.high == pd_bars.low)].index, inplace=True)  # Удаляем их по условия High == Low
            print('- Удалено дожи 4-х цен:', len_with_doji - len(pd_bars))
        print(f'- Первая запись в Alor: {pd_bars.index[0]}')
        print(f'- Последняя запись в Alor: {pd_bars.index[-1]}')
        print(f'- Кол-во записей в Alor: {len(pd_bars)}')
        if file_exists:  # Если файл существует
            pd_bars = pd.concat([file_bars, pd_bars]).drop_duplicates(keep='last').sort_index()  # Объединяем файл с данными из Alor, убираем дубликаты, сортируем заново
        pd_bars.to_csv(file_name, sep='\t', date_format='%d.%m.%Y %H:%M')
        print(f'- В файл {file_name} сохранено записей: {len(pd_bars)}')


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    startTime = time()  # Время начала запуска скрипта
    apProvider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету. Логин и Refresh Token берутся из файла Config.py

    # symbols = ('SBER', 'GAZP',)
    symbols = ('GAZP', 'LKOH', 'SBER', 'NVTK', 'YNDX', 'GMKN', 'ROSN', 'MTLR', 'MGNT', 'CHMF',
               'PHOR', 'VTBR', 'TCSG', 'PLZL', 'ALRS', 'MAGN', 'CBOM', 'SMLT', 'MVID', 'AFLT',
               'SNGS', 'SBERP', 'NLMK', 'RUAL', 'MTSS', 'TATN', 'MOEX', 'VKCO', 'MTLRP', 'AFKS',
               'SNGSP', 'PIKK', 'ISKJ', 'OZON', 'POLY', 'HYDR', 'RASP', 'IRAO', 'SIBN', 'FESH')  # TOP 40 акций ММВБ

    secondsFrom = 0  # В первый раз нужно взять всю историю по этим тикерам. Скрипт будет выполняться около 15-и минут!
    # secondsFrom = int(apProvider.tzMsk.localize(datetime(2023, 2, 1)).timestamp())  # В дальнейшем можно обновляться с нужной даты. Это займет около 10-и минут из-за больших объемов истории
    skipLastDate = True  # Если получаем данные внутри сессии, то не берем бары за дату незавершенной сессии
    # skipLastDate = False  # Если получаем данные, когда рынок не работает, то берем все бары
    SaveCandlesToFile(symbols=symbols, secondsFrom=secondsFrom, skipLastDate=skipLastDate)  # Получаем дневные бары (с начала)
    # SaveCandlesToFile(symbols=symbols, timeFrame=60, fourPriceDoji=True)  # Получаем минутные бары (с 11.12.2007)
    # SaveCandlesToFile(symbols=symbols, timeFrame=300, secondsFrom=secondsFrom, skipLastDate=skipLastDate)  # Получаем 5-и минутные бары (с 11.12.2007)
    # SaveCandlesToFile(symbols=symbols, timeFrame=3600, secondsFrom=secondsFrom, skipLastDate=skipLastDate)  # Получаем часовые бары (с 11.12.2007)

    print(f'Скрипт выполнен за {(time() - startTime):.2f} с')
