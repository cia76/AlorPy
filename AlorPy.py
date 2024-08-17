from typing import Union  # Объединение типов
from math import log10  # Кол-во десятичных знаков будем получать из шага цены через десятичный логарифм
from datetime import datetime
from time import time_ns  # Текущее время в наносекундах, прошедших с 01.01.1970 UTC
from uuid import uuid4  # Номера подписок должны быть уникальными во времени и пространстве
from json import loads, JSONDecodeError, dumps  # Сервер WebSockets работает с JSON сообщениями
from asyncio import get_event_loop, create_task, run, CancelledError  # Работа с асинхронными функциями
from threading import Thread  # Подписки сервера WebSockets будем получать в отдельном потоке
import logging  # Будем вести лог

from pytz import timezone, utc  # Работаем с временнОй зоной и UTC
import requests.adapters  # Настройки запросов/ответов
from requests import post, get, put, delete, Response  # Запросы/ответы от сервера запросов
from jwt import decode
from urllib3.exceptions import MaxRetryError  # Соединение с сервером не установлено за максимальное кол-во попыток подключения
from websockets import connect, ConnectionClosed  # Работа с сервером WebSockets

from AlorPy import Config  # Файл конфигурации


# noinspection PyShadowingBuiltins
class AlorPy:
    """Работа с Alor OpenAPI V2 https://alor.dev/docs из Python"""
    requests.adapters.DEFAULT_RETRIES = 10  # Настройка кол-ва попыток
    requests.adapters.DEFAULT_POOL_TIMEOUT = 10  # Настройка таймауту запроса в секундах
    tz_msk = timezone('Europe/Moscow')  # Время UTC будем приводить к московскому времени
    jwt_token_ttl = 60  # Время жизни токена JWT в секундах
    exchanges = ('MOEX', 'SPBX',)  # Биржи
    logger = logging.getLogger('AlorPy')  # Будем вести лог

    def __init__(self, refresh_token=Config.refresh_token, demo=False):
        """Инициализация

        :param str refresh_token: Токен
        :param bool demo: Режим демо торговли. По умолчанию установлен режим реальной торговли
        """
        self.oauth_server = f'https://oauth{"dev" if demo else ""}.alor.ru'  # Сервер аутентификации
        self.api_server = f'https://api{"dev" if demo else ""}.alor.ru'  # Сервер запросов
        self.cws_server = f'wss://api{"dev" if demo else ""}.alor.ru/cws'  # Сервис работы с заявками WebSocket
        self.cws_socket = None  # Подключение к серверу WebSocket
        self.ws_server = f'wss://api{"dev" if demo else ""}.alor.ru/ws'  # Сервис подписок и событий WebSocket
        self.ws_socket = None  # Подключение к серверу WebSocket
        self.ws_task = None  # Задача управления подписками WebSocket
        self.ws_ready = False  # WebSocket готов принимать запросы

        # События Alor OpenAPI V2
        self.on_change_order_book = self.default_handler  # Биржевой стакан
        self.on_new_bar = self.default_handler  # Новый бар
        self.on_new_quotes = self.default_handler  # Котировки
        self.on_all_trades = self.default_handler  # Все сделки
        self.on_position = self.default_handler  # Позиции по ценным бумагам и деньгам
        self.on_summary = self.default_handler  # Сводная информация по портфелю
        self.on_risk = self.default_handler  # Портфельные риски
        self.on_spectra_risk = self.default_handler  # Риски срочного рынка (FORTS)
        self.on_trade = self.default_handler  # Сделки
        self.on_stop_order = self.default_handler  # Стоп заявки
        self.on_stop_order_v2 = self.default_handler  # Стоп заявки v2
        self.on_order = self.default_handler  # Заявки
        self.on_symbol = self.default_handler  # Информация о финансовых инструментах

        # События WebSocket Thread/Task
        self.on_entering = self.default_handler  # Начало входа (Thread)
        self.on_enter = self.default_handler  # Вход (Thread)
        self.on_connect = self.default_handler  # Подключение к серверу (Task)
        self.on_resubscribe = self.default_handler  # Возобновление подписок (Task)
        self.on_ready = self.default_handler  # Готовность к работе (Task)
        self.on_disconnect = self.default_handler  # Отключение от сервера (Task)
        self.on_timeout = self.default_handler  # Таймаут/максимальное кол-во попыток подключения (Task)
        self.on_error = self.default_handler  # Ошибка (Task)
        self.on_cancel = self.default_handler  # Отмена (Task)
        self.on_exit = self.default_handler  # Выход (Thread)

        self.refresh_token = refresh_token  # Токен
        self.jwt_token = None  # Токен JWT
        self.jwt_token_decoded = dict()  # Информация по портфелям
        self.jwt_token_issued = 0  # UNIX время в секундах выдачи токена JWT
        self.accounts = list()  # Счета (портфели по договорам)
        self.get_jwt_token()  # Получаем токен JWT
        if self.jwt_token_decoded:
            all_agreements = self.jwt_token_decoded['agreements'].split(' ')  # Договоры
            all_portfolios = self.jwt_token_decoded['portfolios'].split(' ')  # Портфели
            i = j = 0  # Начальная позиция договоров и портфелей
            for agreement in all_agreements:  # Пробегаемся по всем договорам
                for portfolio in all_portfolios[j:j + 3]:  # К каждому договору привязаны 3 портфеля
                    exchanges = self.exchanges if portfolio.startswith('D') else (self.exchanges[0],)  # Для фондового рынка берем все биржи. Для остальных только MOEX
                    self.accounts.append(dict(account_id=i, agreement=agreement, portfolio=portfolio, exchanges=exchanges))  # Добавляем договор/портфель/биржи
                i += 1  # Смещаем на следующий договор
                j += 3  # Смещаем на начальную позицию портфелей для следующего договора
        self.subscriptions = {}  # Справочник подписок. Для возобновления всех подписок после перезагрузки сервера Алор
        self.symbols = {}  # Справочник тикеров

    def __enter__(self):
        """Вход в класс, например, с with"""
        return self

    # ClientInfo - Информация о клиенте

    def get_portfolio_summary(self, portfolio, exchange, format='Simple'):
        """Получение информации о портфеле

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/clients/{exchange}/{portfolio}/summary', params=params, headers=self.get_headers()))

    def get_positions(self, portfolio, exchange, without_currency=False, format='Simple'):
        """Получение информации о позициях

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param bool without_currency: Исключить из ответа все денежные инструменты, по умолчанию false
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'withoutCurrency': without_currency, 'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/positions', params=params, headers=self.get_headers()))

    def get_position(self, portfolio, exchange, symbol, format='Simple'):
        """Получение информации о позициях выбранного инструмента

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/positions/{symbol}', params=params, headers=self.get_headers()))

    def get_trades(self, portfolio, exchange, with_repo=None, format='Simple'):
        """Получение информации о сделках

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param bool with_repo: Флаг отображения заявок с РЕПО
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        if with_repo:
            params['withRepo'] = with_repo
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/trades', params=params, headers=self.get_headers()))

    def get_trade(self, portfolio, exchange, symbol, format='Simple'):
        """Получение информации о сделках по выбранному инструменту

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/{symbol}/trades', params=params, headers=self.get_headers()))

    def get_forts_risk(self, portfolio, exchange, format='Simple'):
        """Получение информации о рисках на срочном рынке

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/fortsrisk', params=params, headers=self.get_headers()))

    def get_risk(self, portfolio, exchange, format='Simple'):
        """Получение информации о рисках

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/risk', params=params, headers=self.get_headers()))

    def get_login_positions(self, login, without_currency=None, format='Simple'):
        """Получение информации о позициях по логину

        :param str login: Логин торгового аккаунта
        :param bool without_currency: Исключить из ответа все денежные инструменты
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        if without_currency:
            params['withoutCurrency'] = without_currency
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{login}/positions', params=params, headers=self.get_headers()))

    def get_trades_history_v2(self, portfolio, exchange, ticker=None, date_from=None, id_from=None, limit=None, descending=None, side=None, format='Simple'):
        """Получение истории сделок v2

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str ticker: Тикер/код инструмента. ISIN для облигаций
        :param str date_from: Начиная с какой даты отдавать историю сделок. Например, '2021-10-13'
        :param int id_from: Начальный номер сделки для фильтра результатов
        :param int limit: Количество возвращаемых записей. Не более 1000 сделок за один запрос
        :param bool descending: Флаг обратной сортировки выдачи
        :param str side: Направление сделки: 'buy' - Покупка, 'sell' - Продажа
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        if ticker:
            params['ticker'] = ticker
        if date_from:
            params['dateFrom'] = date_from
        if id_from:
            params['from'] = id_from
        if limit:
            params['limit'] = limit
        if descending:
            params['descending'] = descending
        if side:
            params['side'] = side
        return self.check_result(get(url=f'{self.api_server}/md/v2/Stats/{exchange}/{portfolio}/history/trades', params=params, headers=self.get_headers()))

    def get_trades_symbol_v2(self, portfolio, exchange, symbol, date_from=None, id_from=None, limit=None, descending=None, side=None, format='Simple'):
        """Получение истории сделок (один тикер) v2

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str date_from: Начиная с какой даты отдавать историю сделок. Например, '2021-10-13'
        :param int id_from: Начиная с какого ID (номера сделки) отдавать историю сделок
        :param int limit: Ограничение на количество выдаваемых результатов поиска
        :param bool descending: Флаг загрузки элементов с конца списка
        :param str side: Направление сделки: 'buy' - Покупка, 'sell' - Продажа
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        if date_from:
            params['dateFrom'] = date_from
        if id_from:
            params['from'] = id_from
        if limit:
            params['limit'] = limit
        if descending:
            params['descending'] = descending
        if side:
            params['side'] = side
        return self.check_result(get(url=f'{self.api_server}/md/v2/Stats/{exchange}/{portfolio}/history/trades/{symbol}', params=params, headers=self.get_headers()))

    # Instruments - Ценные бумаги / инструменты

    def get_securities(self, symbol, limit=None, offset=None, sector=None, cficode=None, exchange=None, instrument_group=None, include_non_base_boards=None, format='Simple'):
        """Получение информации о торговых инструментах

        :param str symbol: Маска тикера. Например SB выведет SBER, SBERP, SBRB ETF и пр.
        :param int limit: Ограничение на количество выдаваемых результатов поиска
        :param int offset: Смещение начала выборки (для пагинации)
        :param str sector: Рынок на бирже. FOND, FORTS, CURR
        :param str cficode: Код финансового инструмента по стандарту ISO 10962. EXXXXX
        :param str exchange: Биржа 'MOEX' или 'SPBX':
        :param str instrument_group: Код режима торгов
        :param str include_non_base_boards: Флаг выгрузки инструментов для всех режимов торгов, включая отличающиеся от установленного для инструмента значения параметра
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'query': symbol, 'format': format}
        if limit:
            params['limit'] = limit
        if offset:
            params['offset'] = offset
        if sector:
            params['sector'] = sector
        if cficode:
            params['cficode'] = cficode
        if exchange:
            params['exchange'] = exchange
        if instrument_group:
            params['instrumentGroup'] = instrument_group
        if include_non_base_boards:
            params['includeNonBaseBoards'] = include_non_base_boards
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities', params=params, headers=self.get_headers()))

    def get_securities_exchange(self, exchange, market=None, include_old=None, limit=None, include_non_base_boards=None, offset=None, format='Simple'):
        """Получение информации о торговых инструментах на выбранной бирже

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str market: Рынок на бирже. FOND, FORTS, CURR
        :param bool include_old: Флаг загрузки устаревших инструментов
        :param int limit: Ограничение на количество выдаваемых результатов поиска
        :param str include_non_base_boards: Флаг выгрузки инструментов для всех режимов торгов, включая отличающиеся от установленного для инструмента значения параметра
        :param int offset: Смещение начала выборки (для пагинации)
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        if market:
            params['market'] = market
        if include_old:
            params['includeOld'] = include_old
        if limit:
            params['limit'] = limit
        if include_non_base_boards:
            params['includeNonBaseBoards'] = include_non_base_boards
        if offset:
            params['offset'] = offset
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}', params=params, headers=self.get_headers()))

    def get_symbol(self, exchange, symbol, instrument_group=None, format='Simple'):
        """Получение информации о выбранном финансовом инструменте

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str instrument_group: Код режима торгов
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        if instrument_group:
            params['instrumentGroup'] = instrument_group
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}/{symbol}', params=params, headers=self.get_headers()))

    def get_available_boards(self, exchange, symbol):
        """Получение списка бордов для выбранного финансового инструмента

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}/{symbol}/availableBoards', headers=self.get_headers()))

    def get_all_trades(self, exchange, symbol, instrument_group=None, seconds_from=None, seconds_to=None, id_from=None, id_to=None,
                       qty_from=None, qty_to=None, price_from=None, price_to=None, side=None, offset=None, take=None, descending=None, include_virtual_trades=None, format='Simple'):
        """Получение информации о всех сделках по ценным бумагам за сегодня

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str instrument_group: Код режима торгов
        :param int seconds_from: Дата и время UTC в секундах для первой запрашиваемой сделки
        :param int seconds_to: Дата и время UTC в секундах для первой запрашиваемой сделки
        :param int id_from: Начальный номер сделки для фильтра результатов
        :param int id_to: Конечный номер сделки для фильтра результатов
        :param int qty_from: Нижняя граница объёма сделки в лотах
        :param int qty_to: Верхняя граница объёма сделки в лотах
        :param float price_from: Нижняя граница цены, по которой была совершена сделка
        :param float price_to: Верхняя граница цены, по которой была совершена сделка
        :param str side: Направление сделки: 'buy' - Покупка, 'sell' - Продажа
        :param int offset: Смещение начала выборки (для пагинации)
        :param int take: Количество загружаемых элементов
        :param bool descending: Флаг загрузки элементов с конца списка
        :param bool include_virtual_trades: Флаг загрузки виртуальных (индикативных) сделок, полученных из заявок на питерской бирже
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        if instrument_group:
            params['instrumentGroup'] = instrument_group
        if seconds_from:
            params['from'] = seconds_from
        if seconds_to:
            params['to'] = seconds_to
        if id_from:
            params['fromId'] = id_from
        if id_to:
            params['toId'] = id_to
        if qty_from:
            params['qtyFrom'] = qty_from
        if qty_to:
            params['qtyTo'] = qty_to
        if price_from:
            params['priceFrom'] = price_from
        if price_to:
            params['priceTo'] = price_to
        if side:
            params['side'] = side
        if offset:
            params['offset'] = offset
        if take:
            params['take'] = take
        if descending:
            params['descending'] = descending
        if include_virtual_trades:
            params['includeVirtualTrades'] = include_virtual_trades
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}/{symbol}/alltrades', params=params, headers=self.get_headers()))

    def get_all_trades_history(self, exchange, symbol, instrument_group=None, seconds_from=None, seconds_to=None, limit=50000, offset=None, format='Simple'):
        """Получение исторической информации о всех сделках по ценным бумагам

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str instrument_group: Код режима торгов
        :param int seconds_from: Начало отрезка времени UTC в секундах для фильтра результатов
        :param int seconds_to: Начало отрезка времени UTC в секундах для фильтра результатов
        :param int limit: Ограничение на количество выдаваемых результатов поиска (1-50000)
        :param int offset: Смещение начала выборки (для постраничного вывода)
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'limit': limit, 'format': format}
        if instrument_group:
            params['instrumentGroup'] = instrument_group
        if seconds_from:
            params['from'] = seconds_from
        if seconds_to:
            params['to'] = seconds_to
        if offset:
            params['offset'] = offset
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}/{symbol}/alltrades/history', params=params, headers=self.get_headers()))

    def get_actual_futures_quote(self, exchange, symbol, format='Simple'):
        """Получение котировки по ближайшему фьючерсу (код)

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}/{symbol}/actualFuturesQuote', params=params, headers=self.get_headers()))

    def get_quotes(self, symbols, format='Simple'):
        """Получение информации о котировках для выбранных инструментов

        :param str symbols: Принимает несколько пар биржа-тикер. Пары отделены запятыми. Биржа и тикер разделены двоеточием.
        Пример: MOEX:SBER,MOEX:GAZP,SPBX:AAPL
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{symbols}/quotes', params=params, headers=self.get_headers()))

    def get_currency_pairs(self, format='Simple'):
        """Получение информации о валютных парах

        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/currencyPairs', params=params, headers=self.get_headers()))

    def get_order_book(self, exchange, symbol, depth=20, format='Simple'):
        """Получение информации о биржевом стакане

        :param exchange: Биржа 'MOEX' или 'SPBX'
        :param symbol: Тикер
        :param depth: Глубина стакана. Стандартное и максимальное значение - 20 (20х20)
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'depth': depth, 'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/orderbooks/{exchange}/{symbol}', params=params, headers=self.get_headers()))

    def get_risk_rates(self, exchange, ticker=None, risk_category_id=None, search=None, limit=None, offset=None):
        """Запрос ставок риска

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str ticker: Тикер, код инструмента, ISIN для облигаций
        :param int risk_category_id: Id вашей (или той которая интересует) категории риска. Можно получить из запроса информации по клиенту или через кабинет клиента
        :param str search: Часть Тикера, кода инструмента, ISIN для облигаций. Вернет все совпадения, начинающиеся с
        :param int limit: Ограничение на количество выдаваемых результатов поиска
        :param int offset: Смещение начала выборки (для пагинации)
        """
        params = {'exchange': exchange}
        if ticker:
            params['ticker'] = ticker
        if risk_category_id:
            params['riskCategoryId'] = risk_category_id
        if search:
            params['search'] = search
        if limit:
            params['limit'] = limit
        if offset:
            params['offset'] = offset
        return self.check_result(get(url=f'{self.api_server}/md/v2/risk/rates', params=params, headers=self.get_headers()))

    def get_history(self, exchange, symbol, tf, seconds_from=1, seconds_to=32536799999, untraded=False, format='Simple'):
        """Запрос истории рынка для выбранных биржи и финансового инструмента

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param int|str tf: Длительность временнОго интервала в секундах или код ("D" - дни, "W" - недели, "M" - месяцы, "Y" - годы)
        :param int seconds_from: Дата и время UTC в секундах для первого запрашиваемого бара
        :param int seconds_to: Дата и время UTC в секундах для последнего запрашиваемого бара
        :param bool untraded: Флаг для поиска данных по устаревшим или экспирированным инструментам. При использовании требуется точное совпадение тикера
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        # Если на from подаем точное время начала бара, то этот бар из Алор не передается. Возможно, проблема в том, что сервис Алора смотрит все даты >, а >= from
        # Временное решение, вычитать 1 секунду
        params = {'exchange': exchange, 'symbol': symbol, 'tf': tf, 'from': max(0, seconds_from - 1), 'to': seconds_to, 'untraded': untraded, 'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/history', params=params, headers=self.get_headers()))

    # Other - Другое

    def get_time(self):
        """Запрос текущего UTC времени в секундах на сервере
        Если этот запрос выполнен без авторизации, то будет возвращено время, которое было 15 минут назад
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/time', headers=self.get_headers()))

    # Orders Работа с заявками

    def get_orders(self, portfolio, exchange, format='Simple'):
        """Получение информации о всех заявках

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/clients/{exchange}/{portfolio}/orders', params=params, headers=self.get_headers()))

    def get_order(self, portfolio, exchange, order_id, format='Simple'):
        """Получение информации о выбранной заявке

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int order_id: Номер заявки на бирже
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/clients/{exchange}/{portfolio}/orders/{order_id}', params=params, headers=self.get_headers()))

    def create_market_order(self, portfolio, exchange, symbol, side, quantity, comment='', time_in_force='GoodTillCancelled'):
        """Создание рыночной заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param str comment: Пользовательский комментарий к заявке
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = f'{portfolio};{self.get_request_id()}'  # Портфель с уникальным идентификатором запроса
        j = {'side': side, 'type': 'market', 'quantity': abs(quantity), 'instrument': {'symbol': symbol, 'exchange': exchange}, 'user': {'portfolio': portfolio}, 'comment': comment, 'timeInForce': time_in_force}
        return self.check_result(post(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/market', headers=headers, json=j))

    def create_limit_order(self, portfolio, exchange, symbol, side, quantity, limit_price, comment='', time_in_force='GoodTillCancelled', iceberg_fixed=None, iceberg_variance=None):
        """Создание лимитной заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float limit_price: Лимитная цена
        :param str comment: Пользовательский комментарий к заявке
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = f'{portfolio};{self.get_request_id()}'  # Портфель с уникальным идентификатором запроса
        j = {'side': side, 'type': 'limit', 'quantity': abs(quantity), 'price': limit_price, 'instrument': {'symbol': symbol, 'exchange': exchange}, 'user': {'portfolio': portfolio}, 'comment': comment,  'timeInForce': time_in_force}
        if iceberg_fixed:
            j['icebergFixed'] = iceberg_fixed
        if iceberg_variance:
            j['icebergVariance'] = iceberg_variance
        return self.check_result(post(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/limit', headers=headers, json=j))

    def edit_market_order(self, account, portfolio, exchange, order_id, symbol, side, quantity, comment='', time_in_force='GoodTillCancelled'):
        """Изменение рыночной заявки

        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int order_id: Номер заявки
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param str comment: Пользовательский комментарий к заявке
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = f'{portfolio};{order_id};{quantity}'  # Портфель с уникальным идентификатором запроса и кол-вом в лотах
        j = {'side': side, 'type': 'market', 'id': order_id, 'quantity': abs(quantity), 'instrument': {'symbol': symbol, 'exchange': exchange}, 'user': {'account': account, 'portfolio': portfolio}, 'comment': comment, 'timeInForce': time_in_force}
        return self.check_result(put(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/market/{order_id}', headers=headers, json=j))

    def edit_limit_order(self, portfolio, exchange, order_id, symbol, side, quantity, limit_price, comment='', time_in_force='GoodTillCancelled', iceberg_fixed=None, iceberg_variance=None):
        """Изменение лимитной заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int order_id: Номер заявки
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float limit_price: Лимитная цена
        :param str comment: Пользовательский комментарий к заявке
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = f'{portfolio};{order_id};{quantity}'  # Портфель с уникальным идентификатором запроса и кол-вом в лотах
        j = {'side': side, 'type': 'limit', 'quantity': abs(quantity), 'price': limit_price, 'instrument': {'symbol': symbol, 'exchange': exchange}, 'user': {'portfolio': portfolio}, 'comment': comment, 'timeInForce': time_in_force}
        if iceberg_fixed:
            j['icebergFixed'] = iceberg_fixed
        if iceberg_variance:
            j['icebergVariance'] = iceberg_variance
        return self.check_result(put(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/limit/{order_id}', headers=headers, json=j))

    def estimate_order(self, portfolio, exchange, symbol, price, quantity, board, include_limit_orders=False):
        """Провести оценку одной заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param float price: Цена покупки
        :param int quantity: Кол-во в лотах
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param bool include_limit_orders: Учитывать ли лимитные заявки при расчете
        """
        j = {'portfolio': portfolio, 'ticker': symbol, 'exchange': exchange, 'price': price, 'lotQuantity': quantity, 'board': board, 'includeLimitOrders': include_limit_orders}
        return self.check_result(post(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/estimate', json=j))

    def estimate_orders(self, orders):
        """Провести оценку нескольких заявок

        :param dict orders: Список заявок. Оформлять каждую заявку как в EstimateOrder:
        {'portfolio': portfolio, 'ticker': symbol, 'exchange': exchange, 'price': price, 'lotQuantity': quantity, 'board': board, 'includeLimitOrders': include_limit_orders}
        """
        return self.check_result(post(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/estimate/all', json=orders))

    def delete_order(self, portfolio, exchange, order_id, stop=False, format='Simple'):
        """Снятие заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int order_id: Номер заявки
        :param bool stop: Является ли стоп заявкой
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        params = {'portfolio': portfolio, 'exchange': exchange, 'stop': stop, 'jsonResponse': True, 'format': format}
        return self.check_result(delete(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/{order_id}', params=params, headers=headers))

    # Subscriptions - Подписки и события (WebSocket)

    def order_book_get_and_subscribe(self, exchange, symbol, depth=20, frequency=0, format='Simple') -> str:
        """Подписка на информацию о биржевом стакане для выбранных биржи и финансового инструмента

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param int depth: Глубина стакана. Стандартное и максимальное значение - 20 (20х20)
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'OrderBookGetAndSubscribe', 'exchange': exchange, 'code': symbol, 'depth': depth, 'frequency': frequency, 'format': format}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def bars_get_and_subscribe(self, exchange, symbol, tf, seconds_from, skip_history=False, frequency=0, format='Simple') -> str:
        """Подписка на историю цен (свечи) для выбранных биржи и финансового инструмента

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param tf: Длительность временнОго интервала в секундах или код ("D" - дни, "W" - недели, "M" - месяцы, "Y" - годы)
        :param int seconds_from: Дата и время UTC в секундах для первого запрашиваемого бара
        :param bool skip_history: Флаг отсеивания исторических данных: True — отображать только новые данные, False — отображать в том числе данные из истории
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'BarsGetAndSubscribe', 'exchange': exchange, 'code': symbol, 'tf': tf, 'from': int(seconds_from), 'delayed': False, 'skipHistory': skip_history, 'frequency': frequency, 'format': format}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def quotes_subscribe(self, exchange, symbol, frequency=0, format='Simple') -> str:
        """Подписка на информацию о котировках для выбранных инструментов и бирж

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'QuotesSubscribe', 'exchange': exchange, 'code': symbol, 'frequency': frequency, 'format': format}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def all_trades_subscribe(self, exchange, symbol, depth=0, include_virtual_trades=False, frequency=0, format='Simple') -> str:
        """Подписка на информацию о всех сделках

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param int depth: Если указать, то перед актуальными данными придут данные о последних N сделках. Максимум 5000
        :param bool include_virtual_trades: Указывает, нужно ли отправлять виртуальные (индикативные) сделки
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'AllTradesGetAndSubscribe', 'code': symbol, 'exchange': exchange, 'depth': depth, 'includeVirtualTrades': include_virtual_trades, 'frequency': frequency, 'format': format}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def positions_get_and_subscribe_v2(self, portfolio, exchange, skip_history=False, frequency=0, format='Simple') -> str:
        """Подписка на информацию о текущих позициях по ценным бумагам и деньгам

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param bool skip_history: Флаг отсеивания исторических данных: True — отображать только новые данные, False — отображать в том числе данные из истории
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'PositionsGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'skipHistory': skip_history, 'frequency': frequency, 'format': format}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def summaries_get_and_subscribe_v2(self, portfolio, exchange, skip_history=False, frequency=0, format='Simple') -> str:
        """Подписка на сводную информацию по портфелю

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param bool skip_history: Флаг отсеивания исторических данных: True — отображать только новые данные, False — отображать в том числе данные из истории
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'SummariesGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'skipHistory': skip_history, 'frequency': frequency, 'format': format}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def risks_get_and_subscribe(self, portfolio, exchange, skip_history=False, frequency=0, format='Simple') -> str:
        """Подписка на сводную информацию по портфельным рискам

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param bool skip_history: Флаг отсеивания исторических данных: True — отображать только новые данные, False — отображать в том числе данные из истории
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'RisksGetAndSubscribe', 'exchange': exchange, 'portfolio': portfolio, 'skipHistory': skip_history, 'frequency': frequency, 'format': format}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def spectra_risks_get_and_subscribe(self, portfolio, exchange, skip_history=False, frequency=0, format='Simple') -> str:
        """Подписка на информацию по рискам срочного рынка (FORTS)

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param bool skip_history: Флаг отсеивания исторических данных: True — отображать только новые данные, False — отображать в том числе данные из истории
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'SpectraRisksGetAndSubscribe', 'exchange': exchange, 'portfolio': portfolio, 'skipHistory': skip_history, 'frequency': frequency, 'format': format}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def trades_get_and_subscribe_v2(self, portfolio, exchange, skip_history=False, frequency=0, format='Simple') -> str:
        """Подписка на информацию о сделках

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param bool skip_history: Флаг отсеивания исторических данных: True — отображать только новые данные, False — отображать в том числе данные из истории
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'TradesGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'skipHistory': skip_history, 'frequency': frequency, 'format': format}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def orders_get_and_subscribe_v2(self, portfolio, exchange, order_statuses=None, skip_history=False, frequency=0, format='Simple') -> str:
        """Подписка на информацию о текущих заявках на рынке для выбранных биржи и финансового инструмента

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param list[str] order_statuses: Опциональный фильтр по статусам заявок. Влияет только на фильтрацию первичных исторических данных при подписке
        Статус исполнения. Пример: order_statuses=['filled', 'canceled']
            'working' - На исполнении
            'filled' - Исполнена
            'canceled' - Отменена
            'rejected' - Отклонена
        :param bool skip_history: Флаг отсеивания исторических данных: True — отображать только новые данные, False — отображать в том числе данные из истории
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'OrdersGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'skipHistory': skip_history, 'frequency': frequency, 'format': format}  # Запрос на подписку
        if order_statuses:
            request['orderStatuses'] = order_statuses
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def instruments_get_and_subscribe_v2(self, exchange, symbol, frequency=0, format='Simple') -> str:
        """Подписка на изменение информации о финансовых инструментах на выбранной бирже

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'InstrumentsGetAndSubscribeV2', 'code': symbol, 'exchange': exchange, 'frequency': frequency, 'format': format}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def unsubscribe(self, guid) -> str:
        """Отмена существующей подписки

        :param str guid: Уникальный идентификатор подписки
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'unsubscribe', 'token': str(self.get_jwt_token()), 'guid': guid}  # Запрос на отмену подписки
        get_event_loop().run_until_complete(self.ws_socket.send(dumps(request)))  # Отправляем запрос. Дожидаемся его выполнения
        del self.subscriptions[guid]  # Удаляем подписку из справочника
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def stop_orders_get_and_subscribe_v2(self, portfolio, exchange, order_statuses=None, skip_history=False, frequency=0, format='Simple') -> str:
        """Подписка на информацию о текущих стоп заявках на рынке для выбранных биржи и финансового инструмента

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param list[str] order_statuses: Опциональный фильтр по статусам заявок. Влияет только на фильтрацию первичных исторических данных при подписке
        Статус исполнения. Пример: order_statuses=['filled', 'canceled']
            'working' - На исполнении
            'filled' - Исполнена
            'canceled' - Отменена
            'rejected' - Отклонена
        :param bool skip_history: Флаг отсеивания исторических данных: True — отображать только новые данные, False — отображать в том числе данные из истории
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'StopOrdersGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'skipHistory': skip_history, 'frequency': frequency, 'format': format}  # Запрос на подписку
        if order_statuses:
            request['orderStatuses'] = order_statuses
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    # StopOrdersV2 - Стоп-заявки v2

    def get_stop_orders(self, portfolio, exchange, format='Simple'):
        """Получение информации о стоп-заявках

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/clients/{exchange}/{portfolio}/stoporders', params=params, headers=self.get_headers()))

    def get_stop_order(self, portfolio, exchange, order_id, format='Simple'):
        """Получение информации о выбранной стоп-заявке

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int order_id: Номер заявки на бирже
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/clients/{exchange}/{portfolio}/stoporders/{order_id}', params=params, headers=self.get_headers()))

    def create_stop_order(self, portfolio, exchange, symbol, class_code, side, quantity, stop_price, condition='Less', seconds_order_end=0, activate=True):
        """Создание стоп-заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str class_code: Режим торгов
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param str condition: Условие срабатывания 'More', 'Less', 'MoreOrEqual', 'LessOrEqual'
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        :param bool activate: Флаг активной заявки
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = f'{portfolio};{self.get_request_id()}'  # Портфель с уникальным идентификатором запроса
        j = {'side': side, 'condition': condition, 'triggerPrice': stop_price, 'stopEndUnixTime': seconds_order_end, 'quantity': abs(quantity),
             'instrument': {'symbol': symbol, 'exchange': exchange, 'instrumentGroup': class_code},
             'user': {'portfolio': portfolio, 'exchange': exchange}, 'activate': activate}
        return self.check_result(
            post(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/stop', headers=headers, json=j))

    def create_stop_limit_order(self, portfolio, exchange, symbol, class_code, side, quantity, stop_price, limit_price, condition='Less', seconds_order_end=0,
                                time_in_force='GoodTillCancelled', iceberg_fixed=None, iceberg_variance=None, activate=True):
        """Создание стоп-лимитной заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str class_code: Класс инструмента
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param float limit_price: Лимитная цена
        :param str condition: Условие срабатывания 'More', 'Less', 'MoreOrEqual', 'LessOrEqual'
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :param bool activate: Флаг активной заявки
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = f'{portfolio};{self.get_request_id()}'  # Портфель с уникальным идентификатором запроса
        j = {'side': side, 'condition': condition, 'triggerPrice': stop_price, 'stopEndUnixTime': seconds_order_end, 'price': limit_price, 'quantity': abs(quantity),
             'instrument': {'symbol': symbol, 'exchange': exchange, 'instrumentGroup': class_code}, 'user': {'portfolio': portfolio, 'exchange': exchange},
             'timeInForce': time_in_force, 'activate': activate}
        if iceberg_fixed:
            j['icebergFixed'] = iceberg_fixed
        if iceberg_variance:
            j['icebergVariance'] = iceberg_variance
        return self.check_result(post(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/stopLimit', headers=headers, json=j))

    def edit_stop_order_v2(self, portfolio, exchange, order_id, symbol, class_code, side, quantity, stop_price, condition='Less', seconds_order_end=0, activate=True):
        """Изменение стоп-заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int order_id: Номер заявки
        :param str symbol: Тикер
        :param str class_code: Класс инструмента
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param str condition: Условие срабатывания 'More', 'Less', 'MoreOrEqual', 'LessOrEqual'
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        :param bool activate: Флаг активной заявки
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = f'{portfolio};{self.get_request_id()}'  # Портфель с уникальным идентификатором запроса
        j = {'side': side, 'condition': condition, 'triggerPrice': stop_price, 'stopEndUnixTime': seconds_order_end, 'quantity': abs(quantity),
             'instrument': {'symbol': symbol, 'exchange': exchange, 'instrumentGroup': class_code}, 'user': {'portfolio': portfolio, 'exchange': exchange}, 'activate': activate}
        return self.check_result(put(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/stop/{order_id}', headers=headers, json=j))

    def edit_stop_limit_order_v2(self, portfolio, exchange, order_id, symbol, class_code, side, quantity, stop_price, limit_price, condition='Less', seconds_order_end=0,
                                 time_in_force='GoodTillCancelled', iceberg_fixed=None, iceberg_variance=None, activate=True):
        """Изменение стоп-лимитной заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int order_id: Номер заявки
        :param str symbol: Тикер
        :param str class_code: Класс инструмента
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param float limit_price: Лимитная цена
        :param str condition: Условие срабатывания 'More', 'Less', 'MoreOrEqual', 'LessOrEqual'
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :param bool activate: Флаг активной заявки
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = f'{portfolio};{self.get_request_id()}'  # Портфель с уникальным идентификатором запроса
        j = {'side': side, 'condition': condition, 'triggerPrice': stop_price, 'stopEndUnixTime': seconds_order_end, 'price': limit_price, 'quantity': abs(quantity),
             'instrument': {'symbol': symbol, 'exchange': exchange, 'instrumentGroup': class_code}, 'user': {'portfolio': portfolio, 'exchange': exchange},
             'timeInForce': time_in_force, 'activate': activate}
        if iceberg_fixed:
            j['icebergFixed'] = iceberg_fixed
        if iceberg_variance:
            j['icebergVariance'] = iceberg_variance
        return self.check_result(put(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/stopLimit/{order_id}', headers=headers, json=j))

    # OrdersWebSocket - Работа с заявками (WebSocket)

    def authorize_websocket(self):
        """Авторизация"""
        return self.send_websocket({'opcode': 'authorize', 'token': self.get_jwt_token()})

    def create_market_order_websocket(self, portfolio, exchange, board, symbol, side, quantity, comment='', time_in_force='GoodTillCancelled', check_duplicates=True):
        """Создание рыночной заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param str comment: Пользовательский комментарий к заявке
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        """
        request = {'opcode': 'create:market', 'side': side, 'quantity': abs(quantity), 'instrument': {'exchange': exchange, 'symbol': symbol},
                   'board': board, 'user': {'portfolio': portfolio}, 'comment': comment, 'timeInForce': time_in_force, 'checkDuplicates': check_duplicates}
        return self.send_websocket(request)

    def create_limit_order_websocket(self, portfolio, exchange, board, symbol, side, quantity, limit_price, comment='', time_in_force='GoodTillCancelled', iceberg_fixed=None, iceberg_variance=None, check_duplicates=True):
        """Создание лимитной заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float limit_price: Лимитная цена
        :param str comment: Пользовательский комментарий к заявке
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        """
        request = {'opcode': 'create:limit', 'side': side, 'quantity': abs(quantity), 'price': limit_price, 'instrument': {'exchange': exchange, 'symbol': symbol},
                   'board': board, 'user': {'portfolio': portfolio}, 'comment': comment, 'timeInForce': time_in_force, 'checkDuplicates': check_duplicates}
        if iceberg_fixed:
            request['icebergFixed'] = iceberg_fixed
        if iceberg_variance:
            request['icebergVariance'] = iceberg_variance
        return self.send_websocket(request)

    def create_stop_order_websocket(self, portfolio, exchange, symbol, board, side, quantity, stop_price, comment='', condition='Less', seconds_order_end=0, check_duplicates=True, activate=True):
        """Создание стоп-заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param str comment: Пользовательский комментарий к заявке
        :param str condition: Условие срабатывания 'More', 'Less', 'MoreOrEqual', 'LessOrEqual'
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :param bool activate: Флаг активной заявки
        """
        request = {'opcode': 'create:stop', 'side': side, 'quantity': abs(quantity), 'condition': condition, 'triggerPrice': stop_price, 'stopEndUnixTime': seconds_order_end,
                   'instrument': {'symbol': symbol, 'exchange': exchange}, 'comment': comment, 'board': board, 'user': {'portfolio': portfolio, 'exchange': exchange},
                   'checkDuplicates': check_duplicates, 'activate': activate}
        return self.send_websocket(request)

    def create_stop_limit_order_websocket(self, portfolio, exchange, symbol, board, side, quantity, stop_price, limit_price, comment='', condition='Less', seconds_order_end=0,
                                          time_in_force='GoodTillCancelled', iceberg_fixed=None, iceberg_variance=None, check_duplicates=True, activate=True):
        """Создание стоп-лимитной заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param float limit_price: Лимитная цена
        :param str comment: Пользовательский комментарий к заявке
        :param str condition: Условие срабатывания 'More', 'Less', 'MoreOrEqual', 'LessOrEqual'
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :param bool activate: Флаг активной заявки
        """
        request = {'opcode': 'create:stopLimit', 'side': side, 'quantity': abs(quantity), 'price': limit_price, 'condition': condition, 'triggerPrice': stop_price, 'stopEndUnixTime': seconds_order_end,
                   'instrument': {'symbol': symbol, 'exchange': exchange}, 'comment': comment, 'board': board, 'user': {'portfolio': portfolio, 'exchange': exchange},
                   'timeInForce': time_in_force, 'checkDuplicates': check_duplicates, 'activate': activate}
        if iceberg_fixed:
            request['icebergFixed'] = iceberg_fixed
        if iceberg_variance:
            request['icebergVariance'] = iceberg_variance
        return self.send_websocket(request)

    def edit_market_order_websocket(self, order_id, portfolio, exchange, board, symbol, side, quantity, comment='', time_in_force='GoodTillCancelled', check_duplicates=True):
        """Изменение рыночной заявки

        :param int order_id: Номер заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param str comment: Пользовательский комментарий к заявке
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        """
        request = {'opcode': 'update:market', 'orderId': order_id, 'side': side, 'quantity': abs(quantity),
                   'instrument': {'exchange': exchange, 'symbol': symbol}, 'comment': comment, 'board': board, 'user': {'portfolio': portfolio}, 'timeInForce': time_in_force, 'checkDuplicates': check_duplicates}
        return self.send_websocket(request)

    def edit_limit_order_websocket(self, order_id, portfolio, exchange, board, symbol, side, quantity, limit_price, comment='', time_in_force='GoodTillCancelled', iceberg_fixed=None, iceberg_variance=None, check_duplicates=True):
        """Изменение лимитной заявки

        :param int order_id: Номер заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float limit_price: Лимитная цена
        :param str comment: Пользовательский комментарий к заявке
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        """
        request = {'opcode': 'update:limit', 'orderId': order_id, 'side': side, 'quantity': abs(quantity), 'price': limit_price, 'instrument': {'exchange': exchange, 'symbol': symbol}, 'comment': comment,
                   'board': board, 'user': {'portfolio': portfolio}, 'timeInForce': time_in_force, 'checkDuplicates': check_duplicates}
        if iceberg_fixed:
            request['icebergFixed'] = iceberg_fixed
        if iceberg_variance:
            request['icebergVariance'] = iceberg_variance
        return self.send_websocket(request)

    def edit_stop_order_websocket(self, order_id, portfolio, exchange, symbol, board, side, quantity, stop_price, comment='', condition='Less', seconds_order_end=0, check_duplicates=True, activate=True):
        """Изменение стоп-заявки

        :param int order_id: Номер заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param str comment: Пользовательский комментарий к заявке
        :param str condition: Условие срабатывания 'More', 'Less', 'MoreOrEqual', 'LessOrEqual'
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :param bool activate: Флаг активной заявки
        """
        request = {'opcode': 'update:stop', 'orderId': order_id, 'side': side, 'quantity': abs(quantity), 'condition': condition, 'triggerPrice': stop_price, 'stopEndUnixTime': seconds_order_end,
                   'instrument': {'symbol': symbol, 'exchange': exchange}, 'comment': comment, 'board': board, 'user': {'portfolio': portfolio, 'exchange': exchange},
                   'checkDuplicates': check_duplicates, 'activate': activate}
        return self.send_websocket(request)

    def edit_stop_limit_order_websocket(self, order_id, portfolio, exchange, symbol, board, side, quantity, stop_price, limit_price, comment='', condition='Less', seconds_order_end=0,
                                        time_in_force='GoodTillCancelled', iceberg_fixed=None, iceberg_variance=None, check_duplicates=True, activate=True):
        """Изменение стоп-лимитной заявки

        :param int order_id: Номер заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param float limit_price: Лимитная цена
        :param str comment: Пользовательский комментарий к заявке
        :param str condition: Условие срабатывания 'More', 'Less', 'MoreOrEqual', 'LessOrEqual'
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :param bool activate: Флаг активной заявки
        """
        request = {'opcode': 'update:stopLimit', 'orderId': order_id, 'side': side, 'quantity': abs(quantity), 'price': limit_price, 'condition': condition, 'triggerPrice': stop_price, 'stopEndUnixTime': seconds_order_end,
                   'instrument': {'symbol': symbol, 'exchange': exchange}, 'comment': comment, 'board': board, 'user': {'portfolio': portfolio, 'exchange': exchange},
                   'timeInForce': time_in_force, 'checkDuplicates': check_duplicates, 'activate': activate}
        if iceberg_fixed:
            request['icebergFixed'] = iceberg_fixed
        if iceberg_variance:
            request['icebergVariance'] = iceberg_variance
        return self.send_websocket(request)

    def delete_market_order_websocket(self, order_id, portfolio, exchange, check_duplicates=True):
        """Снятие рыночной заявки рыночной заявки

        :param int order_id: Номер заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        """
        request = {'opcode': 'delete:market', 'orderId': order_id, 'exchange': exchange, 'user': {'portfolio': portfolio}, 'checkDuplicates': check_duplicates}
        return self.send_websocket(request)

    def delete_limit_order_websocket(self, order_id, portfolio, exchange, check_duplicates=True):
        """Снятие лимитной заявки

        :param int order_id: Номер заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        """
        request = {'opcode': 'delete:limit', 'orderId': order_id, 'exchange': exchange, 'user': {'portfolio': portfolio}, 'checkDuplicates': check_duplicates}
        return self.send_websocket(request)

    def delete_stop_order_websocket(self, order_id, portfolio, exchange, check_duplicates=True):
        """Снятие стоп-заявки

        :param int order_id: Номер заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        """
        request = {'opcode': 'delete:stop', 'orderId': order_id, 'exchange': exchange, 'user': {'portfolio': portfolio}, 'checkDuplicates': check_duplicates}
        return self.send_websocket(request)

    def delete_stop_limit_order_websocket(self, order_id, portfolio, exchange, check_duplicates=True):
        """Снятие стоп-лимитной заявки

        :param int order_id: Номер заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        """
        request = {'opcode': 'delete:stopLimit', 'orderId': order_id, 'exchange': exchange, 'user': {'portfolio': portfolio}, 'checkDuplicates': check_duplicates}
        return self.send_websocket(request)

    # OrderGroups - Группы заявок

    def get_order_groups(self):
        """Получение всех групп заявок"""
        return self.check_result(get(url=f'{self.api_server}/commandapi/api/orderGroups', headers=self.get_headers()))

    def get_order_group(self, order_group_id):
        """Получение информации о группе заявок

        :param str order_group_id: Идентификатор группы заявок
        """
        return self.check_result(get(url=f'{self.api_server}/commandapi/api/orderGroups{order_group_id}', headers=self.get_headers()))

    def create_order_group(self, orders, execution_policy):
        """Создание группы заявок

        :param orders: Заявки, из которых будет состоять группа. Каждая заявка состоит из:
            'Portfolio' - Идентификатор клиентского портфеля
            'Exchange' - Биржа 'MOEX' или 'SPBX'
            'OrderId' - Идентификатор заявки
            'Type' - Тип заявки. 'Market' - Рыночная заявка. 'Limit' - Лимитная заявка. 'Stop' - Стоп-заявка. 'StopLimit' - Стоп-лимит заявка
        :param str execution_policy: Тип группы заявок:
            'OnExecuteOrCancel' - Группа отменяется при отмене/выполнении/редактировании любой заявки
            'IgnoreCancel' - Группа отменяется при исполнении заявки. При отмене или редактировании заявки - заявка удаляется из группы, группа остаётся активной
            'TriggerBracketOrders' - Группа, содержащая одну лимитную заявку и несколько стопов. Для создания группы, стоп-заявки должны быть созданны с флагом 'Activate = false'. После выполнения лимитной заявки, активируются стоп-заявки
        """
        j = {'Orders': orders, 'ExecutionPolicy': execution_policy}
        return self.check_result(post(url=f'{self.api_server}/commandapi/api/orderGroups', headers=self.get_headers(), json=j))

    def edit_order_group(self, order_group_id, orders, execution_policy):
        """Редактирование группы заявок (связывание новых заявок, изменение типа связи)

        :param str order_group_id: Идентификатор группы заявок
        :param orders: Заявки, из которых будет состоять группа. Каждая заявка состоит из:
            'Portfolio' - Идентификатор клиентского портфеля
            'Exchange' - Биржа 'MOEX' или 'SPBX'
            'OrderId' - Идентификатор заявки
            'Type' - Тип заявки. 'Market' - Рыночная заявка. 'Limit' - Лимитная заявка. 'Stop' - Стоп-заявка. 'StopLimit' - Стоп-лимит заявка
        :param str execution_policy: Тип группы заявок:
            'OnExecuteOrCancel' - Группа отменяется при отмене/выполнении/редактировании любой заявки
            'IgnoreCancel' - Группа отменяется при исполнении заявки. При отмене или редактировании заявки - заявка удаляется из группы, группа остаётся активной
            'TriggerBracketOrders' - Группа, содержащая одну лимитную заявку и несколько стопов. Для создания группы, стоп-заявки должны быть созданны с флагом 'Activate = false'. После выполнения лимитной заявки, активируются стоп-заявки
        """
        j = {'Orders': orders, 'ExecutionPolicy': execution_policy}
        return self.check_result(put(url=f'{self.api_server}/commandapi/api/orderGroups{order_group_id}', headers=self.get_headers(), json=j))

    def delete_order_group(self, order_group_id):
        """Удаление группы заявок

        :param str order_group_id: Идентификатор группы заявок
        """
        return self.check_result(delete(url=f'{self.api_server}/commandapi/api/orderGroups{order_group_id}', headers=self.get_headers()))

    # Deprecated Устаревшее

    def get_portfolios(self, user_name):
        """Получение списка серверов портфелей

        :param str user_name: Номер счета
        """
        return self.check_result(get(url=f'{self.api_server}/client/v1.0/users/{user_name}/portfolios', headers=self.get_headers()))

    def get_money(self, portfolio, exchange, format='Simple'):
        """Получение информации по деньгам для выбранного портфеля

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/clients/legacy/{exchange}/{portfolio}/money', params=params, headers=self.get_headers()))

    def get_trades_history(self, portfolio, exchange, date_from=None, id_from=None, limit=None, descending=None, format='Simple'):
        """Получение истории сделок

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str date_from: Начиная с какой даты отдавать историю сделок. Например, '2021-10-13'
        :param int id_from: Начиная с какого ID (номера сделки) отдавать историю сделок
        :param int limit: Ограничение на количество выдаваемых результатов поиска
        :param bool descending: Флаг обратной сортировки выдачи
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        if date_from:
            params['dateFrom'] = date_from
        if id_from:
            params['from'] = id_from
        if limit:
            params['limit'] = limit
        if descending:
            params['descending'] = descending
        return self.check_result(get(url=f'{self.api_server}/md/stats/{exchange}/{portfolio}/history/trades', params=params, headers=self.get_headers()))

    def get_trades_symbol(self, portfolio, exchange, symbol, date_from=None, id_from=None, limit=None, descending=None, format='Simple'):
        """Получение истории сделок (один тикер)

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str date_from: Начиная с какой даты отдавать историю сделок. Например, '2021-10-13'
        :param int id_from: Начиная с какого ID (номера сделки) отдавать историю сделок
        :param int limit: Ограничение на количество выдаваемых результатов поиска
        :param bool descending: Флаг загрузки элементов с конца списка
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        if date_from:
            params['dateFrom'] = date_from
        if id_from:
            params['from'] = id_from
        if limit:
            params['limit'] = limit
        if descending:
            params['descending'] = descending
        return self.check_result(get(url=f'{self.api_server}/md/stats/{exchange}/{portfolio}/history/trades/{symbol}', params=params, headers=self.get_headers()))

    def get_exchange_market(self, exchange, market, format='Simple'):
        """Получение информации о статусе торгов

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str market: Рынок на бирже: FORTS, FOND, CURR, SPBX
        :param str format: Формат принимаемых данных 'Simple', 'Slim', 'Heavy'
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/status/{exchange}/{market}', params=params, headers=self.get_headers()))

    def create_stop_loss_order(self, trade_server_code, account, portfolio, exchange, symbol, side, quantity, stop_price, seconds_order_end=0):
        """Создание стоп-лосс заявки

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        j = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': stop_price, 'Instrument': {'Symbol': symbol, 'Exchange': exchange},
             'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': seconds_order_end}
        return self.check_result(post(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/actions/stopLoss', headers=headers, json=j))

    def create_take_profit_order(self, trade_server_code, account, portfolio, exchange, symbol, side, quantity, stop_price, seconds_order_end=0):
        """Создание стоп-заявки

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        j = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': stop_price, 'Instrument': {'Symbol': symbol, 'Exchange': exchange},
             'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': seconds_order_end}
        return self.check_result(post(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/actions/takeProfit', headers=headers, json=j))

    def create_take_profit_limit_order(self, trade_server_code, account, portfolio, exchange, symbol, side, quantity, stop_price, limit_price, seconds_order_end=0):
        """Создание стоп-лимит заявки

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param float limit_price: Лимитная цена
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        j = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': stop_price, 'Price': limit_price, 'Instrument': {'Symbol': symbol, 'Exchange': exchange},
             'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': seconds_order_end}
        return self.check_result(post(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/actions/takeProfitLimit', headers=headers, json=j))

    def create_stop_loss_limit_order(self, trade_server_code, account, portfolio, exchange, symbol, side, quantity, stop_price, limit_price, seconds_order_end=0):
        """Создание стоп-лосс лимит заявки

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param float limit_price: Лимитная цена
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        j = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': stop_price, 'Price': limit_price, 'Instrument': {'Symbol': symbol, 'Exchange': exchange},
             'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': seconds_order_end}
        return self.check_result(post(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/actions/stopLossLimit', headers=headers, json=j))

    def edit_stop_loss_order(self, trade_server_code, account, portfolio, exchange, order_id, symbol, side, quantity, stop_price, seconds_order_end=0):
        """Изменение стоп-лосс заявки

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int order_id: Номер заявки
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        j = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': stop_price, 'Instrument': {'Symbol': symbol, 'Exchange': exchange},
             'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': seconds_order_end}
        return self.check_result(put(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/actions/stopLoss/{order_id}', headers=headers, json=j))

    def edit_take_profit_order(self, trade_server_code, account, portfolio, exchange, order_id, symbol, side, quantity, stop_price, seconds_order_end=0):
        """Изменение стоп-заявки

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int order_id: Номер заявки
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        j = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': stop_price, 'Instrument': {'Symbol': symbol, 'Exchange': exchange},
             'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': seconds_order_end}
        return self.check_result(put(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/actions/takeProfit/{order_id}', headers=headers, json=j))

    def edit_take_profit_limit_order(self, trade_server_code, account, portfolio, exchange, order_id, symbol, side, quantity, stop_price, limit_price, seconds_order_end=0):
        """Изменение стоп-лимит заявки

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int order_id: Номер заявки
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param float limit_price: Лимитная цена
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        j = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': stop_price, 'Price': limit_price, 'Instrument': {'Symbol': symbol, 'Exchange': exchange},
             'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': seconds_order_end}
        return self.check_result(put(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/actions/takeProfitLimit/{order_id}', headers=headers, json=j))

    def edit_stop_loss_limit_order(self, trade_server_code, account, portfolio, exchange, order_id, symbol, side, quantity, stop_price, limit_price, seconds_order_end=0):
        """Изменение стоп-лосс лимит заявки

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int order_id: Номер заявки
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param float limit_price: Лимитная цена
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        j = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': stop_price, 'Price': limit_price, 'Instrument': {'Symbol': symbol, 'Exchange': exchange},
             'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': seconds_order_end}
        return self.check_result(put(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/actions/stopLossLimit/{order_id}', headers=headers, json=j))

    def delete_stop_order(self, trade_server_code, portfolio, order_id, stop=True):
        """Снятие стоп-заявки

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str portfolio: Идентификатор клиентского портфеля
        :param int order_id: Номер заявки
        :param bool stop: Является ли стоп заявкой
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        params = {'portfolio': portfolio, 'stop': stop}
        return self.check_result(delete(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/{order_id}', headers=headers, params=params))

    def stop_orders_get_and_subscribe(self, portfolio, exchange) -> str:
        """Подписка на информацию о текущих стоп-заявках на рынке для выбранных биржи и финансового инструмента

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'StopOrdersGetAndSubscribe', 'exchange': exchange, 'portfolio': portfolio, 'format': 'Simple'}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    # Запросы REST

    def get_jwt_token(self):
        """Получение, выдача, обновление JWT токена"""
        now = int(datetime.timestamp(datetime.now()))  # Текущая дата и время в виде UNIX времени в секундах
        if self.jwt_token is None or now - self.jwt_token_issued > self.jwt_token_ttl:  # Если токен JWT не был выдан или был просрочен
            response = post(url=f'{self.oauth_server}/refresh', params={'token': self.refresh_token})  # Запрашиваем новый JWT токен с сервера аутентификации
            if response.status_code != 200:  # Если при получении токена возникла ошибка
                self.on_error(f'Ошибка получения JWT токена: {response.status_code}')  # Событие ошибки
                self.jwt_token = None  # Сбрасываем токен JWT
                self.jwt_token_decoded = None  # Сбрасываем данные о портфелях
                self.jwt_token_issued = 0  # Сбрасываем время выдачи токена JWT
            else:  # Токен получен
                token = response.json()  # Читаем данные JSON
                self.jwt_token = token['AccessToken']  # Получаем токен JWT
                self.jwt_token_decoded = decode(self.jwt_token, options={'verify_signature': False})  # Получаем из него данные о портфелях
                self.jwt_token_issued = now  # Дата выдачи токена JWT
        return self.jwt_token

    def get_headers(self):
        """Получение хедеров для запросов"""
        return {'Content-Type': 'application/json', 'Authorization': f'Bearer {self.get_jwt_token()}'}

    @staticmethod
    def get_request_id():
        """Получение уникального кода запроса"""
        return f'{time_ns()}'  # Текущее время в наносекундах, прошедших с 01.01.1970 в UTC

    def check_result(self, response):
        """Анализ результата запроса

        :param Response response: Результат запроса
        :return: Справочник из JSON, текст, None в случае веб ошибки
        """
        if not response:  # Если ответ не пришел. Например, при таймауте
            self.on_error('Ошибка сервера: Таймаут')  # Событие ошибки
            return None  # то возвращаем пустое значение
        content = response.content.decode('utf-8')  # Результат запроса
        if response.status_code != 200:  # Если статус ошибки
            self.on_error(f'Ошибка сервера: {response.status_code} Запрос: {response.request.path_url} Ответ: {content}')  # Событие ошибки
            return None  # то возвращаем пустое значение
        # self.logger.debug(f'Запрос: {response.request.path_url} Ответ: {content}')  # Для отладки
        try:
            return loads(content)  # Декодируем JSON в справочник, возвращаем его. Ошибки также могут приходить в виде JSON
        except JSONDecodeError:  # Если произошла ошибка при декодировании JSON, например, при удалении заявок
            return content  # то возвращаем значение в виде текста

    # Запросы WebSocket

    def send_websocket(self, request):
        """Отправка запроса WebSocket

        :param request: Запрос JSON
        :return: JSON, текст, None в случае веб ошибки
        """
        response = get_event_loop().run_until_complete(self.send_websocket_async(request))  # Запускаем асинхронную фукнцию с параметрами. Дожидаемся выполнения. Получаем результат
        return self.check_websocket_result(response)  # Возвращаем результат после анализа

    async def send_websocket_async(self, request):
        """Отправка асинхронного запроса WebSocket

        :param request: Запрос JSON
        :return: Ответ JSON
        """
        if not self.cws_socket:  # Если не было подключения к серверу WebSocket
            self.cws_socket = await connect(self.cws_server)  # то пробуем к нему подключиться
        request['guid'] = str(uuid4())  # Получаем уникальный идентификатор запроса, ставим его в запрос
        await self.cws_socket.send(dumps(request))  # Переводим JSON в строку, отправляем запрос
        return await self.cws_socket.recv()  # Дожидаемся ответа, возвращаем его

    def check_websocket_result(self, response):
        """Анализ результата запроса WebSocket

        :param response: Ответ JSON
        :return: JSON, текст, None в случае веб ошибки
        """
        try:
            json_response = loads(response)  # Декодируем JSON в справочник, возвращаем его. Ошибки также могут приходить в виде JSON
        except JSONDecodeError:  # Если произошла ошибка при декодировании JSON, например, при удалении заявок
            return response  # то возвращаем значение в виде текста
        http_code = json_response['httpCode']  # Код 200 или ошибки
        if http_code != 200:  # Если в результате запроса произошла ошибка
            self.on_error(f'Ошибка сервера: {http_code} {response["message"]}')  # Событие ошибки
            return None  # то возвращаем пустое значение
        return json_response  # Возвращаем JSON

    # Подписки WebSocket

    def default_handler(self, response=None):
        """Пустой обработчик события по умолчанию. Его можно заменить на пользовательский"""
        pass

    def subscribe(self, request) -> str:
        """Запуск WebSocket, если не запущен. Отправка запроса подписки на сервер WebSocket

        :param request request: Запрос
        :return: Уникальный идентификатор подписки
        """
        if not self.ws_ready:  # Если WebSocket не готов принимать запросы
            self.on_entering()  # Событие начала входа (Thread)
            Thread(target=run, args=(self.websocket_async(),)).start()  # Создаем и запускаем поток управления подписками
        while not self.ws_ready:  # Подключение к серверу WebSocket выполняется в отдельном потоке
            pass  # Подождем, пока WebSocket не будет готов принимать запросы
        guid = str(uuid4())  # Уникальный идентификатор подписки
        thread = Thread(target=run, args=(self.subscribe_async(request, guid),))  # Поток подписки
        thread.start()  # Запускаем
        thread.join()  # Ожидаем завершения
        return guid

    async def websocket_async(self):
        """Запуск и управление задачей подписок"""
        self.on_enter()  # Событие входа (Thread)
        while True:  # Будем держать соединение с сервером WebSocket до отмены
            self.ws_task = create_task(self.websocket_handler())  # Запускаем задачу (Task) подключения к серверу WebSocket и получения с него подписок
            try:
                await self.ws_task  # Ожидаем отмены задачи
            except CancelledError:  # Если задачу отменили
                break  # то выходим, дальше не продолжаем
        self.on_exit()  # Событие выхода (Thread)

    async def websocket_handler(self):
        """
        - Подключение к серверу WebSocket
        - Переподключение к серверу WebSocket. Возобновление подписок, если требуется
        - Получение данных подписок до отмены. Запуск событий подписок
        """
        try:
            # Для всех подписок используем 1 WebSocket. У Алора нет ограничений на кол-во соединений
            # Но подключение сбрасывается, если в очереди соединения находится более 5000 непрочитанных сообщений
            # Это может быть из-за медленного компьютера или слабого канала связи
            # В любом из этих случаев создание дополнительных подключений проблему не решит
            self.ws_socket = await connect(self.ws_server)  # Пробуем подключиться к серверу WebSocket
            self.on_connect()  # Событие подключения к серверу (Task)

            if len(self.subscriptions) > 0:  # Если есть подписки, то будем их возобновлять
                self.on_resubscribe()  # Событие возобновления подписок (Task)
                for guid, request in self.subscriptions.items():  # Пробегаемся по всем подпискам
                    await self.subscribe_async(request, guid)  # Переподписываемся с тем же уникальным идентификатором
            self.ws_ready = True  # Готов принимать запросы
            self.on_ready()  # Событие готовности к работе (Task)

            while True:  # Получаем подписки до отмены
                response_json = await self.ws_socket.recv()  # Ожидаем следующую строку в виде JSON
                try:
                    response = loads(response_json)  # Переводим JSON в словарь
                except JSONDecodeError:  # Если вместо JSON сообщений получаем текст (проверка на всякий случай)
                    self.logger.warning(f'websocket_handler: Пришли данные подписки не в формате JSON {response_json}. Пропуск')
                    continue  # то его не разбираем, пропускаем
                if 'data' not in response:  # Если пришло сервисное сообщение о подписке/отписке
                    continue  # то его не разбираем, пропускаем
                guid = response['guid']  # GUID подписки
                if guid not in self.subscriptions:  # Если подписка не найдена
                    self.logger.debug(f'websocket_handler: Поступившая подписка с кодом {guid} не найдена. Пропуск')
                    continue  # то мы не можем сказать, что это за подписка, пропускаем ее
                subscription = self.subscriptions[guid]  # Поиск подписки по GUID
                opcode = subscription['opcode']  # Разбираем по типу подписки
                self.logger.debug(f'websocket_handler: Пришли данные подписки {opcode} - {guid} - {response}')
                if opcode == 'OrderBookGetAndSubscribe':  # Биржевой стакан
                    self.on_change_order_book(response)
                elif opcode == 'BarsGetAndSubscribe':  # Новый бар
                    if subscription['prev']:  # Если есть предыдущее значение
                        seconds = response['data']['time']  # Время пришедшего бара
                        prev_seconds = subscription['prev']['data']['time']  # Время предыдущего бара
                        if seconds == prev_seconds:  # Пришла обновленная версия текущего бара
                            subscription['prev'] = response  # то запоминаем пришедший бар
                        elif seconds > prev_seconds:  # Пришел новый бар
                            self.logger.debug(f'websocket_handler: OnNewBar {subscription["prev"]}')
                            self.on_new_bar(subscription['prev'])
                            subscription['prev'] = response  # Запоминаем пришедший бар
                    else:  # Если пришло первое значение
                        subscription['prev'] = response  # то запоминаем пришедший бар
                elif opcode == 'QuotesSubscribe':  # Котировки
                    self.on_new_quotes(response)
                elif opcode == 'AllTradesGetAndSubscribe':  # Все сделки
                    self.on_all_trades(response)
                elif opcode == 'PositionsGetAndSubscribeV2':  # Позиции по ценным бумагам и деньгам
                    self.on_position(response)
                elif opcode == 'SummariesGetAndSubscribeV2':  # Сводная информация по портфелю
                    self.on_summary(response)
                elif opcode == 'RisksGetAndSubscribe':  # Портфельные риски
                    self.on_risk(response)
                elif opcode == 'SpectraRisksGetAndSubscribe':  # Риски срочного рынка (FORTS)
                    self.on_spectra_risk(response)
                elif opcode == 'TradesGetAndSubscribeV2':  # Сделки
                    self.on_trade(response)
                elif opcode == 'StopOrdersGetAndSubscribe':  # Стоп заявки
                    self.on_stop_order(response)
                elif opcode == 'StopOrdersGetAndSubscribeV2':  # Стоп заявки v2
                    self.on_stop_order_v2(response)
                elif opcode == 'OrdersGetAndSubscribeV2':  # Заявки
                    self.on_order(response)
                elif opcode == 'InstrumentsGetAndSubscribeV2':  # Информация о финансовых инструментах
                    self.on_symbol(response)
        except CancelledError:  # Задачу отменили
            self.on_cancel()  # Событие отмены и завершения (Task)
            raise  # Передаем исключение на родительский уровень WebSocketHandler
        except ConnectionClosed:  # Отключились от сервера WebSockets
            self.on_disconnect()  # Событие отключения от сервера (Task)
        except (OSError, TimeoutError, MaxRetryError):  # При системной ошибке, таймауте на websockets, достижении максимального кол-ва попыток подключения
            self.on_timeout()  # Событие таймаута/максимального кол-ва попыток подключения (Task)
        except Exception as ex:  # При других типах ошибок
            self.on_error(f'Ошибка {ex}')  # Событие ошибки (Task)
        finally:
            self.ws_ready = False  # Не готов принимать запросы
            self.ws_socket = None  # Сбрасываем подключение

    async def subscribe_async(self, request, guid):
        """Отправка запроса (пере)подписки на сервер WebSocket

        :param request: Запрос
        :param str guid: Уникальный идентификатор подписки
        :return: Справочник из JSON, текст, None в случае веб ошибки
        """
        if request['opcode'] == 'BarsGetAndSubscribe' and 'prev' not in request:  # Для подписки на новые бары если нет последнего полученного бара (для подписки)
            request['prev'] = None  # то ставим пустую дату и время последнего полученного бара UTC в секундах
        self.subscriptions[guid] = request  # Заносим подписку в справочник
        request['token'] = self.get_jwt_token()  # Получаем JWT токен, ставим его в запрос
        request['guid'] = guid  # Уникальный идентификатор подписки тоже ставим в запрос
        await self.ws_socket.send(dumps(request))  # Отправляем запрос

    # Выход и закрытие

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Выход из класса, например, с with"""
        self.close_web_socket()  # Закрываем соединение с сервером WebSocket

    def __del__(self):
        self.close_web_socket()  # Закрываем соединение с сервером WebSocket

    def close_web_socket(self):
        """Закрытие соединения с сервером WebSocket"""
        if self.ws_socket:  # Если запущена задача управления подписками WebSocket
            self.ws_task.cancel()  # то отменяем задачу. Генерируем на ней исключение asyncio.CancelledError

    # Функции конвертации

    def dataname_to_board_symbol(self, dataname) -> tuple[str, str]:
        """Код режима торгов и тикер из названия тикера

        :param str dataname: Название тикера
        :return: Код режима торгов и тикер
        """
        board = None  # Код режима торгов
        symbol_parts = dataname.split('.')  # По разделителю пытаемся разбить тикер на части
        if len(symbol_parts) >= 2:  # Если тикер задан в формате <Код режима торгов>.<Код тикера>
            board = symbol_parts[0]  # Код режима торгов
            symbol = '.'.join(symbol_parts[1:])  # Код тикера
        else:  # Если тикер задан без кода режима торгов
            symbol = dataname  # Код тикера
            for ex in self.exchanges:  # Пробегаемся по всем биржам
                si = self.get_symbol_info(ex, symbol)  # Получаем информацию о тикере
                if si:  # Если тикер найден на бирже
                    board = si['board']  # то подставляем его код режима торгов
                    break  # Выходим, дальше не продолжаем
        if board == 'SPBFUT':  # Для фьючерсов
            board = 'RFUD'  # Меняем код режима торгов на принятое в Алоре
        return board, symbol

    @staticmethod
    def board_symbol_to_dataname(board, symbol) -> str:
        """Название тикера из кода режима торгов и тикера

        :param str board: Код режима торгов
        :param str symbol: Тикер
        :return: Название тикера
        """
        if board == 'RFUD':  # Для фьючерсов
            board = 'SPBFUT'  # Меняем код режима торгов на каноническое
        return f'{board}.{symbol}'

    def get_account(self, board, account_id=0) -> Union[dict, None]:
        """Счет из кода режима торгов и номера счета

        :param str board: Код режима торгов
        :param int account_id: Порядковый номер счета
        :return: Счет
        """
        if board == 'CETS':  # Для валютного рынка
            return next((account for account in self.accounts if account['account_id'] == account_id and account['portfolio'].startswith('G')), None)
        elif board in ('RFUD', 'ROPD'):  # Для фьючерсов и опционов
            return next((account for account in self.accounts if account['account_id'] == account_id and not account['portfolio'].startswith('G') and not account['portfolio'].startswith('D')), None)
        else:  # Для остальных рынков
            return next((account for account in self.accounts if account['account_id'] == account_id and account['portfolio'].startswith('D')), None)

    def get_exchange(self, board, symbol):
        """Биржа тикера из кода режима торгов и тикера

        :param str board: Код режима торгов
        :param str symbol: Тикер
        :return: Биржа 'MOEX' или 'SPBX'
        """
        if board == 'SPBFUT':  # Для фьючерсов
            board = 'RFUD'  # Меняем код режима торгов на принятое в Алоре
        for exchange in self.exchanges:  # Пробегаемся по всем биржам
            si = self.get_symbol_info(exchange, symbol)  # Получаем информацию о тикере
            if si and si['board'] == board:  # Если информация о тикере найдена, и режим торгов есть на бирже
                return exchange  # то биржа найдена
        self.logger.warning(f'Биржа для {board}.{symbol} не найдена')
        return None  # Если биржа не была найдена, то возвращаем пустое значение

    def get_symbol_info(self, exchange, symbol, reload=False):
        """Спецификация тикера

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param bool reload: Получить информацию из Алор
        :return: Значение из кэша/Алор или None, если тикер не найден
        """
        if reload or (exchange, symbol) not in self.symbols:  # Если нужно получить информацию из Алор или нет информации о тикере в справочнике
            symbol_info = self.get_symbol(exchange, symbol)  # Получаем информацию о тикере из Алор
            if not symbol_info:  # Если тикер не найден
                self.logger.warning(f'Информация о {exchange}.{symbol} не найдена')
                return None  # то возвращаем пустое значение
            self.symbols[(exchange, symbol)] = symbol_info  # Заносим информацию о тикере в справочник
        return self.symbols[(exchange, symbol)]  # Возвращаем значение из справочника

    @staticmethod
    def timeframe_to_alor_timeframe(tf) -> tuple[Union[str, int], bool]:
        """Перевод временнОго интервала во временной интервал Алора

        :param str tf: Временной интервал https://ru.wikipedia.org/wiki/Таймфрейм
        :return: Временной интервал Алора, внутридневной интервал
        """
        if 'MN' in tf:  # Месячный временной интервал
            return 'M', False
        if tf[0:1] in ('D', 'W', 'Y'):  # Дневной/недельный/годовой интервалы
            return tf[0:1], False
        if tf[0:1] == 'M':  # Минутный временной интервал
            return int(tf[1:]) * 60, True  # переводим из минут в секунды
        raise NotImplementedError  # С остальными временнЫми интервалами не работаем

    @staticmethod
    def alor_timeframe_to_timeframe(tf) -> tuple[str, bool]:
        """Перевод временнОго интервала Алора во временной интервал

        :param str|int tf: Временной интервал Алора
        :return: Временной интервал https://ru.wikipedia.org/wiki/Таймфрейм, внутридневной интервал
        """
        if tf in ('D', 'W', 'Y'):  # Дневной/недельный/годовой интервалы
            return f'{tf}1', False
        if tf == 'M':  # Месячный интервал
            return f'MN1', False
        if isinstance(tf, int):  # Интервал в секундах
            return f'M{int(tf) // 60}', True  # переводим из секунд в минуты
        raise NotImplementedError  # С остальными временнЫми интервалами не работаем

    def price_to_alor_price(self, exchange, symbol, price) -> float:
        """Перевод цены в цену Алор

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param float price: Цена
        :return: Цена в Алор
        """
        si = self.get_symbol_info(exchange, symbol)  # Информация о тикере
        min_step = si['minstep']  # Шаг цены
        primary_board = si['primary_board']  # Рынок тикера
        if primary_board in ('TQOB', 'TQCB', 'TQRD', 'TQIR'):  # Для облигаций (Т+ Гособлигации, Т+ Облигации, Т+ Облигации Д, Т+ Облигации ПИР)
            alor_price = price * 100 / si['facevalue']  # Пункты цены для котировок облигаций представляют собой проценты номинала облигации
        elif primary_board == 'RFUD' and si['cfiCode'] == 'FFCCSX':  # Для вечных фьючерсов
            alor_price = price / si['facevalue']
        elif primary_board == 'CETS':  # Для валют
            alor_price = price / si.lot * si['facevalue']
        else:  # В остальных случаях
            alor_price = price  # Цена не изменяется
        decimals = int(log10(1 / min_step) + 0.99)  # Из шага цены получаем кол-во десятичных знаков
        return round(alor_price // min_step * min_step, decimals)  # Округляем цену кратно шага цены

    def alor_price_to_price(self, exchange, symbol, alor_price) -> float:
        """Перевод цены Алор в цену

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param float alor_price: Цена в Алор
        :return: Цена
        """
        si = self.get_symbol_info(exchange, symbol)  # Информация о тикере
        min_step = si['minstep']  # Шаг цены
        alor_price = alor_price // min_step * min_step  # Цена кратная шагу цены
        primary_board = si['primary_board']  # Код площадки
        if primary_board in ('TQOB', 'TQCB', 'TQRD', 'TQIR'):  # Для облигаций (Т+ Гособлигации, Т+ Облигации, Т+ Облигации Д, Т+ Облигации ПИР)
            price = alor_price / 100 * si['facevalue']  # Пункты цены для котировок облигаций представляют собой проценты номинала облигации
        elif primary_board == 'RFUD' and si['cfiCode'] == 'FFCCSX':  # Для вечных фьючерсов
            price = alor_price * si['facevalue']
        elif primary_board == 'CETS':  # Для валют
            price = alor_price * si['lot'] / si['facevalue']
        else:  # В остальных случаях
            price = alor_price  # Цена не изменяется
        decimals = int(log10(1 / min_step) + 0.99)  # Из шага цены получаем кол-во десятичных знаков
        return round(price, decimals)  # Округляем цену

    def msk_datetime_to_utc_timestamp(self, dt) -> int:
        """Перевод московского времени в кол-во секунд, прошедших с 01.01.1970 00:00 UTC

        :param datetime dt: Московское время
        :return: Кол-во секунд, прошедших с 01.01.1970 00:00 UTC
        """
        dt_msk = self.tz_msk.localize(dt)  # Заданное время ставим в зону МСК
        return int(dt_msk.timestamp())  # Переводим в кол-во секунд, прошедших с 01.01.1970 в UTC

    def utc_timestamp_to_msk_datetime(self, seconds) -> datetime:
        """Перевод кол-ва секунд, прошедших с 01.01.1970 00:00 UTC в московское время

        :param int seconds: Кол-во секунд, прошедших с 01.01.1970 00:00 UTC
        :return: Московское время без временнОй зоны
        """
        dt_utc = datetime.utcfromtimestamp(seconds)  # Переводим кол-во секунд, прошедших с 01.01.1970 в UTC
        return self.utc_to_msk_datetime(dt_utc)  # Переводим время из UTC в московское

    def msk_to_utc_datetime(self, dt, tzinfo=False) -> datetime:
        """Перевод времени из московского в UTC

        :param datetime dt: Московское время
        :param bool tzinfo: Отображать временнУю зону
        :return: Время UTC
        """
        dt_msk = self.tz_msk.localize(dt)  # Задаем временнУю зону МСК
        dt_utc = dt_msk.astimezone(utc)  # Переводим в UTC
        return dt_utc if tzinfo else dt_utc.replace(tzinfo=None)

    def utc_to_msk_datetime(self, dt, tzinfo=False) -> datetime:
        """Перевод времени из UTC в московское

        :param datetime dt: Время UTC
        :param bool tzinfo: Отображать временнУю зону
        :return: Московское время
        """
        dt_utc = utc.localize(dt)  # Задаем временнУю зону UTC
        dt_msk = dt_utc.astimezone(self.tz_msk)  # Переводим в МСК
        return dt_msk if tzinfo else dt_msk.replace(tzinfo=None)
