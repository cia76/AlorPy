import logging  # Выводим лог на консоль и в файл
from datetime import datetime, timedelta  # Дата и время, временной интервал
from time import time
import os.path

import pandas as pd

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2


# noinspection PyShadowingNames
def save_candles_to_file(ap_provider=AlorPy(), board='TQBR', symbols=('SBER',), time_frame='D',
                         datapath=os.path.join('..', '..', 'Data', 'Alor', ''), delimiter='\t', dt_format='%d.%m.%Y %H:%M',
                         skip_first_date=False, skip_last_date=False, four_price_doji=False):
    """Получение баров, объединение с имеющимися барами в файле (если есть), сохранение баров в файл

    :param AlorPy ap_provider: Провайдер Alor
    :param str board: Код режима торгов
    :param tuple symbols: Коды тикеров в виде кортежа
    :param int|str time_frame: Временной интервал в секундах (int) или код ("D" - дни, "W" - недели, "M" - месяцы, "Y" - годы)
    :param str datapath: Путь сохранения файла истории '..\\..\\Data\\Alor\\' - Windows, '../../Data/Alor/' - Linux
    :param str delimiter: Разделитель значений в файле истории. По умолчанию табуляция
    :param str dt_format: Формат представления даты и времени в файле истории. По умолчанию русский формат
    :param bool skip_first_date: Убрать бары на первую полученную дату
    :param bool skip_last_date: Убрать бары на последнюю полученную дату
    :param bool four_price_doji: Оставить бары с дожи 4-х цен
    """
    tf, intraday = ap_provider.alor_timeframe_to_timeframe(time_frame)  # Временной интервал для имени файла, внутридневной интервал
    for symbol in symbols:  # Пробегаемся по всем тикерам
        file_bars = None  # Дальше будем пытаться получить бары из файла
        file_name = f'{datapath}{board}.{symbol}_{tf}.txt'
        file_exists = os.path.isfile(file_name)  # Существует ли файл
        if file_exists:  # Если файл существует
            logger.info(f'Получение файла {file_name}')
            file_bars = pd.read_csv(file_name, sep=delimiter, parse_dates=['datetime'], date_format=dt_format, index_col='datetime')  # Считываем файл в DataFrame
            last_date: datetime = file_bars.index[-1]  # Дата и время последнего бара
            logger.info(f'Первый бар: {file_bars.index[0]}')
            logger.info(f'Последний бар: {last_date}')
            logger.info(f'Кол-во бар: {len(file_bars)}')
            seconds_from = ap_provider.msk_datetime_to_utc_timestamp(last_date + timedelta(seconds=1)) if intraday else\
                ap_provider.msk_datetime_to_utc_timestamp(last_date + timedelta(days=1))  # Смещаем время на возможный следующий бар по UTC
        else:  # Файл не существует
            logger.warning(f'Файл {file_name} не найден и будет создан')
            seconds_from = 0  # Берем отметку времени, когда никакой тикер еще не торговался
        exchange = ap_provider.get_exchange(board, symbol)  # Биржа
        if not exchange:  # Если биржа не была найдена
            logger.error(f'Биржа для тикера {board}.{symbol} не найдена')
            return  # то выходим, дальше не продолжаем
        logger.info(f'Получение истории {board}.{symbol} {tf} из Alor')
        history = ap_provider.get_history(exchange, symbol, time_frame, seconds_from)  # Запрос истории рынка
        if not history:  # Если бары не получены
            logger.error('Ошибка при получении истории: История не получена')
            return  # то выходим, дальше не продолжаем
        if 'history' not in history:  # Если бар нет в словаре
            logger.error(f'Ошибка при получении истории: {history}')
            return  # то выходим, дальше не продолжаем
        new_bars = history['history']  # Получаем все бары из Alor
        if len(new_bars) == 0:  # Если новых бар нет
            logger.info('Новых записей нет')
            continue  # то переходим к следующему тикеру, дальше не продолжаем
        pd_bars = pd.json_normalize(new_bars)  # Переводим список баров в pandas DataFrame
        pd_bars['datetime'] = pd.to_datetime(pd_bars['time'], unit='s')  # Дата и время в UTC для дневных бар и выше
        si = ap_provider.get_symbol_info(exchange, symbol)  # Получаем спецификацию тикера
        pd_bars['volume'] *= si['lotsize']  # Объемы из лотов переводим в штуки
        if type(time_frame) is not str:  # Для внутридневных баров (time_frame число)
            pd_bars['datetime'] = pd_bars['datetime'].dt.tz_localize('UTC').dt.tz_convert(ap_provider.tz_msk).dt.tz_localize(None)  # Переводим в рыночное время МСК
        pd_bars.index = pd_bars['datetime']  # Это будет индексом
        pd_bars = pd_bars[['datetime', 'open', 'high', 'low', 'close', 'volume']]  # Отбираем нужные колонки. Дата и время нужна, чтобы не удалять одинаковые OHLCV на разное время
        pd_bars.volume = pd.to_numeric(pd_bars.volume, downcast='integer')  # Объемы могут быть только целыми
        logger.info(f'Первый бар: {pd_bars.index[0]}')
        logger.info(f'Последний бар: {pd_bars.index[-1]}')
        logger.info(f'Кол-во бар: {len(pd_bars)}')
        if not file_exists and skip_first_date:  # Если файла нет, и убираем бары на первую дату
            len_with_first_date = len(pd_bars)  # Кол-во баров до удаления на первую дату
            first_date = pd_bars.index[0].date()  # Первая дата
            pd_bars.drop(pd_bars[(pd_bars.index.date == first_date)].index, inplace=True)  # Удаляем их
            logger.warning(f'Удалено бар на первую дату {first_date}: {len_with_first_date - len(pd_bars)}')
        if skip_last_date:  # Если убираем бары на последнюю дату
            len_with_last_date = len(pd_bars)  # Кол-во баров до удаления на последнюю дату
            last_date = pd_bars.index[-1].date()  # Последняя дата
            pd_bars.drop(pd_bars[(pd_bars.index.date == last_date)].index, inplace=True)  # Удаляем их
            logger.warning(f'Удалено бар на последнюю дату {last_date}: {len_with_last_date - len(pd_bars)}')
        if not four_price_doji:  # Если удаляем дожи 4-х цен
            len_with_doji = len(pd_bars)  # Кол-во баров до удаления дожи
            pd_bars.drop(pd_bars[(pd_bars.high == pd_bars.low)].index, inplace=True)  # Удаляем их по условия High == Low
            logger.warning(f'Удалено дожи 4-х цен: {len_with_doji - len(pd_bars)}')
        if len(pd_bars) == 0:  # Если нечего объединять
            logger.info('Новых записей нет')
            continue  # то переходим к следующему тикеру, дальше не продолжаем
        if file_exists:  # Если файл существует
            pd_bars = pd.concat([file_bars, pd_bars]).drop_duplicates(keep='last').sort_index()  # Объединяем файл с данными из Alor, убираем дубликаты, сортируем заново
        pd_bars = pd_bars[['open', 'high', 'low', 'close', 'volume']]  # Отбираем нужные колонки. Дата и время будет экспортирована как индекс
        logger.info(f'Сохранение файла ')
        pd_bars.to_csv(file_name, sep=delimiter, date_format=dt_format)
        logger.info(f'Первый бар: {pd_bars.index[0]}')
        logger.info(f'Последний бар: {pd_bars.index[-1]}')
        logger.info(f'Кол-во бар: {len(pd_bars)}')
        logger.info(f'В файл {file_name} сохранено записей: {len(pd_bars)}')


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    start_time = time()  # Время начала запуска скрипта
    logger = logging.getLogger('AlorPy.Bars')  # Будем вести лог
    ap_provider = AlorPy()  # Подключаемся ко всем торговым счетам

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                        datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                        level=logging.DEBUG,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                        handlers=[logging.FileHandler('Bars.log'), logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
    logging.Formatter.converter = lambda *args: datetime.now(tz=ap_provider.tz_msk).timetuple()  # В логе время указываем по МСК
    logging.getLogger('urllib3').setLevel(logging.CRITICAL + 1)  # Пропускаем события запросов

    board = 'TQBR'  # Акции ММВБ
    # symbols = ('SBER', 'VTBR', 'GAZP', 'NMTP', 'LKOH', 'BSPB', 'FESH', 'ALRS', 'YNDX', 'BELU',
    #            'GMKN', 'MTLR', 'HYDR', 'MAGN', 'SNGSP', 'NVTK', 'ROSN', 'TATN', 'SBERP', 'CHMF',
    #            'MGNT', 'RTKM', 'TRNFP', 'MTSS', 'FEES', 'SNGS', 'NLMK', 'PLZL', 'RNFT', 'MOEX',
    #            'DVEC', 'TGKA', 'MTLRP', 'RUAL', 'TRMK', 'IRAO', 'SMLT', 'AFKS', 'AFLT', 'PIKK')  # TOP 40 акций ММВБ
    symbols = ('SBER',)  # Для тестов
    # board = 'RFUD'  # Фьючерсы
    # symbols = ('SiH4', 'RIH4')  # Формат фьючерса: <Тикер><Месяц экспирации><Последняя цифра года> Месяц экспирации: 3-H, 6-M, 9-U, 12-Z

    skip_last_date = True  # Если получаем данные внутри сессии, то не берем бары за дату незавершенной сессии
    # skip_last_date = False  # Если получаем данные, когда рынок не работает, то берем все бары
    save_candles_to_file(ap_provider, board=board, symbols=symbols, skip_last_date=skip_last_date, four_price_doji=True)  # Дневные бары (с начала)
    # save_candles_to_file(ap_provider, board=board, symbols=symbols, time_frame=3600, skip_last_date=skip_last_date)  # Часовые бары (с 11.12.2017)
    # save_candles_to_file(ap_provider, board=board, symbols=symbols, time_frame=900, skip_last_date=skip_last_date)  # 15-и минутные бары (с 11.12.2017)
    # save_candles_to_file(ap_provider, board=board, symbols=symbols, time_frame=300, skip_last_date=skip_last_date)  # 5-и минутные бары (с 11.12.2017)
    # save_candles_to_file(ap_provider, board=board, symbols=symbols, time_frame=60, skip_last_date=skip_last_date, four_price_doji=True)  # Минутные бары (с 11.12.2007)

    ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket

    logger.info(f'Скрипт выполнен за {(time() - start_time):.2f} с')
