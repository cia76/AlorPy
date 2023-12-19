from math import log10  # Кол-во десятичных знаков будем получать из шага цены через десятичный логарифм
from datetime import datetime
from time import time_ns  # Текущее время в наносекундах, прошедших с 01.01.1970 UTC

import requests.adapters
from pytz import timezone, utc  # Работаем с временнОй зоной и UTC
from uuid import uuid4  # Номера подписок должны быть уникальными во времени и пространстве
from json import loads, JSONDecodeError, dumps  # Сервер WebSockets работает с JSON сообщениями
from requests import post, get, put, delete  # Запросы/ответы от сервера запросов
from urllib3.exceptions import MaxRetryError  # Соединение с сервером не установлено за максимальное кол-во попыток подключения
from asyncio import get_event_loop, create_task, run, CancelledError  # Работа с асинхронными функциями
from threading import Thread  # Подписки сервера WebSockets будем получать в отдельном потоке
from websockets import connect, ConnectionClosed  # Работа с сервером WebSockets


class AlorPy:
    """Работа с Alor OpenAPI V2 из Python https://alor.dev/docs"""
    requests.adapters.DEFAULT_RETRIES = 10  # Кол-во попыток (недокументированная команда)
    requests.adapters.DEFAULT_POOL_TIMEOUT = 10  # Таймаут запроса в секундах (недокументированная команда)
    tz_msk = timezone('Europe/Moscow')  # Время UTC будем приводить к московскому времени
    jwt_token_ttl = 60  # Время жизни токена JWT в секундах
    exchanges = ('MOEX', 'SPBX',)  # Биржи

    def __init__(self, user_name, refresh_token, demo=False):
        """Инициализация

        :param str user_name: Имя пользователя
        :param str refresh_token: Токен
        :param bool demo: Режим демо торговли. По умолчанию установлен режим реальной торговли
        """
        self.oauth_server = f'https://oauth{"dev" if demo else ""}.alor.ru'  # Сервер аутентификации
        self.api_server = f'https://api{"dev" if demo else ""}.alor.ru'  # Сервер запросов
        self.user_name = user_name  # Имя пользователя
        self.refresh_token = refresh_token  # Токен
        self.jwt_token = None  # Токен JWT
        self.jwt_token_issued = 0  # UNIX время в секундах выдачи токена JWT

        self.symbols = {}  # Справочник тикеров

        self.cws_server = f'wss://api{"dev" if demo else ""}.alor.ru/cws'  # Сервис работы с заявками WebSocket
        self.cws_socket = None  # Подключение к серверу WebSocket

        self.ws_server = f'wss://api{"dev" if demo else ""}.alor.ru/ws'  # Сервис подписок и событий WebSocket
        self.ws_socket = None  # Подключение к серверу WebSocket
        self.ws_task = None  # Задача управления подписками WebSocket
        self.ws_ready = False  # WebSocket готов принимать запросы
        self.subscriptions = {}  # Справочник подписок. Для возобновления всех подписок после перезагрузки сервера Алор

        # События Alor OpenAPI V2
        self.OnChangeOrderBook = self.default_handler  # Биржевой стакан
        self.OnNewBar = self.default_handler  # Новый бар
        self.OnNewQuotes = self.default_handler  # Котировки
        self.OnAllTrades = self.default_handler  # Все сделки
        self.OnPosition = self.default_handler  # Позиции по ценным бумагам и деньгам
        self.OnSummary = self.default_handler  # Сводная информация по портфелю
        self.OnRisk = self.default_handler  # Портфельные риски
        self.OnSpectraRisk = self.default_handler  # Риски срочного рынка (FORTS)
        self.OnTrade = self.default_handler  # Сделки
        self.OnStopOrder = self.default_handler  # Стоп заявки
        self.OnStopOrderV2 = self.default_handler  # Стоп заявки v2
        self.OnOrder = self.default_handler  # Заявки
        self.OnSymbol = self.default_handler  # Информация о финансовых инструментах

        # События WebSocket Thread/Task
        self.OnEntering = self.default_handler  # Начало входа (Thread)
        self.OnEnter = self.default_handler  # Вход (Thread)
        self.OnConnect = self.default_handler  # Подключение к серверу (Task)
        self.OnResubscribe = self.default_handler  # Возобновление подписок (Task)
        self.OnReady = self.default_handler  # Готовность к работе (Task)
        self.OnDisconnect = self.default_handler  # Отключение от сервера (Task)
        self.OnTimeout = self.default_handler  # Таймаут/максимальное кол-во попыток подключения (Task)
        self.OnError = self.default_handler  # Ошибка (Task)
        self.OnCancel = self.default_handler  # Отмена (Task)
        self.OnExit = self.default_handler  # Выход (Thread)

    def __enter__(self):
        """Вход в класс, например, с with"""
        return self

    # ClientInfo - Информация о клиенте

    def get_portfolio_summary(self, portfolio, exchange):
        """Получение информации о портфеле

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/clients/{exchange}/{portfolio}/summary', headers=self.get_headers()))

    def get_positions(self, portfolio, exchange, without_currency=False):
        """Получение информации о позициях

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param bool without_currency: Исключить из ответа все денежные инструменты, по умолчанию false
        """
        params = {'withoutCurrency': without_currency}
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/positions', params=params, headers=self.get_headers()))

    def get_position(self, portfolio, exchange, symbol):
        """Получение информации о позициях выбранного инструмента

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/positions/{symbol}', headers=self.get_headers()))

    def get_trades(self, portfolio, exchange):
        """Получение информации о сделках

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/trades', headers=self.get_headers()))

    def get_trade(self, portfolio, exchange, symbol):
        """Получение информации о сделках по выбранному инструменту

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/{symbol}/trades', headers=self.get_headers()))

    def get_forts_risk(self, portfolio, exchange):
        """Получение информации о рисках на срочном рынке

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/fortsrisk', headers=self.get_headers()))

    def get_risk(self, portfolio, exchange):
        """Получение информации о рисках

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/risk', headers=self.get_headers()))

    def get_trades_history(self, portfolio, exchange, date_from=None, id_from=None, limit=None, descending=None):
        """Получение истории сделок

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str date_from: Начиная с какой даты отдавать историю сделок. Например, '2021-10-13'
        :param int id_from: Начиная с какого ID (номера сделки) отдавать историю сделок
        :param int limit: Ограничение на количество выдаваемых результатов поиска
        :param bool descending: Флаг обратной сортировки выдачи
        """
        params = {}
        if date_from:
            params['dateFrom'] = date_from
        if id_from:
            params['from'] = id_from
        if limit:
            params['limit'] = limit
        if descending:
            params['descending'] = descending
        if params == {}:
            return self.check_result(get(url=f'{self.api_server}/md/stats/{exchange}/{portfolio}/history/trades', headers=self.get_headers()))
        return self.check_result(get(url=f'{self.api_server}/md/stats/{exchange}/{portfolio}/history/trades', params=params, headers=self.get_headers()))

    def get_trades_symbol(self, portfolio, exchange, symbol, date_from=None, id_from=None, limit=None, descending=None):
        """Получение истории сделок (один тикер)

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str date_from: Начиная с какой даты отдавать историю сделок. Например, '2021-10-13'
        :param int id_from: Начиная с какого ID (номера сделки) отдавать историю сделок
        :param int limit: Ограничение на количество выдаваемых результатов поиска
        :param bool descending: Флаг загрузки элементов с конца списка
        """
        params = {}
        if date_from:
            params['dateFrom'] = date_from
        if id_from:
            params['from'] = id_from
        if limit:
            params['limit'] = limit
        if descending:
            params['descending'] = descending
        if params == {}:
            return self.check_result(get(url=f'{self.api_server}/md/stats/{exchange}/{portfolio}/history/trades/{symbol}', headers=self.get_headers()))
        return self.check_result(get(url=f'{self.api_server}/md/stats/{exchange}/{portfolio}/history/trades/{symbol}', params=params, headers=self.get_headers()))

    # Instruments - Ценные бумаги / инструменты

    def get_securities(self, symbol, limit=None, offset=None, sector=None, cficode=None, exchange=None):
        """Получение информации о торговых инструментах

        :param str symbol: Маска тикера. Например SB выведет SBER, SBERP, SBRB ETF и пр.
        :param int limit: Ограничение на количество выдаваемых результатов поиска
        :param int offset: Смещение начала выборки (для пагинации)
        :param str sector: Рынок на бирже. FOND, FORTS, CURR
        :param str cficode: Код финансового инструмента по стандарту ISO 10962. EXXXXX
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        params = {'query': symbol}
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
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities', params=params, headers=self.get_headers()))

    def get_securities_exchange(self, exchange):
        """Получение информации о торговых инструментах на выбранной бирже

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}', headers=self.get_headers()))

    def get_symbol(self, exchange, symbol):
        """Получение информации о выбранном финансовом инструменте

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}/{symbol}', headers=self.get_headers()))

    def get_quotes(self, symbols):
        """Получение информации о котировках для выбранных инструментов

        :param str symbols: Принимает несколько пар биржа-тикер. Пары отделены запятыми. Биржа и тикер разделены двоеточием.
        Пример: MOEX:SBER,MOEX:GAZP,SPBX:AAPL
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{symbols}/quotes', headers=self.get_headers()))

    def get_order_book(self, exchange, symbol, depth=20):
        """Получение информации о биржевом стакане

        :param exchange: Биржа 'MOEX' или 'SPBX'
        :param symbol: Тикер
        :param depth: Глубина стакана. Стандартное и максимальное значение - 20 (20х20)
        """
        params = {'depth': depth}
        return self.check_result(get(url=f'{self.api_server}/md/v2/orderbooks/{exchange}/{symbol}', params=params, headers=self.get_headers()))

    def get_all_trades(self, exchange, symbol, seconds_from=None, seconds_to=None, id_from=None, id_to=None, take=None, descending=None):
        """Получение информации о всех сделках по ценным бумагам за сегодня

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param int seconds_from: Дата и время UTC в секундах для первой запрашиваемой сделки
        :param int seconds_to: Дата и время UTC в секундах для первой запрашиваемой сделки
        :param int id_from: Начальный номер сделки для фильтра результатов
        :param int id_to: Конечный номер сделки для фильтра результатов
        :param int take: Количество загружаемых элементов
        :param bool descending: Флаг загрузки элементов с конца списка
        """
        params = {}
        if seconds_from:
            params['from'] = seconds_from
        if seconds_to:
            params['to'] = seconds_to
        if id_from:
            params['fromId'] = id_from
        if id_to:
            params['toId'] = id_to
        if take:
            params['take'] = take
        if descending:
            params['descending'] = descending
        if params == {}:
            return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}/{symbol}/alltrades', headers=self.get_headers()))
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}/{symbol}/alltrades', params=params, headers=self.get_headers()))

    def get_all_trades_history(self, exchange, symbol, seconds_from=None, seconds_to=None, limit=50000, offset=None):
        """Получение исторической информации о всех сделках по ценным бумагам

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param int seconds_from: Начало отрезка времени UTC в секундах для фильтра результатов
        :param int seconds_to: Начало отрезка времени UTC в секундах для фильтра результатов
        :param int limit: Ограничение на количество выдаваемых результатов поиска (1-50000)
        :param int offset: Смещение начала выборки (для постраничного вывода)
        """
        params = {'limit': limit}
        if seconds_from:
            params['from'] = seconds_from
        if seconds_to:
            params['to'] = seconds_to
        if offset:
            params['offset'] = offset
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}/{symbol}/alltrades/history', params=params, headers=self.get_headers()))

    def get_actual_futures_quote(self, exchange, symbol):
        """Получение котировки по ближайшему фьючерсу (код)

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}/{symbol}/actualFuturesQuote', headers=self.get_headers()))

    def get_risk_rates(self, exchange, ticker=None, risk_category_id=None, search=None):
        """Запрос ставок риска

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str ticker: Тикер, код инструмента, ISIN для облигаций
        :param int risk_category_id: Id вашей (или той которая интересует) категории риска. Можно получить из запроса информации по клиенту или через кабинет клиента
        :param str search: Часть Тикера, кода инструмента, ISIN для облигаций. Вернет все совпадения, начинающиеся с
        """
        params = {'exchange': exchange}
        if ticker:
            params['ticker'] = ticker
        if risk_category_id:
            params['riskCategoryId'] = risk_category_id
        if search:
            params['search'] = search
        return self.check_result(get(url=f'{self.api_server}/md/v2/risk/rates', params=params, headers=self.get_headers()))

    def get_history(self, exchange, symbol, tf, seconds_from=1, seconds_to=32536799999, untraded=False):
        """Запрос истории рынка для выбранных биржи и финансового инструмента

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param int|str tf: Длительность временнОго интервала в секундах или код ("D" - дни, "W" - недели, "M" - месяцы, "Y" - годы)
        :param int seconds_from: Дата и время UTC в секундах для первого запрашиваемого бара
        :param int seconds_to: Дата и время UTC в секундах для последнего запрашиваемого бара
        :param bool untraded: Флаг для поиска данных по устаревшим или экспирированным инструментам. При использовании требуется точное совпадение тикера
        """
        # Если на from подаем точное время начала бара, то этот бар из Алор не передается. Возможно, проблема в том, что сервис Алора смотрит все даты >, а >= from
        # Временное решение, вычитать 1 секунду
        params = {'exchange': exchange, 'symbol': symbol, 'tf': tf, 'from': seconds_from - 1, 'to': seconds_to, 'untraded': untraded}
        return self.check_result(get(url=f'{self.api_server}/md/v2/history', params=params, headers=self.get_headers()))

    # Other - Другое

    def get_time(self):
        """Запрос текущего UTC времени в секундах на сервере
        Если этот запрос выполнен без авторизации, то будет возвращено время, которое было 15 минут назад
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/time', headers=self.get_headers()))

    # Orders Работа с заявками

    def get_orders(self, portfolio, exchange):
        """Получение информации о всех заявках

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/clients/{exchange}/{portfolio}/orders', headers=self.get_headers()))

    def get_order(self, portfolio, exchange, order_id):
        """Получение информации о выбранной заявке

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int order_id: Номер заявки на бирже
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/clients/{exchange}/{portfolio}/orders/{order_id}', headers=self.get_headers()))

    def create_market_order(self, portfolio, exchange, symbol, side, quantity):
        """Создание рыночной заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = f'{portfolio};{self.get_request_id()}'  # Портфель с уникальным идентификатором запроса
        j = {'side': side, 'type': 'market', 'quantity': abs(quantity), 'instrument': {'symbol': symbol, 'exchange': exchange}, 'user': {'portfolio': portfolio}}
        return self.check_result(post(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/market', headers=headers, json=j))

    def create_limit_order(self, portfolio, exchange, symbol, side, quantity, limit_price, time_in_force='GoodTillCancelled', iceberg_fixed=None, iceberg_variance=None):
        """Создание лимитной заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float limit_price: Лимитная цена
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = f'{portfolio};{self.get_request_id()}'  # Портфель с уникальным идентификатором запроса
        j = {'side': side, 'type': 'limit', 'quantity': abs(quantity), 'price': limit_price, 'instrument': {'symbol': symbol, 'exchange': exchange}, 'user': {'portfolio': portfolio}, 'timeInForce': time_in_force}
        if iceberg_fixed:
            j['icebergFixed'] = iceberg_fixed
        if iceberg_variance:
            j['icebergVariance'] = iceberg_variance
        return self.check_result(post(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/limit', headers=headers, json=j))

    def edit_market_order(self, account, portfolio, exchange, order_id, symbol, side, quantity):
        """Изменение рыночной заявки

        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int order_id: Номер заявки
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = f'{portfolio};{order_id};{quantity}'  # Портфель с уникальным идентификатором запроса и кол-вом в лотах
        j = {'side': side, 'type': 'market', 'id': order_id, 'quantity': abs(quantity), 'instrument': {'symbol': symbol, 'exchange': exchange}, 'user': {'account': account, 'portfolio': portfolio}}
        return self.check_result(put(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/market/{order_id}', headers=headers, json=j))

    def edit_limit_order(self, portfolio, exchange, order_id, symbol, side, quantity, limit_price, time_in_force='GoodTillCancelled', iceberg_fixed=None, iceberg_variance=None):
        """Изменение лимитной заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int order_id: Номер заявки
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float limit_price: Лимитная цена
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = f'{portfolio};{order_id};{quantity}'  # Портфель с уникальным идентификатором запроса и кол-вом в лотах
        j = {'side': side, 'type': 'limit', 'quantity': abs(quantity), 'price': limit_price, 'instrument': {'symbol': symbol, 'exchange': exchange}, 'user': {'portfolio': portfolio}, 'timeInForce': time_in_force}
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
        {'portfolio': portfolio, 'ticker': symbol, 'exchange': exchange, 'price': price, 'lotQuantity': quantity, 'board': board}
        """
        return self.check_result(post(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/estimate/all', json=orders))

    def delete_order(self, portfolio, exchange, order_id, stop=False):
        """Снятие заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int order_id: Номер заявки
        :param bool stop: Является ли стоп заявкой
        """
        headers = self.get_headers()
        headers['X-ALOR-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        params = {'portfolio': portfolio, 'exchange': exchange, 'stop': stop, 'jsonResponse': True, 'format': 'Simple'}
        return self.check_result(delete(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/{order_id}', headers=headers, params=params))

    # Subscriptions - Подписки и события (WebSocket)

    def order_book_get_and_subscribe(self, exchange, symbol, depth=20, frequency=0) -> str:
        """Подписка на информацию о биржевом стакане для выбранных биржи и финансового инструмента

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param int depth: Глубина стакана. Стандартное и максимальное значение - 20 (20х20)
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'OrderBookGetAndSubscribe', 'exchange': exchange, 'code': symbol, 'depth': depth, 'frequency': frequency, 'format': 'Simple'}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def bars_get_and_subscribe(self, exchange, symbol, tf, seconds_from, frequency=0) -> str:
        """Подписка на историю цен (свечи) для выбранных биржи и финансового инструмента

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param tf: Длительность временнОго интервала в секундах или код ("D" - дни, "W" - недели, "M" - месяцы, "Y" - годы)
        :param int seconds_from: Дата и время UTC в секундах для первого запрашиваемого бара
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'BarsGetAndSubscribe', 'exchange': exchange, 'code': symbol, 'tf': tf, 'from': int(seconds_from), 'delayed': False, 'frequency': frequency, 'format': 'Simple'}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def quotes_subscribe(self, exchange, symbol, frequency=0) -> str:
        """Подписка на информацию о котировках для выбранных инструментов и бирж

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'QuotesSubscribe', 'exchange': exchange, 'code': symbol, 'frequency': frequency, 'format': 'Simple'}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def all_trades_subscribe(self, exchange, symbol, depth=0, include_virtual_trades=False, frequency=0) -> str:
        """Подписка на информацию о всех сделках

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param int depth: Если указать, то перед актуальными данными придут данные о последних N сделках. Максимум 5000
        :param bool include_virtual_trades: Указывает, нужно ли отправлять виртуальные (индикативные) сделки
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'AllTradesGetAndSubscribe', 'code': symbol, 'exchange': exchange, 'depth': depth, 'includeVirtualTrades': include_virtual_trades, 'frequency': frequency, 'format': 'Simple'}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def positions_get_and_subscribe_v2(self, portfolio, exchange, frequency=0) -> str:
        """Подписка на информацию о текущих позициях по ценным бумагам и деньгам

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'PositionsGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'frequency': frequency, 'format': 'Simple'}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def summaries_get_and_subscribe_v2(self, portfolio, exchange, frequency=0) -> str:
        """Подписка на сводную информацию по портфелю

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'SummariesGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'frequency': frequency, 'format': 'Simple'}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def risks_get_and_subscribe(self, portfolio, exchange, frequency=0) -> str:
        """Подписка на сводную информацию по портфельным рискам

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'RisksGetAndSubscribe', 'exchange': exchange, 'portfolio': portfolio, 'frequency': frequency, 'format': 'Simple'}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def spectra_risks_get_and_subscribe(self, portfolio, exchange, frequency=0) -> str:
        """Подписка на информацию по рискам срочного рынка (FORTS)

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'SpectraRisksGetAndSubscribe', 'exchange': exchange, 'portfolio': portfolio, 'frequency': frequency, 'format': 'Simple'}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def trades_get_and_subscribe_v2(self, portfolio, exchange, frequency=0) -> str:
        """Подписка на информацию о сделках

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'TradesGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'frequency': frequency, 'format': 'Simple'}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def orders_get_and_subscribe_v2(self, portfolio, exchange, order_statuses=None, frequency=0) -> str:
        """Подписка на информацию о текущих заявках на рынке для выбранных биржи и финансового инструмента

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param list[str] order_statuses: Опциональный фильтр по статусам заявок. Влияет только на фильтрацию первичных исторических данных при подписке
        Статус исполнения. Пример: order_statuses=['filled', 'canceled']
            'working' - На исполнении
            'filled' - Исполнена
            'canceled' - Отменена
            'rejected' - Отклонена
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'OrdersGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'frequency': frequency, 'format': 'Simple'}  # Запрос на подписку
        if order_statuses:
            request['orderStatuses'] = order_statuses
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def instruments_get_and_subscribe_v2(self, exchange, symbol, frequency=0) -> str:
        """Подписка на изменение информации о финансовых инструментах на выбранной бирже

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'InstrumentsGetAndSubscribeV2', 'code': symbol, 'exchange': exchange, 'frequency': frequency, 'format': 'Simple'}  # Запрос на подписку
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

    def stop_orders_get_and_subscribe_v2(self, portfolio, exchange, frequency=0) -> str:
        """Подписка на информацию о текущих стоп заявках на рынке для выбранных биржи и финансового инструмента

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'StopOrdersGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'frequency': frequency, 'format': 'Simple'}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    # StopOrdersV2 - Стоп-заявки v2

    def get_stop_orders(self, portfolio, exchange):
        """Получение информации о стоп-заявках

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        return self.check_result(
            get(url=f'{self.api_server}/md/v2/clients/{exchange}/{portfolio}/stoporders', headers=self.get_headers()))

    def get_stop_order(self, portfolio, exchange, order_id):
        """Получение информации о выбранной стоп-заявке

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int order_id: Номер заявки на бирже
        """
        return self.check_result(
            get(url=f'{self.api_server}/md/v2/clients/{exchange}/{portfolio}/stoporders/{order_id}',
                headers=self.get_headers()))

    def create_stop_order(self, portfolio, exchange, symbol, class_code, side, quantity, stop_price, condition='Less', seconds_order_end=0, activate=True):
        """Создание стоп-заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str class_code: Класс инструмента
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param str condition: условие 'More' или 'Less'
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
        :param str condition: Условие 'More' или 'Less'
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
        :param str condition: Условие 'More' или 'Less'
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
        :param str condition: Условие 'More' или 'Less'
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

    def create_market_order_websocket(self, portfolio, exchange, board, symbol, side, quantity, check_duplicates=True):
        """Создание рыночной заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        """
        request = {'opcode': 'create:market', 'side': side, 'quantity': abs(quantity), 'instrument': {'exchange': exchange, 'symbol': symbol},
                   'board': board, 'user': {'portfolio': portfolio}, 'checkDuplicates': check_duplicates}
        return self.send_websocket(request)

    def create_limit_order_websocket(self, portfolio, exchange, board, symbol, side, quantity, limit_price, time_in_force='GoodTillCancelled', iceberg_fixed=None, iceberg_variance=None, check_duplicates=True):
        """Создание лимитной заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float limit_price: Лимитная цена
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        """
        request = {'opcode': 'create:limit', 'side': side, 'quantity': abs(quantity), 'price': limit_price, 'instrument': {'exchange': exchange, 'symbol': symbol},
                   'board': board, 'user': {'portfolio': portfolio}, 'timeInForce': time_in_force, 'checkDuplicates': check_duplicates}
        if iceberg_fixed:
            request['icebergFixed'] = iceberg_fixed
        if iceberg_variance:
            request['icebergVariance'] = iceberg_variance
        return self.send_websocket(request)

    def create_stop_order_websocket(self, portfolio, exchange, symbol, board, side, quantity, stop_price, condition='Less', seconds_order_end=0, check_duplicates=True, activate=True):
        """Создание стоп-заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param str condition: условие 'More' или 'Less'
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :param bool activate: Флаг активной заявки
        """
        request = {'opcode': 'create:stop', 'side': side, 'quantity': abs(quantity), 'condition': condition, 'triggerPrice': stop_price, 'stopEndUnixTime': seconds_order_end,
                   'instrument': {'symbol': symbol, 'exchange': exchange}, 'board': board, 'user': {'portfolio': portfolio, 'exchange': exchange},
                   'checkDuplicates': check_duplicates, 'activate': activate}
        return self.send_websocket(request)

    def create_stop_limit_order_websocket(self, portfolio, exchange, symbol, board, side, quantity, stop_price, limit_price, condition='Less', seconds_order_end=0,
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
        :param str condition: Условие 'More' или 'Less'
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :param bool activate: Флаг активной заявки
        """
        request = {'opcode': 'create:stopLimit', 'side': side, 'quantity': abs(quantity), 'price': limit_price, 'condition': condition, 'triggerPrice': stop_price, 'stopEndUnixTime': seconds_order_end,
                   'instrument': {'symbol': symbol, 'exchange': exchange}, 'board': board, 'user': {'portfolio': portfolio, 'exchange': exchange},
                   'timeInForce': time_in_force, 'checkDuplicates': check_duplicates, 'activate': activate}
        if iceberg_fixed:
            request['icebergFixed'] = iceberg_fixed
        if iceberg_variance:
            request['icebergVariance'] = iceberg_variance
        return self.send_websocket(request)

    def edit_market_order_websocket(self, order_id, portfolio, exchange, board, symbol, side, quantity, check_duplicates=True):
        """Изменение рыночной заявки

        :param int order_id: Номер заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        """
        request = {'opcode': 'update:market', 'orderId': order_id, 'side': side, 'quantity': abs(quantity),
                   'instrument': {'exchange': exchange, 'symbol': symbol}, 'board': board, 'user': {'portfolio': portfolio}, 'checkDuplicates': check_duplicates}
        return self.send_websocket(request)

    def edit_limit_order_websocket(self, order_id, portfolio, exchange, board, symbol, side, quantity, limit_price, time_in_force='GoodTillCancelled', iceberg_fixed=None, iceberg_variance=None, check_duplicates=True):
        """Изменение лимитной заявки

        :param int order_id: Номер заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float limit_price: Лимитная цена
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        """
        request = {'opcode': 'update:limit', 'orderId': order_id, 'side': side, 'quantity': abs(quantity), 'price': limit_price, 'instrument': {'exchange': exchange, 'symbol': symbol},
                   'board': board, 'user': {'portfolio': portfolio}, 'timeInForce': time_in_force, 'checkDuplicates': check_duplicates}
        if iceberg_fixed:
            request['icebergFixed'] = iceberg_fixed
        if iceberg_variance:
            request['icebergVariance'] = iceberg_variance
        return self.send_websocket(request)

    def edit_stop_order_websocket(self, order_id, portfolio, exchange, symbol, board, side, quantity, stop_price, condition='Less', seconds_order_end=0, check_duplicates=True, activate=True):
        """Изменение стоп-заявки

        :param int order_id: Номер заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stop_price: Стоп цена
        :param str condition: условие 'More' или 'Less'
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :param bool activate: Флаг активной заявки
        """
        request = {'opcode': 'update:stop', 'orderId': order_id, 'side': side, 'quantity': abs(quantity), 'condition': condition, 'triggerPrice': stop_price, 'stopEndUnixTime': seconds_order_end,
                   'instrument': {'symbol': symbol, 'exchange': exchange}, 'board': board, 'user': {'portfolio': portfolio, 'exchange': exchange},
                   'checkDuplicates': check_duplicates, 'activate': activate}
        return self.send_websocket(request)

    def edit_stop_limit_order_websocket(self, order_id, portfolio, exchange, symbol, board, side, quantity, stop_price, limit_price, condition='Less', seconds_order_end=0,
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
        :param str condition: Условие 'More' или 'Less'
        :param int seconds_order_end: Дата и время UTC в секундах завершения сделки
        :param str time_in_force: 'OneDay' - До конца дня, 'ImmediateOrCancel' - Снять остаток, 'FillOrKill' - Исполнить целиком или отклонить, 'GoodTillCancelled' - Активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :param bool activate: Флаг активной заявки
        """
        request = {'opcode': 'update:stopLimit', 'orderId': order_id, 'side': side, 'quantity': abs(quantity), 'price': limit_price, 'condition': condition, 'triggerPrice': stop_price, 'stopEndUnixTime': seconds_order_end,
                   'instrument': {'symbol': symbol, 'exchange': exchange}, 'board': board, 'user': {'portfolio': portfolio, 'exchange': exchange},
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

    def get_portfolios(self):
        """Получение списка серверов портфелей"""
        # TODO Перевести на декодирование base64 полей agreements и portfolios токена JWT
        return self.check_result(get(url=f'{self.api_server}/client/v1.0/users/{self.user_name}/portfolios', headers=self.get_headers()))

    def get_money(self, portfolio, exchange):
        """Получение информации по деньгам для выбранного портфеля

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/clients/legacy/{exchange}/{portfolio}/money', headers=self.get_headers()))

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

    # Запросы REST

    def get_jwt_token(self):
        """Получение, выдача, обновление JWT токена"""
        now = int(datetime.timestamp(datetime.now()))  # Текущая дата и время в виде UNIX времени в секундах
        if self.jwt_token is None or now - self.jwt_token_issued > self.jwt_token_ttl:  # Если токен JWT не был выдан или был просрочен
            response = post(url=f'{self.oauth_server}/refresh', params={'token': self.refresh_token})  # Запрашиваем новый JWT токен с сервера аутентификации
            if response.status_code != 200:  # Если при получении токена возникла ошибка
                self.OnError(f'Ошибка получения JWT токена: {response.status_code}')  # Событие ошибки
                self.jwt_token = None  # Сбрасываем токен JWT
                self.jwt_token_issued = 0  # Сбрасываем время выдачи токена JWT
            else:  # Токен получен
                token = response.json()  # Читаем данные JSON
                self.jwt_token = token.get('AccessToken')  # Получаем токен JWT
                self.jwt_token_issued = now  # Дата выдачи токена JWT
        return self.jwt_token

    def get_headers(self):
        """Получение хедеров для запросов"""
        return {'Content-Type': 'application/json', 'Authorization': f'Bearer {self.get_jwt_token()}'}

    def get_request_id(self):
        """Получение уникального кода запроса"""
        return f'{self.user_name}{time_ns()}'  # Логин и текущее время в наносекундах, прошедших с 01.01.1970 в UTC

    def check_result(self, response):
        """Анализ результата запроса

        :param response response: Результат запроса
        :return: Справочник из JSON, текст, None в случае веб ошибки
        """
        if response.status_code != 200:  # Если статус ошибки
            self.OnError(f'Ошибка сервера: {response.status_code} {response.content.decode("utf-8")} {response.request}')  # Событие ошибки
            return None  # то возвращаем пустое значение
        content = response.content.decode('utf-8')  # Значение
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
            self.OnError(f'Ошибка сервера: {http_code} {response["message"]}')  # Событие ошибки
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
            self.OnEntering()  # Событие начала входа (Thread)
            thread = Thread(target=run, args=(self.websocket_async(),))  # Создаем поток управления подписками
            # thread = Thread(target=self.loop.run_until_complete, args=(self.websocket_async(),))  # Создаем поток управления подписками
            thread.start()  # Запускаем его TODO Бывает ошибка cannot schedule new futures after shutdown
            # self.loop.create_task(self.websocket_async())
        while not self.ws_ready:  # Подключение к серверу WebSocket выполняется в отдельном потоке
            pass  # Подождем, пока WebSocket не будет готов принимать запросы
        guid = str(uuid4())  # Уникальный идентификатор подписки
        thread = Thread(target=run, args=(self.subscribe_async(request, guid),))  # Поток подписки
        thread.start()  # Запускаем
        thread.join()  # Ожидаем завершения
        return guid

    async def websocket_async(self):
        """Запуск и управление задачей подписок"""
        self.OnEnter()  # Событие входа (Thread)
        while True:  # Будем держать соединение с сервером WebSocket до отмены
            self.ws_task = create_task(self.websocket_handler())  # Запускаем задачу (Task) подключения к серверу WebSocket и получения с него подписок
            try:
                await self.ws_task  # Ожидаем отмены задачи
            except CancelledError:  # Если задачу отменили
                break  # то выходим, дальше не продолжаем
        self.OnExit()  # Событие выхода (Thread)

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
            self.OnConnect()  # Событие подключения к серверу (Task)

            if len(self.subscriptions) > 0:  # Если есть подписки, то будем их возобновлять
                self.OnResubscribe()  # Событие возобновления подписок (Task)
                for guid, request in self.subscriptions.items():  # Пробегаемся по всем подпискам
                    await self.subscribe_async(request, guid)  # Переподписываемся с тем же уникальным идентификатором
            self.ws_ready = True  # Готов принимать запросы
            self.OnReady()  # Событие готовности к работе (Task)

            while True:  # Получаем подписки до отмены
                response_json = await self.ws_socket.recv()  # Ожидаем следующую строку в виде JSON
                try:
                    response = loads(response_json)  # Переводим JSON в словарь
                except JSONDecodeError:  # Если вместо JSON сообщений получаем текст (проверка на всякий случай)
                    continue  # то его не разбираем, пропускаем
                if 'data' not in response:  # Если пришло сервисное сообщение о подписке/отписке
                    continue  # то его не разбираем, пропускаем
                guid = response['guid']  # GUID подписки
                if guid not in self.subscriptions:  # Если подписка не найдена
                    continue  # то мы не можем сказать, что это за подписка, пропускаем ее
                subscription = self.subscriptions[guid]  # Поиск подписки по GUID
                opcode = subscription['opcode']  # Разбираем по типу подписки
                if opcode == 'OrderBookGetAndSubscribe':  # Биржевой стакан
                    self.OnChangeOrderBook(response)
                elif opcode == 'BarsGetAndSubscribe':  # Новый бар
                    seconds = response['data']['time']  # Время пришедшего бара
                    if subscription['mode'] == 0:  # История
                        if seconds != subscription['last']:  # Если пришел следующий бар истории
                            subscription['last'] = seconds  # то запоминаем его
                            if subscription['prev'] is not None:  # Мы не знаем, когда придет первый дубль
                                self.OnNewBar(subscription['prev'])  # Поэтому, выдаем бар с задержкой на 1
                        else:  # Если пришел дубль
                            subscription['same'] = 2  # Есть 2 одинаковых бара
                            subscription['mode'] = 1  # Переходим к обработке первого несформированного бара
                    elif subscription['mode'] == 1:  # Первый несформированный бар
                        if subscription['same'] < 3:  # Если уже есть 2 одинаковых бара
                            subscription['same'] += 1  # то следующий бар будет таким же. 3 одинаковых бара
                        else:  # Если пришел следующий бар
                            subscription['last'] = seconds  # то запоминаем бар
                            subscription['same'] = 1  # Повторов нет
                            subscription['mode'] = 2  # Переходим к обработке новых баров
                            self.OnNewBar(subscription['prev'])
                    elif subscription['mode'] == 2:  # Новый бар
                        if subscription['same'] < 2:  # Если нет повторов
                            subscription['same'] += 1  # то следующий бар будет таким же. 2 одинаковых бара
                        else:  # Если пришел следующий бар
                            subscription['last'] = seconds  # то запоминаем бар
                            subscription['same'] = 1  # Повторов нет
                            self.OnNewBar(subscription['prev'])
                    subscription['prev'] = response  # Запоминаем пришедший бар
                elif opcode == 'QuotesSubscribe':  # Котировки
                    self.OnNewQuotes(response)
                elif opcode == 'AllTradesGetAndSubscribe':  # Все сделки
                    self.OnAllTrades(response)
                elif opcode == 'PositionsGetAndSubscribeV2':  # Позиции по ценным бумагам и деньгам
                    self.OnPosition(response)
                elif opcode == 'SummariesGetAndSubscribeV2':  # Сводная информация по портфелю
                    self.OnSummary(response)
                elif opcode == 'RisksGetAndSubscribe':  # Портфельные риски
                    self.OnRisk(response)
                elif opcode == 'SpectraRisksGetAndSubscribe':  # Риски срочного рынка (FORTS)
                    self.OnSpectraRisk(response)
                elif opcode == 'TradesGetAndSubscribeV2':  # Сделки
                    self.OnTrade(response)
                elif opcode == 'StopOrdersGetAndSubscribe':  # Стоп заявки
                    self.OnStopOrder(response)
                elif opcode == 'StopOrdersGetAndSubscribeV2':  # Стоп заявки v2
                    self.OnStopOrderV2(response)
                elif opcode == 'OrdersGetAndSubscribeV2':  # Заявки
                    self.OnOrder(response)
                elif opcode == 'InstrumentsGetAndSubscribeV2':  # Информация о финансовых инструментах
                    self.OnSymbol(response)
        except CancelledError:  # Задачу отменили
            self.OnCancel()  # Событие отмены и завершения (Task)
            raise  # Передаем исключение на родительский уровень WebSocketHandler
        except ConnectionClosed:  # Отключились от сервера WebSockets
            self.OnDisconnect()  # Событие отключения от сервера (Task)
        except (OSError, TimeoutError, MaxRetryError):  # При системной ошибке, таймауте на websockets, достижении максимального кол-ва попыток подключения
            self.OnTimeout()  # Событие таймаута/максимального кол-ва попыток подключения (Task)
        except Exception as ex:  # При других типах ошибок
            self.OnError(f'Ошибка {ex}')  # Событие ошибки (Task)
        finally:
            self.ws_ready = False  # Не готов принимать запросы
            self.ws_socket = None  # Сбрасываем подключение

    async def subscribe_async(self, request, guid):
        """Отправка запроса подписки на сервер WebSocket

        :param request: Запрос
        :param str guid: Уникальный идентификатор подписки
        :return: Справочник из JSON, текст, None в случае веб ошибки
        """
        subscription_request = request.copy()  # Копируем запрос в подписку
        if subscription_request['opcode'] == 'BarsGetAndSubscribe':  # Для подписки на новые бары добавляем дополнительные атрибуты и их значения по умолчанию
            subscription_request['mode'] = 0  # 0 - история, 1 - первый несформированный бар, 2 - новый бар
            subscription_request['last'] = 0  # Время последнего бара
            subscription_request['same'] = 1  # Кол-во повторяющихся баров
            subscription_request['prev'] = None  # Дата и время предыдущего бара UTC в секундах
        self.subscriptions[guid] = subscription_request  # Заносим копию подписки в справочник
        request['token'] = self.get_jwt_token()  # Получаем JWT токен, ставим его в запрос
        request['guid'] = guid  # Уникальный идентификатор подписки тоже ставим в запрос
        await self.ws_socket.send(dumps(request))  # Отправляем запрос

    # Функции конвертации

    def get_symbol_info(self, exchange, symbol, reload=False):
        """Получение информации тикера

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param bool reload: Получить информацию из Алор
        :return: Значение из кэша/Алор или None, если тикер не найден
        """
        if reload or (exchange, symbol) not in self.symbols:  # Если нужно получить информацию из Алор или нет информации о тикере в справочнике
            symbol_info = self.get_symbol(exchange, symbol)  # Получаем информацию о тикере из Алор
            if not symbol_info:  # Если тикер не найден
                print(f'Информация о {exchange}.{symbol} не найдена')
                return None  # то возвращаем пустое значение
            self.symbols[(exchange, symbol)] = symbol_info  # Заносим информацию о тикере в справочник
        return self.symbols[(exchange, symbol)]  # Возвращаем значение из справочника

    @staticmethod
    def dataname_to_exchange_symbol(dataname) -> tuple[str, str]:
        """Биржа и код тикера из названия тикера. Если задается без биржи, то по умолчанию ставится MOEX

        :param str dataname: Название тикера
        :return: Код площадки и код тикера
        """
        symbol_parts = dataname.split('.')  # По разделителю пытаемся разбить тикер на части
        if len(symbol_parts) >= 2:  # Если тикер задан в формате <Биржа>.<Код тикера>
            exchange = symbol_parts[0]  # Биржа
            symbol = '.'.join(symbol_parts[1:])  # Код тикера
        else:  # Если тикер задан без биржи
            exchange = 'MOEX'  # Биржа по умолчанию
            symbol = dataname  # Код тикера
        return exchange, symbol  # Возвращаем биржу и код тикера

    @staticmethod
    def exchange_symbol_to_dataname(exchange, symbol) -> str:
        """Название тикера из биржи и кода тикера

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :return: Название тикера
        """
        return f'{exchange}.{symbol}'

    def price_to_alor_price(self, exchange, symbol, price) -> float:
        """Перевод цены в цену Алор

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param float price: Цена
        :return: Цена в Алор
        """
        si = self.get_symbol_info(exchange, symbol)  # Информация о тикере
        primary_board = si['primary_board']  # Рынок тикера
        if primary_board == 'TQOB':  # Для рынка облигаций
            price /= 10  # цену делим на 10
        min_step = si['minstep']  # Минимальный шаг цены
        decimals = int(log10(1 / min_step) + 0.99)  # Из шага цены получаем кол-во десятичных знаков
        return round(price, decimals)  # Округляем цену

    def alor_price_to_price(self, exchange, symbol, price) -> float:
        """Перевод цены Алор в цену

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param float price: Цена в Алор
        :return: Цена
        """
        si = self.get_symbol_info(exchange, symbol)  # Информация о тикере
        primary_board = si['primary_board']  # Рынок тикера
        if primary_board == 'TQOB':  # Для рынка облигаций
            price *= 10  # цену умножаем на 10
        return price

    def utc_timestamp_to_msk_datetime(self, seconds) -> datetime:
        """Перевод кол-ва секунд, прошедших с 01.01.1970 00:00 UTC в московское время

        :param int seconds: Кол-во секунд, прошедших с 01.01.1970 00:00 UTC
        :return: Московское время без временнОй зоны
        """
        dt_utc = datetime.utcfromtimestamp(seconds)  # Переводим кол-во секунд, прошедших с 01.01.1970 в UTC
        return self.utc_to_msk_datetime(dt_utc)  # Переводим время из UTC в московское

    def msk_datetime_to_utc_timestamp(self, dt) -> int:
        """Перевод московского времени в кол-во секунд, прошедших с 01.01.1970 00:00 UTC

        :param datetime dt: Московское время
        :return: Кол-во секунд, прошедших с 01.01.1970 00:00 UTC
        """
        dt_msk = self.tz_msk.localize(dt)  # Заданное время ставим в зону МСК
        return int(dt_msk.timestamp())  # Переводим в кол-во секунд, прошедших с 01.01.1970 в UTC

    def utc_to_msk_datetime(self, dt, tzinfo=False) -> datetime:
        """Перевод времени из UTC в московское

        :param datetime dt: Время UTC
        :param bool tzinfo: Отображать временнУю зону
        :return: Московское время
        """
        dt_utc = utc.localize(dt)  # Задаем временнУю зону UTC
        dt_msk = dt_utc.astimezone(self.tz_msk)  # Переводим в МСК
        return dt_msk if tzinfo else dt_msk.replace(tzinfo=None)
