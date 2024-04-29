import logging  # Выводим лог на консоль и в файл
from datetime import datetime, timedelta  # Дата и время, временной интервал
from time import time
import os.path

import pandas as pd

from AlorPy import AlorPy  # Работа с Alor OpenAPI V2


logger = logging.getLogger('AlorPy.Bars')  # Будем вести лог. Определяем здесь, т.к. возможен внешний вызов ф-ии
datapath = os.path.join('..', '..', 'Data', 'Alor', '')  # Путь сохранения файла истории
delimiter = '\t'  # Разделитель значений в файле истории. По умолчанию табуляция
dt_format = '%d.%m.%Y %H:%M'  # Формат представления даты и времени в файле истории. По умолчанию русский формат


# noinspection PyShadowingNames
def load_candles_from_file(class_code='TQBR', security_code='SBER', tf='D1') -> pd.DataFrame:
    """Получение бар из файла

    :param str class_code: Код режима торгов
    :param str security_code: Код тикера
    :param str tf: Временной интервал https://ru.wikipedia.org/wiki/Таймфрейм
    """
    filename = f'{datapath}{class_code}.{security_code}_{tf}.txt'
    file_exists = os.path.isfile(filename)  # Существует ли файл
    if file_exists:  # Если файл существует
        logger.info(f'Получение файла {filename}')
        file_bars = pd.read_csv(filename, sep=delimiter, parse_dates=['datetime'], date_format=dt_format, index_col='datetime')
        logger.info(f'Первый бар    : {file_bars.index[0]:{dt_format}}')
        logger.info(f'Последний бар : {file_bars.index[-1]:{dt_format}}')
        logger.info(f'Кол-во бар    : {len(file_bars)}')
        return file_bars
    else:  # Если файл не существует
        logger.warning(f'Файл {filename} не найден')
        return pd.DataFrame()


# noinspection PyShadowingNames
def get_candles_from_provider(ap_provider=AlorPy(), class_code='TQBR', security_code='SBER', tf='D1', seconds_from=0) -> pd.DataFrame:
    """Получение бар из провайдера

    :param AlorPy ap_provider: Провайдер Alor
    :param str class_code: Код режима торгов
    :param str security_code: Код тикера
    :param str tf: Временной интервал https://ru.wikipedia.org/wiki/Таймфрейм
    :param int seconds_from: Дата и время открытия первого бара в кол-ве секунд, прошедших с 01.01.1970 00:00 UTC
    """
    time_frame, _ = ap_provider.timeframe_to_alor_timeframe(tf)  # Временной интервал Alor
    exchange = ap_provider.get_exchange(class_code, security_code)  # Биржа
    if not exchange:  # Если биржа не была найдена
        logger.error(f'Биржа для тикера {class_code}.{security_code} не найдена')
        return pd.DataFrame()  # то выходим, дальше не продолжаем
    logger.info(f'Получение истории {class_code}.{security_code} {tf} из Alor')
    history = ap_provider.get_history(exchange, security_code, time_frame, seconds_from)  # Запрос истории рынка
    if not history:  # Если бары не получены
        logger.error('Ошибка при получении истории: История не получена')
        return pd.DataFrame()  # то выходим, дальше не продолжаем
    if 'history' not in history:  # Если бар нет в словаре
        logger.error(f'Ошибка при получении истории: {history}')
        return pd.DataFrame()  # то выходим, дальше не продолжаем
    new_bars = history['history']  # Получаем все бары из Alor
    if len(new_bars) == 0:  # Если новых бар нет
        logger.info('Новых записей нет')
        return pd.DataFrame()  # то выходим, дальше не продолжаем
    pd_bars = pd.json_normalize(new_bars)  # Переводим список бар в pandas DataFrame
    pd_bars['datetime'] = pd.to_datetime(pd_bars['time'], unit='s')  # Дата и время в UTC для дневных бар и выше
    if type(time_frame) is not str:  # Для внутридневных бар (time_frame число)
        pd_bars['datetime'] = pd_bars['datetime'].dt.tz_localize('UTC').dt.tz_convert(ap_provider.tz_msk).dt.tz_localize(None)  # Переводим в рыночное время МСК
    pd_bars.index = pd_bars['datetime']  # В индекс ставим дату/время
    si = ap_provider.get_symbol(exchange, security_code)  # Получаем информацию о тикере
    pd_bars['volume'] *= si['lotsize']  # Объем в штуках
    pd_bars = pd_bars[['datetime', 'open', 'high', 'low', 'close', 'volume']]  # Отбираем нужные колонки. Дата и время нужна, чтобы не удалять одинаковые OHLCV на разное время
    pd_bars.volume = pd.to_numeric(pd_bars.volume, downcast='integer')  # Объемы могут быть только целыми
    logger.info(f'Первый бар    : {pd_bars.index[0]:{dt_format}}')
    logger.info(f'Последний бар : {pd_bars.index[-1]:{dt_format}}')
    logger.info(f'Кол-во бар    : {len(pd_bars)}')
    return pd_bars


# noinspection PyShadowingNames
def save_candles_to_file(ap_provider=AlorPy(), class_code='TQBR', security_codes=('SBER',), tf='D1',
                         skip_first_date=False, skip_last_date=False, four_price_doji=False):
    """Получение новых бар из провайдера, объединение с имеющимися барами в файле (если есть), сохранение баров в файл

    :param AlorPy ap_provider: Провайдер Alor
    :param str class_code: Код режима торгов
    :param tuple security_codes: Коды тикеров в виде кортежа
    :param str tf: Временной интервал https://ru.wikipedia.org/wiki/Таймфрейм
    :param bool skip_first_date: Убрать бары на первую полученную дату
    :param bool skip_last_date: Убрать бары на последнюю полученную дату
    :param bool four_price_doji: Оставить бары с дожи 4-х цен
    """
    _, intraday = ap_provider.timeframe_to_alor_timeframe(tf)  # Временной интервал Alor, внутридневной интервал
    for security_code in security_codes:  # Пробегаемся по всем тикерам
        file_bars = load_candles_from_file(class_code, security_code, tf)  # Получаем бары из файла
        if file_bars.empty:  # Если файла нет
            seconds_from = 0  # Берем отметку времени, когда никакой тикер еще не торговался
        else:  # Если получили бары из файла
            last_date: datetime = file_bars.index[-1]  # Дата и время последнего бара по МСК
            seconds_from = ap_provider.msk_datetime_to_utc_timestamp(last_date + timedelta(seconds=1)) if intraday else \
                ap_provider.msk_datetime_to_utc_timestamp(last_date + timedelta(days=1))  # Смещаем время на возможный следующий бар по UTC
        pd_bars = get_candles_from_provider(ap_provider, class_code, security_code, tf, seconds_from)  # Получаем бары из провайдера
        if pd_bars.empty:  # Если бары не получены
            logger.info('Новых бар нет')
            continue  # то переходим к следующему тикеру, дальше не продолжаем
        if file_bars.empty and skip_first_date:  # Если файла нет, и убираем бары на первую дату
            len_with_first_date = len(pd_bars)  # Кол-во бар до удаления на первую дату
            first_date = pd_bars.index[0].date()  # Первая дата
            pd_bars.drop(pd_bars[(pd_bars.index.date == first_date)].index, inplace=True)  # Удаляем их
            logger.warning(f'Удалено бар на первую дату {first_date:{dt_format}}: {len_with_first_date - len(pd_bars)}')
        if skip_last_date:  # Если убираем бары на последнюю дату
            len_with_last_date = len(pd_bars)  # Кол-во бар до удаления на последнюю дату
            last_date = pd_bars.index[-1].date()  # Последняя дата
            pd_bars.drop(pd_bars[(pd_bars.index.date == last_date)].index, inplace=True)  # Удаляем их
            logger.warning(f'Удалено бар на последнюю дату {last_date:{dt_format}}: {len_with_last_date - len(pd_bars)}')
        if not four_price_doji:  # Если удаляем дожи 4-х цен
            len_with_doji = len(pd_bars)  # Кол-во бар до удаления дожи
            pd_bars.drop(pd_bars[(pd_bars.high == pd_bars.low)].index, inplace=True)  # Удаляем их по условия High == Low
            logger.warning(f'Удалено дожи 4-х цен: {len_with_doji - len(pd_bars)}')
        if len(pd_bars) == 0:  # Если нечего объединять
            logger.info('Новых бар нет')
            continue  # то переходим к следующему тикеру, дальше не продолжаем
        if not file_bars.empty:  # Если файл существует
            pd_bars = pd.concat([file_bars, pd_bars]).drop_duplicates(keep='last').sort_index()  # Объединяем файл с данными из Alor, убираем дубликаты, сортируем заново
        pd_bars = pd_bars[['open', 'high', 'low', 'close', 'volume']]  # Отбираем нужные колонки. Дата и время будет экспортирована как индекс
        filename = f'{datapath}{class_code}.{security_code}_{tf}.txt'
        logger.info('Сохранение файла')
        pd_bars.to_csv(filename, sep=delimiter, date_format=dt_format)
        logger.info(f'Первый бар    : {pd_bars.index[0]:{dt_format}}')
        logger.info(f'Последний бар : {pd_bars.index[-1]:{dt_format}}')
        logger.info(f'Кол-во бар    : {len(pd_bars)}')
        logger.info(f'В файл {filename} сохранено записей: {len(pd_bars)}')


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    start_time = time()  # Время начала запуска скрипта
    ap_provider = AlorPy()  # Подключаемся ко всем торговым счетам

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
                        datefmt='%d.%m.%Y %H:%M:%S',  # Формат даты
                        level=logging.DEBUG,  # Уровень логируемых событий NOTSET/DEBUG/INFO/WARNING/ERROR/CRITICAL
                        handlers=[logging.FileHandler('Bars.log'), logging.StreamHandler()])  # Лог записываем в файл и выводим на консоль
    logging.Formatter.converter = lambda *args: datetime.now(tz=ap_provider.tz_msk).timetuple()  # В логе время указываем по МСК
    logging.getLogger('urllib3').setLevel(logging.CRITICAL + 1)  # Пропускаем события запросов

    class_code = 'TQBR'  # Акции ММВБ
    security_codes = ('SBER',)  # Для тестов
    # security_codes = ('SBER', 'VTBR', 'GAZP', 'NMTP', 'LKOH', 'BSPB', 'FESH', 'ALRS', 'YNDX', 'BELU',
    #                   'GMKN', 'MTLR', 'HYDR', 'MAGN', 'SNGSP', 'NVTK', 'ROSN', 'TATN', 'SBERP', 'CHMF',
    #                   'MGNT', 'RTKM', 'TRNFP', 'MTSS', 'FEES', 'SNGS', 'NLMK', 'PLZL', 'RNFT', 'MOEX',
    #                   'DVEC', 'TGKA', 'MTLRP', 'RUAL', 'TRMK', 'IRAO', 'SMLT', 'AFKS', 'AFLT', 'PIKK')  # TOP 40 акций ММВБ
    # class_code = 'SPBFUT'  # Фьючерсы (RFUD)
    # security_codes = ('SiM4', 'RIM4')  # Формат фьючерса: <Тикер><Месяц экспирации><Последняя цифра года> Месяц экспирации: 3-H, 6-M, 9-U, 12-Z
    # security_codes = ('USDRUBF', 'EURRUBF', 'CNYRUBF', 'GLDRUBF', 'IMOEXF')  # Вечные фьючерсы ММВБ

    skip_last_date = True  # Если получаем данные внутри сессии, то не берем бары за дату незавершенной сессии
    # skip_last_date = False  # Если получаем данные, когда рынок не работает, то берем все бары
    save_candles_to_file(ap_provider, class_code, security_codes, 'D1', skip_last_date=skip_last_date, four_price_doji=True)  # Дневные бары (с начала)
    # save_candles_to_file(ap_provider, class_code, security_codes, 'M60', skip_last_date=skip_last_date)  # Часовые бары (с 11.12.2017)
    # save_candles_to_file(ap_provider, class_code, security_codes, 'M15', skip_last_date=skip_last_date)  # 15-и минутные бары (с 11.12.2017)
    # save_candles_to_file(ap_provider, class_code, security_codes, 'M5', skip_last_date=skip_last_date)  # 5-и минутные бары (с 11.12.2017)
    # save_candles_to_file(ap_provider, class_code, security_codes, 'M1', skip_last_date=skip_last_date, four_price_doji=True)  # Минутные бары (с 11.12.2017)

    ap_provider.close_web_socket()  # Перед выходом закрываем соединение с WebSocket

    logger.info(f'Скрипт выполнен за {(time() - start_time):.2f} с')
