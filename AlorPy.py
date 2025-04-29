import logging  # Будем вести лог
from typing import Union, Any  # Объединение типов, любой тип
from math import log10  # Кол-во десятичных знаков будем получать из шага цены через десятичный логарифм
from datetime import datetime
from time import time_ns  # Текущее время в наносекундах, прошедших с 01.01.1970 UTC
from uuid import uuid4  # Номера подписок должны быть уникальными во времени и пространстве
from json import loads, JSONDecodeError, dumps  # Сервер WebSockets работает с JSON сообщениями
from asyncio import get_event_loop, create_task, run, CancelledError  # Работа с асинхронными функциями
from threading import Thread  # Подписки сервера WebSockets будем получать в отдельном потоке

from pytz import timezone, utc  # Работаем с временнОй зоной и UTC
import requests.adapters  # Настройки запросов/ответов
from requests import post, get, put, delete, Response  # Запросы/ответы от сервера запросов
from jwt import decode  # Декодирование токена JWT для получения договоров и портфелей
from urllib3.exceptions import MaxRetryError  # Соединение с сервером не установлено за максимальное кол-во попыток подключения
from websockets import connect, ConnectionClosed  # Работа с сервером WebSockets

from AlorPy import Config  # Файл конфигурации


# noinspection PyShadowingBuiltins
class AlorPy:
    """Работа с Alor OpenAPI V2 https://alor.dev/docs из Python"""
    requests.adapters.DEFAULT_RETRIES = 10  # Настройка кол-ва попыток
    requests.adapters.DEFAULT_POOL_TIMEOUT = 10  # Настройка таймаута запроса в секундах
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
        self.on_entering = lambda: self.logger.debug(f'WebSocket Thread: Запуск')  # Начало входа (Thread)
        self.on_enter = lambda: self.logger.debug(f'WebSocket Thread: Запущен')  # Вход (Thread)
        self.on_connect = lambda: self.logger.debug(f'WebSocket Task: Подключен к серверу')  # Подключение к серверу (Task)
        self.on_resubscribe = lambda: self.logger.debug(f'WebSocket Task: Возобновление подписок ({len(self.subscriptions)})')  # Возобновление подписок (Task)
        self.on_ready = lambda: self.logger.debug(f'WebSocket Task: Готов')  # Готовность к работе (Task)
        self.on_disconnect = lambda: self.logger.debug(f'WebSocket Task: Отключен от сервера')  # Отключение от сервера (Task)
        self.on_timeout = lambda: self.logger.debug(f'WebSocket Task: Таймаут')  # Таймаут/максимальное кол-во попыток подключения (Task)
        self.on_error = lambda response: self.logger.debug(f'WebSocket Task: {response}')  # Ошибка (Task)
        self.on_cancel = lambda: self.logger.debug(f'WebSocket Task: Отмена')  # Отмена (Task)
        self.on_exit = lambda: self.logger.debug(f'WebSocket Thread: Завершение')  # Выход (Thread)

        self.refresh_token = refresh_token  # Токен
        self.jwt_token = None  # Токен JWT
        self.jwt_token_decoded = dict()  # Информация по портфелям
        self.jwt_token_issued = 0  # UNIX время в секундах выдачи токена JWT
        self.accounts = list()  # Счета (портфели по договорам)
        self.get_jwt_token()  # Получаем токен JWT
        if self.jwt_token_decoded:
            all_agreements = self.jwt_token_decoded['agreements'].split(' ')  # Все договоры
            all_portfolios = self.jwt_token_decoded['portfolios'].split(' ')  # Все портфели. К каждому договору привязаны 3 портфеля
            account_id = portfolio_id = 0  # Начальная позиция договоров и портфелей
            for agreement in all_agreements:  # Пробегаемся по всем договорам
                for portfolio in all_portfolios[portfolio_id:portfolio_id + 3]:  # Пробегаемся по 3-м портфелям каждого договора
                    if portfolio.startswith('D'):  # Портфель счета фондового рынка начинается с D и имеет формат D12345
                        type = 'securities'  # Тип счета
                        exchanges = self.exchanges  # Все биржи
                        boards = ('TQRD', 'TQOY', 'TQIF', 'TQBR', 'MTQR', 'TQOB', 'TQIR', 'EQRP_INFO', 'TQTF', 'FQDE', 'INDX', 'TQOD', 'FQBR', 'TQCB', 'TQPI', 'TQBD')  # Режимы торгов
                    elif portfolio.startswith('G'):  # Портфель валютного счета начинается с G и имеет формат G12345
                        type = 'fx'  # Тип счета
                        exchanges = (self.exchanges[0],)  # Биржа MOEX
                        boards = ('CETS_SU', 'INDXC', 'CETS')  # Режимы торгов
                    elif portfolio.startswith('750'):  # Портфель счета срочного рынка начинается с 750 и имеет формат 750****
                        type = 'derivatives'  # Тип счета
                        exchanges = (self.exchanges[0],)  # Биржа MOEX
                        boards = ('SPBOPT', 'OPTCOMDTY', 'OPTSPOT', 'SPBFUT', 'OPTCURNCY', 'RFUD', 'ROPD')  # Режимы торгов RFUD=SBPFUT, ROPD=SPBOPT
                    else:  # Неизвестный портфель
                        logging.warning(f'Не определен тип счета для договора {agreement}, портфеля {portfolio}')
                        continue  # Переходим к следующему портфелю, дальше не продолжаем
                    self.accounts.append(dict(account_id=account_id, agreement=agreement, portfolio=portfolio, type=type, exchanges=exchanges, boards=boards))  # Добавляем договор/портфель/биржи/режимы торгов
                account_id += 1  # Смещаем на следующий договор
                portfolio_id += 3  # Смещаем на начальную позицию портфелей для следующего договора
        self.subscriptions = {}  # Справочник подписок. Для возобновления всех подписок после перезагрузки сервера Алор
        self.symbols = {}  # Справочник тикеров

    def __enter__(self):
        """Вход в класс, например, с with"""
        return self

    # Авторизация

    def get_jwt_token(self):  # https://alor.dev/docs/api/http/jwt-token
        """JWT token
        :return: JWT токен, использующийся в качестве токена доступа при авторизации запросов к остальным ресурсам API
        """
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

    # О клиенте

    def get_orders(self, portfolio, exchange, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-clients-exchange-portfolio-orders-get
        """Все биржевые заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает информацию обо всех биржевых заявках с участием указанного портфеля
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/clients/{exchange}/{portfolio}/orders', params=params, headers=self.get_headers()))

    def get_order(self, portfolio, exchange, order_id, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-clients-exchange-portfolio-orders-order-id-get
        """Выбранная биржевая заявка

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param int order_id: Идентификатор заявки
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает информацию об определённой биржевой заявке
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/clients/{exchange}/{portfolio}/orders/{order_id}', params=params, headers=self.get_headers()))

    def get_stop_orders(self, portfolio, exchange, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-clients-exchange-portfolio-stop-orders-get
        """Все условные заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает информацию обо всех стоп-заявках с участием указанного портфеля
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/clients/{exchange}/{portfolio}/stoporders', params=params, headers=self.get_headers()))

    def get_stop_order(self, portfolio, exchange, order_id, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-clients-exchange-portfolio-stop-orders-order-id-get
        """Выбранная условная заявка

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param int order_id: Идентификатор заявки
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает информацию об определённой стоп-заявке
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/clients/{exchange}/{portfolio}/stoporders/{order_id}', params=params, headers=self.get_headers()))

    def get_portfolio_summary(self, portfolio, exchange, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-clients-exchange-portfolio-summary-get
        """Сводная информация о портфеле

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает сводную информацию об указанном портфеле
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/clients/{exchange}/{portfolio}/summary', params=params, headers=self.get_headers()))

    def get_positions(self, portfolio, exchange, without_currency=False, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-clients-exchange-portfolio-positions-get
        """Позиции в портфеле (Все)

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param bool without_currency: Исключить из ответа все денежные инструменты
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает информацию о наличии и свойствах позиций финансовых и валютных инструментов в указанном портфеле
        """
        params = {'withoutCurrency': without_currency, 'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/positions', params=params, headers=self.get_headers()))

    def get_position(self, portfolio, exchange, symbol, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-clients-exchange-portfolio-positions-symbol-get
        """Позиции в портфеле (По инструменту)

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает информацию обо всех открытых позициях выбранного инструмента в указанном портфеле
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/positions/{symbol}', params=params, headers=self.get_headers()))

    def get_trades(self, portfolio, exchange, with_repo=None, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-clients-exchange-portfolio-trades-get
        """Сделки по портфелю (Все | Текущая сессия)

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param bool with_repo: Флаг отображения заявок с РЕПО
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает информацию обо всех сделках с участием указанного в portfolio портфеля за текущую торговую сессию
        """
        params: dict[str, Any] = {'format': format}
        if with_repo: params['withRepo'] = with_repo
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/trades', params=params, headers=self.get_headers()))

    def get_trade(self, portfolio, exchange, symbol, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-clients-exchange-portfolio-symbol-trades-get
        """Сделки по портфелю (Инструмент | Текущая сессия)

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает информацию обо всех сделках с участием указанного в portfolio портфеля по указанному в symbol финансовому инструменту за текущую торговую сессию
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/{symbol}/trades', params=params, headers=self.get_headers()))

    def get_forts_risk(self, portfolio, exchange, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-clients-exchange-portfolio-fortsrisk-get
        """Риски на срочном рынке

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает информацию по рискам срочного рынка (FORTS) для указанного портфеля
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/fortsrisk', params=params, headers=self.get_headers()))

    def get_risk(self, portfolio, exchange, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-clients-exchange-portfolio-risk-get
        """Все риски

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает сводную информацию по портфельным рискам для указанного портфеля
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{exchange}/{portfolio}/risk', params=params, headers=self.get_headers()))

    def get_login_positions(self, login, without_currency=None, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-clients-login-positions-get
        """Все позиции для выбранного логина

        :param str login: Логин торгового аккаунта
        :param bool without_currency: Исключить из ответа все денежные инструменты
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает информацию обо всех позициях во всех портфелях указанного в параметре login торгового аккаунта
        """
        params: dict[str, Any] = {'format': format}
        if without_currency: params['withoutCurrency'] = without_currency
        return self.check_result(get(url=f'{self.api_server}/md/v2/Clients/{login}/positions', params=params, headers=self.get_headers()))

    def get_trades_history_v2(self, portfolio, exchange, instrument_group=None, date_from=None, ticker=None, id_from=None,
                              limit=None, order_by_trade_date=None, descending=None, with_repo=None, side=None, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-stats-exchange-portfolio-history-trades-get
        """Сделки по портфелю (Все | Прошлые сессии)

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str instrument_group: Код режима торгов
        :param str date_from: Начиная с какой даты отдавать историю сделок. Например, '2021-10-13
        :param str ticker: Тикер/код инструмента. ISIN для облигаций
        :param int id_from: Начальный номер сделки для фильтра результатов
        :param int limit: Количество возвращаемых записей (1-1000)
        :param bool order_by_trade_date: Флаг сортировки возвращаемых результатов по дате совершения сделки
        :param bool descending: Флаг обратной сортировки выдачи
        :param bool with_repo: Флаг отображения заявок с РЕПО
        :param str side: Направление сделки: 'buy' - Покупка, 'sell' - Продажа
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает информацию обо всех сделках с участием указанного в portfolio портфеля за прошлые торговые сессии
        """
        params: dict[str, Any] = {'format': format}
        if instrument_group: params['instrumentGroup'] = instrument_group
        if date_from: params['dateFrom'] = date_from
        if ticker: params['ticker'] = ticker
        if id_from: params['from'] = id_from
        if limit: params['limit'] = limit
        if order_by_trade_date: params['orderByTradeDate'] = order_by_trade_date
        if descending: params['descending'] = descending
        if with_repo: params['withRepo'] = with_repo
        if side: params['side'] = side
        return self.check_result(get(url=f'{self.api_server}/md/v2/Stats/{exchange}/{portfolio}/history/trades', params=params, headers=self.get_headers()))

    def get_trades_symbol_v2(self, portfolio, exchange, symbol, instrument_group=None, date_from=None, id_from=None,
                             limit=None, order_by_trade_date=None, descending=None, with_repo=None, side=None, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-stats-exchange-portfolio-history-trades-symbol-get
        """Сделки по портфелю (Инструмент | Прошлые сессии)

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str instrument_group: Код режима торгов
        :param str date_from: Начиная с какой даты отдавать историю сделок. Например, '2021-10-13'
        :param int id_from: Начиная с какого ID (номера сделки) отдавать историю сделок
        :param int limit: Ограничение на количество выдаваемых результатов поиска
        :param bool order_by_trade_date: Флаг сортировки возвращаемых результатов по дате совершения сделки
        :param bool descending: Флаг загрузки элементов с конца списка
        :param bool with_repo: Флаг отображения заявок с РЕПО
        :param str side: Направление сделки: 'buy' - Покупка, 'sell' - Продажа
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает информацию обо всех сделках с участием указанного в portfolio портфеля по указанному в symbol финансовому инструменту за прошлые торговые сессии
        """
        params: dict[str, Any] = {'format': format}
        if instrument_group: params['instrumentGroup'] = instrument_group
        if date_from: params['dateFrom'] = date_from
        if id_from: params['from'] = id_from
        if limit: params['limit'] = limit
        if order_by_trade_date: params['orderByTradeDate'] = order_by_trade_date
        if descending: params['descending'] = descending
        if with_repo: params['withRepo'] = with_repo
        if side: params['side'] = side
        return self.check_result(get(url=f'{self.api_server}/md/v2/Stats/{exchange}/{portfolio}/history/trades/{symbol}', params=params, headers=self.get_headers()))

    # Об инструменте

    def get_securities(self, symbol=None, limit=None, offset=None, sector=None, cficode=None, exchange=None, instrument_group=None, include_non_base_boards=None, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-securities-get
        """Все торговые инструменты

        :param str symbol: Тикер
        :param int limit: Ограничение на количество выдаваемых результатов поиска. По умолчанию 25
        :param int offset: Смещение начала выборки (для пагинации)
        :param str sector: Рынок на бирже. 'FOND', 'FORTS', 'CURR'
        :param str cficode: Код финансового инструмента по стандарту ISO 10962. EXXXXX
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа:
        :param str instrument_group: Код режима торгов
        :param str include_non_base_boards: Флаг выгрузки инструментов для всех режимов торгов, включая отличающиеся от установленного для инструмента значения параметра
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает информацию о соответствующих запросу торговых инструментах на всех биржах. Объекты в ответе сортируются по объёму торгов в очерёдности "Сначала объёмные"
        """
        params: dict[str, Any] = {'format': format}
        if symbol: params['query'] = symbol
        if limit: params['limit'] = limit
        if offset: params['offset'] = offset
        if sector: params['sector'] = sector
        if cficode: params['cficode'] = cficode
        if exchange: params['exchange'] = exchange
        if instrument_group: params['instrumentGroup'] = instrument_group
        if include_non_base_boards: params['includeNonBaseBoards'] = include_non_base_boards
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities', params=params, headers=self.get_headers()))

    def get_securities_exchange(self, exchange, market=None, include_old=None, limit=None, include_non_base_boards=None, offset=None, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-securities-exchange-get
        """Все торговые инструменты выбранной биржи

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str market: Рынок на бирже. FOND, FORTS, CURR
        :param bool include_old: Флаг загрузки устаревших инструментов
        :param int limit: Ограничение на количество выдаваемых результатов поиска
        :param str include_non_base_boards: Флаг выгрузки инструментов для всех режимов торгов, включая отличающиеся от установленного для инструмента значения параметра
        :param int offset: Смещение начала выборки (для пагинации)
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает информацию о соответствующих запросу торговых инструментах на выбранной бирже. Объекты в ответе сортируются по объёму торгов в очерёдности "Сначала объёмные"
        """
        params: dict[str, Any] = {'format': format}
        if market: params['market'] = market
        if include_old: params['includeOld'] = include_old
        if limit: params['limit'] = limit
        if include_non_base_boards: params['includeNonBaseBoards'] = include_non_base_boards
        if offset: params['offset'] = offset
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}', params=params, headers=self.get_headers()))

    def get_symbol(self, exchange, symbol, instrument_group=None, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-securities-exchange-symbol-get
        """Выбранный торговый инструмент

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str instrument_group: Код режима торгов
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает полную информацию об указанном финансовом инструменте на выбранной бирже
        """
        params = {'format': format}
        if instrument_group: params['instrumentGroup'] = instrument_group
        result: dict = self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}/{symbol}', params=params, headers=self.get_headers()))  # Результат в виде словаря
        result['decimals'] = int(log10(1 / result['minstep']) + 0.99)  # Кол-во десятичных знаков получаем из шага цены, добавляем в полученный словарь
        return result

    def get_available_boards(self, exchange, symbol):  # https://alor.dev/docs/api/http/md-v-2-securities-exchange-symbol-available-boards-get
        """Режимы торгов выбранного инструмента

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :return: Запрос возвращает список всех кодов режимов торгов, в которых представлен выбранный финансовый инструмент
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}/{symbol}/availableBoards', headers=self.get_headers()))

    def get_all_trades(self, exchange, symbol,
                       instrument_group=None, seconds_from=None, seconds_to=None, id_from=None, id_to=None, qty_from=None, qty_to=None, price_from=None, price_to=None,
                       side=None, offset=None, take=None, descending=None, include_virtual_trades=None, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-securities-exchange-symbol-alltrades-get
        """Сделки по инструменту (Текущая сессия)

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str instrument_group: Код режима торгов
        :param int seconds_from: Начало отрезка времени (UTC) для фильтра результатов в формате Unix Time Seconds
        :param int seconds_to: Конец отрезка времени (UTC) для фильтра результатов в формате Unix Time Seconds
        :param int id_from: Начальный номер сделки для фильтра результатов
        :param int id_to: Конечный номер сделки для фильтра результатов
        :param int qty_from: Нижняя граница объёма сделки в лотах
        :param int qty_to: Верхняя граница объёма сделки в лотах
        :param float price_from: Нижняя граница цены, по которой была совершена сделка
        :param float price_to: Верхняя граница цены, по которой была совершена сделка
        :param str side: Направление сделки: 'buy' - Покупка, 'sell' - Продажа
        :param int offset: Смещение начала выборки (для пагинации)
        :param int take: Количество загружаемых элементов
        :param bool descending: Флаг обратной сортировки выдачи
        :param bool include_virtual_trades: Флаг загрузки виртуальных (индикативных) сделок, полученных из заявок на питерской бирже
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает обезличенную информацию обо всех сделках с участием указанного в symbol инструмента, совершённых всеми участниками торгов за текущую торговую сессию
        """
        params: dict[str, Any] = {'format': format}
        if instrument_group: params['instrumentGroup'] = instrument_group
        if seconds_from: params['from'] = seconds_from
        if seconds_to: params['to'] = seconds_to
        if id_from: params['fromId'] = id_from
        if id_to: params['toId'] = id_to
        if qty_from: params['qtyFrom'] = qty_from
        if qty_to: params['qtyTo'] = qty_to
        if price_from: params['priceFrom'] = price_from
        if price_to: params['priceTo'] = price_to
        if side: params['side'] = side
        if offset: params['offset'] = offset
        if take: params['take'] = take
        if descending: params['descending'] = descending
        if include_virtual_trades: params['includeVirtualTrades'] = include_virtual_trades
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}/{symbol}/alltrades', params=params, headers=self.get_headers()))

    def get_all_trades_history(self, exchange, symbol, instrument_group=None, seconds_from=None, seconds_to=None, limit=50000, offset=None, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-securities-exchange-symbol-alltrades-history-get
        """Сделки по инструменту (Прошлые сессии)

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str instrument_group: Код режима торгов
        :param int seconds_from: Начало отрезка времени (UTC) для фильтра результатов в формате Unix Time Seconds
        :param int seconds_to: Конец отрезка времени (UTC) для фильтра результатов в формате Unix Time Seconds
        :param int limit: Ограничение на количество выдаваемых результатов поиска (1-50000)
        :param int offset: Смещение начала выборки (для пагинации)
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает обезличенную информацию обо всех сделках с участием указанного в symbol инструмента, совершённых всеми участниками торгов за прошлые торговые сессии
        """
        params = {'limit': limit, 'format': format}
        if instrument_group: params['instrumentGroup'] = instrument_group
        if seconds_from: params['from'] = seconds_from
        if seconds_to: params['to'] = seconds_to
        if offset: params['offset'] = offset
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}/{symbol}/alltrades/history', params=params, headers=self.get_headers()))

    def get_actual_futures_quote(self, exchange, symbol, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-securities-exchange-symbol-actual-futures-quote-get
        """Котировки по ближайшему фьючерсу (код)

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает информацию о текущем активном фьючерсе с ближайшей датой экспирации
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{exchange}/{symbol}/actualFuturesQuote', params=params, headers=self.get_headers()))

    def get_quotes(self, symbols, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-securities-symbols-quotes-get
        """Котировки для выбранных инструментов

        :param str symbols: Принимает несколько пар биржа-тикер. Пары отделены запятыми. Биржа и тикер разделены двоеточием. Пример: MOEX:SBER,MOEX:GAZP,SPBX:AAPL
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает информацию о котировках для выбранного финансового инструмента на указанной бирже
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/{symbols}/quotes', params=params, headers=self.get_headers()))

    def get_currency_pairs(self, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-securities-currency-pairs-get
        """Валютные пары

        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает список всех доступных валютных пар
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/Securities/currencyPairs', params=params, headers=self.get_headers()))

    def get_order_book(self, exchange, symbol, instrument_group=None, depth=None, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-orderbooks-exchange-symbol-get
        """Биржевой стакан

        :param exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str instrument_group: Код режима торгов
        :param int depth: Глубина стакана. Стандартное значение — 20 (20х20), максимальное — 50 (50х50)
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает информацию о текущем количестве лотов и их цене в бидах и асках биржевого стакана для указанного финансового инструмента
        """
        params: dict[str, Any] = {'format': format}
        if depth: params['depth'] = depth
        if instrument_group: params['instrumentGroup'] = instrument_group
        return self.check_result(get(url=f'{self.api_server}/md/v2/orderbooks/{exchange}/{symbol}', params=params, headers=self.get_headers()))

    def get_risk_rates(self, exchange, ticker=None, risk_category_id=None, search=None, limit=None, offset=None):  # https://alor.dev/docs/api/http/md-v-2-risk-rates-get
        """Ставки риска

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str ticker: Тикер, код инструмента, ISIN для облигаций
        :param int risk_category_id: Id вашей (или той которая интересует) категории риска. Можно получить из запроса информации по клиенту или через кабинет клиента
        :param str search: Часть Тикера, кода инструмента, ISIN для облигаций. Вернет все совпадения, начинающиеся с
        :param int limit: Ограничение на количество выдаваемых результатов поиска
        :param int offset: Смещение начала выборки (для пагинации)
        :return: Запрос возвращает текущие значения ставок риска для маржинальной торговли
        """
        params: dict[str, Any] = {'exchange': exchange}
        if ticker: params['ticker'] = ticker
        if risk_category_id: params['riskCategoryId'] = risk_category_id
        if search: params['search'] = search
        if limit: params['limit'] = limit
        if offset: params['offset'] = offset
        return self.check_result(get(url=f'{self.api_server}/md/v2/risk/rates', params=params, headers=self.get_headers()))

    def get_history(self, exchange, symbol, tf, seconds_from=0, seconds_to=32536799999,
                    instrument_group=None, count_back=None, untraded=None, split_adjust=None, format='Simple'):  # https://alor.dev/docs/api/http/md-v-2-history-get
        """История рынка для выбранных биржи и инструмента

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param int|str tf: Длительность временнОго интервала в секундах или код ("D" - дни, "W" - недели, "M" - месяцы, "Y" - годы)
        :param int seconds_from: Дата и время UTC в секундах для первого запрашиваемого бара
        :param int seconds_to: Дата и время UTC в секундах для последнего запрашиваемого бара
        :param str instrument_group: Код режима торгов
        :param int count_back: Минимальное количество свечей, которое сервер должен вернуть в ответ на запрос
        :param bool untraded: Флаг для поиска данных по устаревшим или экспирированным инструментам. При использовании требуется точное совпадение тикера
        :param bool split_adjust: Флаг коррекции исторических свечей инструмента с учётом сплитов, консолидаций и прочих факторов
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос возвращает исторические данные о состоянии рынка для выбранных биржи и финансового инструмента
        """
        params = {'exchange': exchange, 'symbol': symbol, 'tf': tf, 'from': seconds_from, 'to': seconds_to, 'format': format}
        if instrument_group: params['instrumentGroup'] = instrument_group
        if count_back: params['countBack'] = count_back
        if untraded: params['untraded'] = untraded
        if split_adjust: params['splitAdjust'] = split_adjust
        return self.check_result(get(url=f'{self.api_server}/md/v2/history', params=params, headers=self.get_headers()))

    # Биржевые заявки

    def create_market_order(self, portfolio, exchange, symbol, side, quantity,
                            instrument_group=None, comment=None, time_in_force=None, allow_margin=None):  # https://alor.dev/docs/api/http/commandapi-warptrans-trade-v-2-client-orders-actions-market-post
        """Создать рыночную заявку

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param str instrument_group: Код режима торгов
        :param str comment: Пользовательский комментарий к заявке
        :param str time_in_force: Тип заявки: 'oneday' - до конца дня, 'immediateorcancel' - снять остаток, 'fillorkill' - исполнить целиком или отклонить, 'goodtillcancelled' - активна до отмены
        :param bool allow_margin: Флаг, подтверждающий согласие клиента с начальным уровнем риска (КНУР) на выставление заявки с потенциальной непокрытой позицией
        :return: Запрос создаёт от имени указанного портфеля рыночную заявку c указанными в теле сообщения характеристиками
        """
        headers = self.get_headers()
        headers['X-REQID'] = f'{portfolio};{self.get_request_id()}'  # Портфель с уникальным идентификатором запроса
        instrument = {'symbol': symbol, 'exchange': exchange}
        if instrument_group: instrument['instrumentGroup'] = instrument_group
        params = {'side': side, 'quantity': abs(quantity), 'instrument': instrument, 'user': {'portfolio': portfolio}}
        if comment: params['comment'] = comment
        if time_in_force: params['timeInForce'] = time_in_force
        if allow_margin: params['allowMargin'] = allow_margin
        return self.check_result(post(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/market', headers=headers, json=params))

    def create_limit_order(self, portfolio, exchange, symbol, side, quantity, price,
                           instrument_group=None, comment=None, time_in_force=None, allow_margin=None, iceberg_fixed=None, iceberg_variance=None):  # https://alor.dev/docs/api/http/commandapi-warptrans-trade-v-2-client-orders-actions-limit-post
        """Создать лимитную заявку

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float price: Цена
        :param str instrument_group: Код режима торгов
        :param str comment: Пользовательский комментарий к заявке
        :param str time_in_force: Тип заявки: 'oneday' - до конца дня, 'immediateorcancel' - снять остаток, 'fillorkill' - исполнить целиком или отклонить, 'goodtillcancelled' - активна до отмены
        :param bool allow_margin: Флаг, подтверждающий согласие клиента с начальным уровнем риска (КНУР) на выставление заявки с потенциальной непокрытой позицией
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах, указанная при создании лимитной заявки
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :return: Запрос создаёт от имени указанного портфеля лимитную заявку c указанными в теле сообщения характеристиками
        """
        headers = self.get_headers()
        headers['X-REQID'] = f'{portfolio};{self.get_request_id()}'  # Портфель с уникальным идентификатором запроса
        instrument = {'symbol': symbol, 'exchange': exchange}
        if instrument_group: instrument['instrumentGroup'] = instrument_group
        params = {'side': side, 'quantity': abs(quantity), 'price': price, 'instrument': instrument, 'user': {'portfolio': portfolio}}
        if comment: params['comment'] = comment
        if time_in_force: params['timeInForce'] = time_in_force
        if allow_margin: params['allowMargin'] = allow_margin
        if iceberg_fixed: params['icebergFixed'] = iceberg_fixed
        if iceberg_variance: params['icebergVariance'] = iceberg_variance
        return self.check_result(post(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/limit', headers=headers, json=params))

    def edit_market_order(self, portfolio, exchange, order_id, symbol, side, quantity,
                          instrument_group=None, comment=None, time_in_force=None, allow_margin=None):  # https://alor.dev/docs/api/http/commandapi-warptrans-trade-v-2-client-orders-actions-market-order-id-put
        """Изменить рыночную заявку

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param int order_id: Идентификатор заявки
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param str instrument_group: Код режима торгов
        :param str comment: Пользовательский комментарий к заявке
        :param str time_in_force: Тип заявки: 'oneday' - до конца дня, 'immediateorcancel' - снять остаток, 'fillorkill' - исполнить целиком или отклонить, 'goodtillcancelled' - активна до отмены
        :param bool allow_margin: Флаг, подтверждающий согласие клиента с начальным уровнем риска (КНУР) на выставление заявки с потенциальной непокрытой позицией
        :return: Запрос создаёт новую рыночную заявку с изменёнными характеристиками, автоматически отменив созданную ранее. Для определения отменяемой заявки используется её номер в параметре orderid
        """
        headers = self.get_headers()
        headers['X-REQID'] = f'{portfolio};{order_id};{quantity}'  # Портфель с уникальным идентификатором запроса и кол-вом в лотах
        instrument = {'symbol': symbol, 'exchange': exchange}
        if instrument_group: instrument['instrumentGroup'] = instrument_group
        params = {'side': side, 'quantity': abs(quantity), 'instrument': instrument, 'user': {'portfolio': portfolio}}
        if comment: params['comment'] = comment
        if time_in_force: params['timeInForce'] = time_in_force
        if allow_margin: params['allowMargin'] = allow_margin
        return self.check_result(put(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/market/{order_id}', headers=headers, json=params))

    def edit_limit_order(self, portfolio, exchange, order_id, symbol, side, quantity, price,
                         instrument_group=None, comment=None, time_in_force=None, allow_margin=None, iceberg_fixed=None, iceberg_variance=None):  # https://alor.dev/docs/api/http/commandapi-warptrans-trade-v-2-client-orders-actions-limit-order-id-put
        """Изменить лимитную заявку

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param int order_id: Идентификатор заявки
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float price: Цена
        :param str instrument_group: Код режима торгов
        :param str comment: Пользовательский комментарий к заявке
        :param str time_in_force: Тип заявки: 'oneday' - до конца дня, 'immediateorcancel' - снять остаток, 'fillorkill' - исполнить целиком или отклонить, 'goodtillcancelled' - активна до отмены
        :param bool allow_margin: Флаг, подтверждающий согласие клиента с начальным уровнем риска (КНУР) на выставление заявки с потенциальной непокрытой позицией
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах, указанная при создании лимитной заявки
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :return: Запрос создаёт новую лимитную заявку с изменёнными характеристиками, автоматически отменив созданную ранее. Для определения отменяемой заявки используется её номер в параметре orderid
        """
        headers = self.get_headers()
        headers['X-REQID'] = f'{portfolio};{order_id};{quantity}'  # Портфель с уникальным идентификатором запроса и кол-вом в лотах
        instrument = {'symbol': symbol, 'exchange': exchange}
        if instrument_group: instrument['instrumentGroup'] = instrument_group
        params = {'side': side, 'quantity': abs(quantity), 'price': price, 'instrument': instrument, 'user': {'portfolio': portfolio}}
        if comment: params['comment'] = comment
        if time_in_force: params['timeInForce'] = time_in_force
        if allow_margin: params['allowMargin'] = allow_margin
        if iceberg_fixed: params['icebergFixed'] = iceberg_fixed
        if iceberg_variance: params['icebergVariance'] = iceberg_variance
        return self.check_result(put(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/limit/{order_id}', headers=headers, json=params))

    def estimate_order(self, portfolio, exchange, symbol, price, quantity=None, budget=None, board=None, include_limit_orders=False):  # https://alor.dev/docs/api/http/commandapi-warptrans-trade-v-2-client-orders-estimate-post
        """Провести оценку одной заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param float price: Цена
        :param int quantity: Количество (лоты)
        :param float budget: Бюджет заявки на покупку инструмента
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param bool include_limit_orders: Учитывать ли лимитные заявки при расчете
        :return: Запрос возвращает результаты оценки соотношения текущего состояния рынка с заданными возможной характеристиками потенциальной заявки
        """
        params = {'portfolio': portfolio, 'ticker': symbol, 'exchange': exchange, 'price': price}
        if quantity:
            params['lotQuantity'] = quantity
        if budget:
            params['budget'] = budget
        if board:
            params['board'] = board
        if include_limit_orders:
            params['includeLimitOrders'] = include_limit_orders
        return self.check_result(post(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/estimate', json=params))

    def estimate_orders(self, orders):  # https://alor.dev/docs/api/http/commandapi-warptrans-trade-v-2-client-orders-estimate-all-post
        """Провести оценку нескольких заявок

        :param dict orders: Список параметров заявок. Оформлять каждую заявку как в EstimateOrder:
        {'portfolio': portfolio, 'ticker': symbol, 'exchange': exchange, 'price': price, 'lotQuantity': quantity, 'budget': budget, 'board': board, 'includeLimitOrders': include_limit_orders}
        """
        return self.check_result(post(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/estimate/all', json=orders))

    def delete_order(self, portfolio, exchange, order_id, stop=False, format='Simple'):  # https://alor.dev/docs/api/http/commandapi-warptrans-trade-v-2-client-orders-order-id-delete
        """Снять одну заявку

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param int order_id: Идентификатор заявки
        :param bool stop: Является ли стоп заявкой
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос снимает выставленную ранее заявку. Для определения отменяемой заявки используется её номер в параметре orderid
        """
        params = {'portfolio': portfolio, 'exchange': exchange, 'stop': stop, 'format': format}
        return self.check_result(delete(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/{order_id}', params=params, headers=self.get_headers()))

    def delete_all_orders(self, portfolio, exchange, stop=False):  # https://alor.dev/docs/api/http/commandapi-warptrans-trade-v-2-client-orders-all-delete
        """Снять все заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param bool stop: Является стоп-заявкой?
        :return: Запрос снимает все биржевые и/или условные заявки для указанного портфеля
        """
        params = {'portfolio': portfolio, 'exchange': exchange, 'stop': stop}
        return self.check_result(delete(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/all', params=params, headers=self.get_headers()))

    # Условные заявки

    def create_stop_order(self, portfolio, exchange, symbol, side, quantity, trigger_price,
                          instrument_group=None, condition='Less', stop_end_unix_time=0, allow_margin=None, protecting_seconds=15, activate=True):  # https://alor.dev/docs/api/http/commandapi-warptrans-trade-v-2-client-orders-actions-stop-post
        """Создать стоп-заявку

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float trigger_price: Условная цена (цена срабатывания)
        :param str instrument_group: Код режима торгов
        :param str condition: Условие срабатывания 'More', 'Less', 'MoreOrEqual', 'LessOrEqual'
        :param int stop_end_unix_time: Срок действия (UTC) в формате Unix Time Seconds
        :param bool allow_margin: Флаг, подтверждающий согласие клиента с начальным уровнем риска (КНУР) на выставление заявки с потенциальной непокрытой позицией
        :param int protecting_seconds: Защитное время. Непрерывный период времени в секундах, в течение которого рыночная цена инструмента должна соответствовать указанным в заявке цене и условию срабатывания (1-300)
        :param bool activate: Флаг указывает, создать активную заявку, или не активную. Не активная заявка отображается в системе, но не участвует в процессе выставления на биржу, пока не станет активной
        :return: Запрос создаёт от имени указанного портфеля стоп-заявку c указанными в теле сообщения характеристиками
        """
        headers = self.get_headers()
        headers['X-REQID'] = f'{portfolio};{self.get_request_id()}'  # Портфель с уникальным идентификатором запроса
        instrument = {'symbol': symbol, 'exchange': exchange}
        if instrument_group: instrument['instrumentGroup'] = instrument_group
        params = {'side': side, 'condition': condition, 'triggerPrice': trigger_price, 'stopEndUnixTime': stop_end_unix_time, 'quantity': abs(quantity),
                  'instrument': instrument, 'user': {'portfolio': portfolio, 'exchange': exchange}, 'protectingSeconds': protecting_seconds, 'activate': activate}
        if allow_margin: params['allowMargin'] = allow_margin
        return self.check_result(post(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/stop', headers=headers, json=params))

    def create_stop_limit_order(self, portfolio, exchange, symbol, side, quantity, trigger_price, price,
                                instrument_group=None, condition='Less', stop_end_unix_time=0, time_in_force=None, allow_margin=None,
                                iceberg_fixed=None, iceberg_variance=None, protecting_seconds=15, activate=True):  # https://alor.dev/docs/api/http/commandapi-warptrans-trade-v-2-client-orders-actions-stop-limit-post
        """Создать стоп-лимитную заявку

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float trigger_price: Условная цена (цена срабатывания)
        :param float price: Цена
        :param str instrument_group: Код режима торгов
        :param str condition: Условие срабатывания 'More', 'Less', 'MoreOrEqual', 'LessOrEqual'
        :param int stop_end_unix_time: Срок действия (UTC) в формате Unix Time Seconds
        :param str time_in_force: Тип заявки: 'oneday' - до конца дня, 'immediateorcancel' - снять остаток, 'fillorkill' - исполнить целиком или отклонить, 'goodtillcancelled' - активна до отмены
        :param bool allow_margin: Флаг, подтверждающий согласие клиента с начальным уровнем риска (КНУР) на выставление заявки с потенциальной непокрытой позицией
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах, указанная при создании лимитной заявки
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :param int protecting_seconds: Защитное время. Непрерывный период времени в секундах, в течение которого рыночная цена инструмента должна соответствовать указанным в заявке цене и условию срабатывания (1-300)
        :param bool activate: Флаг указывает, создать активную заявку, или не активную. Не активная заявка отображается в системе, но не участвует в процессе выставления на биржу, пока не станет активной
        :return: Запрос создаёт от имени указанного портфеля стоп-лимитную заявку c указанными в теле сообщения характеристиками
        """
        headers = self.get_headers()
        headers['X-REQID'] = f'{portfolio};{self.get_request_id()}'  # Портфель с уникальным идентификатором запроса
        instrument = {'symbol': symbol, 'exchange': exchange}
        if instrument_group: instrument['instrumentGroup'] = instrument_group
        params = {'side': side, 'condition': condition, 'triggerPrice': trigger_price, 'stopEndUnixTime': stop_end_unix_time, 'price': price, 'quantity': abs(quantity),
                  'instrument': instrument, 'user': {'portfolio': portfolio, 'exchange': exchange}, 'protectingSeconds': protecting_seconds, 'activate': activate}
        if time_in_force: params['timeInForce'] = time_in_force
        if allow_margin: params['allowMargin'] = allow_margin
        if iceberg_fixed: params['icebergFixed'] = iceberg_fixed
        if iceberg_variance: params['icebergVariance'] = iceberg_variance
        return self.check_result(post(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/stopLimit', headers=headers, json=params))

    def edit_stop_order(self, portfolio, exchange, order_id, symbol, side, quantity, trigger_price,
                        instrument_group=None, condition='Less', stop_end_unix_time=0, allow_margin=None, protecting_seconds=15, activate=True):  # https://alor.dev/docs/api/http/commandapi-warptrans-trade-v-2-client-orders-actions-stop-stop-order-id-put
        """Изменить стоп-заявку

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param int order_id: Идентификатор заявки
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float trigger_price: Условная цена (цена срабатывания)
        :param str instrument_group: Код режима торгов
        :param str condition: Условие срабатывания 'More', 'Less', 'MoreOrEqual', 'LessOrEqual'
        :param int stop_end_unix_time: Срок действия (UTC) в формате Unix Time Seconds
        :param bool allow_margin: Флаг, подтверждающий согласие клиента с начальным уровнем риска (КНУР) на выставление заявки с потенциальной непокрытой позицией
        :param int protecting_seconds: Защитное время. Непрерывный период времени в секундах, в течение которого рыночная цена инструмента должна соответствовать указанным в заявке цене и условию срабатывания (1-300)
        :param bool activate: Флаг указывает, создать активную заявку, или не активную. Не активная заявка отображается в системе, но не участвует в процессе выставления на биржу, пока не станет активной
        :return: Запрос создаёт новую стоп-заявку с изменёнными характеристиками, автоматически отменив созданную ранее. Для определения отменяемой заявки используется её номер в параметре orderid
        """
        headers = self.get_headers()
        instrument = {'symbol': symbol, 'exchange': exchange}
        if instrument_group: instrument['instrumentGroup'] = instrument_group
        headers['X-REQID'] = f'{portfolio};{self.get_request_id()}'  # Портфель с уникальным идентификатором запроса
        params = {'side': side, 'condition': condition, 'triggerPrice': trigger_price, 'stopEndUnixTime': stop_end_unix_time, 'quantity': abs(quantity),
                  'instrument': instrument, 'user': {'portfolio': portfolio, 'exchange': exchange}, 'protectingSeconds': protecting_seconds, 'activate': activate}
        if allow_margin: params['allowMargin'] = allow_margin
        return self.check_result(put(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/stop/{order_id}', headers=headers, json=params))

    def edit_stop_limit_order(self, portfolio, exchange, order_id, symbol, side, quantity, trigger_price, price,
                              instrument_group=None, condition='Less', stop_end_unix_time=0, time_in_force=None, allow_margin=None,
                              iceberg_fixed=None, iceberg_variance=None, protecting_seconds=15, activate=True):  # https://alor.dev/docs/api/http/commandapi-warptrans-trade-v-2-client-orders-actions-stop-limit-stop-order-id-put
        """Изменить стоп-лимитную заявку

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param int order_id: Идентификатор заявки
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float trigger_price: Условная цена (цена срабатывания)
        :param float price: Цена
        :param str instrument_group: Код режима торгов
        :param str condition: Условие срабатывания 'More', 'Less', 'MoreOrEqual', 'LessOrEqual'
        :param int stop_end_unix_time: Дата и время UTC в секундах завершения сделки
        :param str time_in_force: Тип заявки: 'oneday' - до конца дня, 'immediateorcancel' - снять остаток, 'fillorkill' - исполнить целиком или отклонить, 'goodtillcancelled' - активна до отмены
        :param bool allow_margin: Флаг, подтверждающий согласие клиента с начальным уровнем риска (КНУР) на выставление заявки с потенциальной непокрытой позицией
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :param int protecting_seconds: Защитное время. Непрерывный период времени в секундах, в течение которого рыночная цена инструмента должна соответствовать указанным в заявке цене и условию срабатывания (1-300)
        :param bool activate: Флаг указывает, создать активную заявку, или не активную. Не активная заявка отображается в системе, но не участвует в процессе выставления на биржу, пока не станет активной
        :return: Запрос создаёт новую стоп-лимитную заявку с изменёнными характеристиками, автоматически отменив созданную ранее. Для определения отменяемой заявки используется её номер в параметре orderid
        """
        headers = self.get_headers()
        headers['X-REQID'] = f'{portfolio};{self.get_request_id()}'  # Портфель с уникальным идентификатором запроса
        instrument = {'symbol': symbol, 'exchange': exchange}
        if instrument_group: instrument['instrumentGroup'] = instrument_group
        params = {'side': side, 'condition': condition, 'triggerPrice': trigger_price, 'stopEndUnixTime': stop_end_unix_time, 'price': price, 'quantity': abs(quantity),
                  'instrument': instrument, 'user': {'portfolio': portfolio, 'exchange': exchange}, 'protectingSeconds': protecting_seconds, 'activate': activate}
        if time_in_force: params['timeInForce'] = time_in_force
        if allow_margin: params['allowMargin'] = allow_margin
        if iceberg_fixed: params['icebergFixed'] = iceberg_fixed
        if iceberg_variance: params['icebergVariance'] = iceberg_variance
        return self.check_result(put(url=f'{self.api_server}/commandapi/warptrans/TRADE/v2/client/orders/actions/stopLimit/{order_id}', headers=headers, json=params))

    # Группы заявок

    def get_order_groups(self):  # https://alor.dev/docs/api/http/commandapi-api-order-groups-get
        """Все группы заявок

        :return: Запрос возвращает список групп заявок для логина, выписавшего токен
        """
        return self.check_result(get(url=f'{self.api_server}/commandapi/api/orderGroups', headers=self.get_headers()))

    def get_order_group(self, order_group_id):  # https://alor.dev/docs/api/http/commandapi-api-order-groups-order-group-id-get
        """Выбранная группа заявок

        :param str order_group_id: Идентификатор группы заявок
        :return: Запрос возвращает информацию об определённой группе заявок, идентификатор которой указан в параметре orderGroupId
        """
        return self.check_result(get(url=f'{self.api_server}/commandapi/api/orderGroups{order_group_id}', headers=self.get_headers()))

    def create_order_group(self, orders, execution_policy):  # https://alor.dev/docs/api/http/commandapi-api-order-groups-post
        """Создать группу заявок

        :param orders: Заявки, из которых будет состоять группа. Каждая заявка состоит из:
            'portfolio' - Идентификатор клиентского портфеля
            'exchange' - Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
            'orderId' - Уникальный идентификатор заявки
            'type' - Тип заявки. 'Market' - рыночная заявка, 'Limit' - лимитная заявка, 'Stop' - стоп-заявка, 'StopLimit' - стоп-лимит заявка
        :param str execution_policy: Тип группы заявок:
            'OnExecuteOrCancel' - Группа отменяется при отмене/выполнении/редактировании любой заявки
            'IgnoreCancel' - Группа отменяется при исполнении заявки. При отмене или редактировании заявки - заявка удаляется из группы, группа остаётся активной
            'TriggerBracketOrders' - Группа, содержащая одну лимитную заявку и несколько стопов. Для создания группы, стоп-заявки должны быть созданны с флагом 'Activate = false'. После выполнения лимитной заявки, активируются стоп-заявки
        :return: Создание группы заявок на основе уже созданных заявок
        """
        params = {'orders': orders, 'executionPolicy': execution_policy}
        return self.check_result(post(url=f'{self.api_server}/commandapi/api/orderGroups', headers=self.get_headers(), json=params))

    def edit_order_group(self, order_group_id, orders, execution_policy):  # https://alor.dev/docs/api/http/commandapi-api-order-groups-order-group-id-put
        """Изменить группу заявок

        :param str order_group_id: Идентификатор группы заявок
        :param orders: Заявки, из которых будет состоять группа. Каждая заявка состоит из:
            'portfolio' - Идентификатор клиентского портфеля
            'exchange' - Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
            'orderId' - Уникальный идентификатор заявки
            'type' - Тип заявки. 'Market' - рыночная заявка, 'Limit' - лимитная заявка, 'Stop' - стоп-заявка, 'StopLimit' - стоп-лимит заявка
        :param str execution_policy: Тип группы заявок:
            'OnExecuteOrCancel' - Группа отменяется при отмене/выполнении/редактировании любой заявки
            'IgnoreCancel' - Группа отменяется при исполнении заявки. При отмене или редактировании заявки - заявка удаляется из группы, группа остаётся активной
            'TriggerBracketOrders' - Группа, содержащая одну лимитную заявку и несколько стопов. Для создания группы, стоп-заявки должны быть созданны с флагом 'Activate = false'. После выполнения лимитной заявки, активируются стоп-заявки
        :return: Изменение характеристик группы заявок с указанным в параметре orderGroupId идентификатором: связывание новых заявок, изменение типа связи и так далее
        """
        params = {'orders': orders, 'executionPolicy': execution_policy}
        return self.check_result(put(url=f'{self.api_server}/commandapi/api/orderGroups{order_group_id}', headers=self.get_headers(), json=params))

    def delete_order_group(self, order_group_id):  # https://alor.dev/docs/api/http/commandapi-api-order-groups-order-group-id-delete
        """Удалить группу заявок

        :param str order_group_id: Идентификатор группы заявок
        :return: Снятие группы заявок с идентификатором, указанным в параметре orderGroupId. При снятии группы заявок также будут сняты все заявки, входившие в эту группу
        """
        return self.check_result(delete(url=f'{self.api_server}/commandapi/api/orderGroups{order_group_id}', headers=self.get_headers()))

    # Другое

    def get_time(self):  # https://alor.dev/docs/api/http/md-v-2-time-get
        """Текущее UTC время
        :return: Запрос возвращает текущее значение UTC времени в формате Unix Time Seconds
        """
        return self.check_result(get(url=f'{self.api_server}/md/v2/time', headers=self.get_headers()))

    # Устаревшее

    def get_money(self, portfolio, exchange, format='Simple'):  # https://alor.dev/docs/api/http/exchange-portfolio-money
        """Деньги выбранного портфеля

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос информации о позиции по деньгам. Вызов существует для обратной совместимости с API v1, предпочтительно использовать другие вызовы (/summary, /risk, /positions)
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/v2/clients/legacy/{exchange}/{portfolio}/money', params=params, headers=self.get_headers()))

    def get_trades_history(self, portfolio, exchange, symbol=None, date_from=None, side=None, id_from=None, limit=None, order_by_trade_date=None, descending=None, with_repo=None, format='Simple'):  # https://alor.dev/docs/api/http/trade-stats
        """Вся история сделок

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str date_from: Начало отрезка времени, за которое требуется получить историю сделок
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int id_from: Начальный номер сделки для фильтра результатов
        :param int limit: Количество возвращаемых записей (1-1000)
        :param bool order_by_trade_date: Флаг сортировки возвращаемых результатов по дате совершения сделки
        :param bool descending: Флаг обратной сортировки выдачи
        :param bool with_repo: Флаг отображения заявок с РЕПО
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос списка сделок за предыдущие дни (не более 1000 сделок за один запрос)
        """
        params: dict[str, Any] = {'format': format}
        if date_from: params['dateFrom'] = date_from
        if symbol: params['ticker'] = symbol
        if side: params['side'] = side
        if id_from: params['from'] = id_from
        if limit: params['limit'] = limit
        if order_by_trade_date: params['orderByTradeDate'] = order_by_trade_date
        if descending: params['descending'] = descending
        if with_repo: params['withRepo'] = with_repo
        return self.check_result(get(url=f'{self.api_server}/md/stats/{exchange}/{portfolio}/history/trades', params=params, headers=self.get_headers()))

    def get_trades_symbol(self, portfolio, exchange, symbol, date_from=None, id_from=None, limit=None, order_by_trade_date=None, descending=None, with_repo=None, format='Simple'):  # https://alor.dev/docs/api/http/trade-stats-by-symbol
        """История сделок для выбранного инструмента

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str date_from: Начало отрезка времени, за которое требуется получить историю сделок
        :param int id_from: Начальный номер сделки для фильтра результатов
        :param int limit: Количество возвращаемых записей (1-1000)
        :param bool order_by_trade_date: Флаг сортировки возвращаемых результатов по дате совершения сделки
        :param bool descending: Флаг обратной сортировки выдачи
        :param bool with_repo: Флаг отображения заявок с РЕПО
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Запрос списка сделок за предыдущие дни (не более 1000 сделок за один запрос) по одному инструменту
        """
        params: dict[str, Any] = {'format': format}
        if date_from: params['dateFrom'] = date_from
        if id_from: params['from'] = id_from
        if limit: params['limit'] = limit
        if order_by_trade_date: params['orderByTradeDate'] = order_by_trade_date
        if descending: params['descending'] = descending
        if with_repo: params['withRepo'] = with_repo
        return self.check_result(get(url=f'{self.api_server}/md/stats/{exchange}/{portfolio}/history/trades/{symbol}', params=params, headers=self.get_headers()))

    def get_exchange_market(self, exchange, market, format='Simple'):  # https://alor.dev/docs/api/http/dev-trading-session-status
        """Статус торгов

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str market: Рынок на бирже: FORTS, FOND, CURR, SPBX
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Возвращает информацию о статусе торгов для указанного рынка на выбранной бирже
        """
        params = {'format': format}
        return self.check_result(get(url=f'{self.api_server}/md/status/{exchange}/{market}', params=params, headers=self.get_headers()))

    def create_stop_loss_order(self, trade_server_code, account, portfolio, exchange, symbol, side, quantity, trigger_price, comment=None, order_end_unix_time=0):  # https://alor.dev/docs/api/http/v-2-client-orders-actions-stop-loss
        """Создать стоп-лосс заявку

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float trigger_price: Условная цена (цена срабатывания)
        :param str comment: Пользовательский комментарий к заявке
        :param int order_end_unix_time: Срок действия (UTC) в формате Unix Time Seconds
        :return: Запрос создаёт стоп-лосс заявку с указанными характеристиками
        """
        headers = self.get_headers()
        headers['X-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        params = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': trigger_price, 'Instrument': {'Symbol': symbol, 'Exchange': exchange},
                  'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': order_end_unix_time}
        if comment: params['comment'] = comment
        return self.check_result(post(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/actions/stopLoss', headers=headers, json=params))

    def create_take_profit_order(self, trade_server_code, account, portfolio, exchange, symbol, side, quantity, trigger_price, comment=None, order_end_unix_time=0):  # https://alor.dev/docs/api/http/v-2-client-orders-actions-take-profit
        """Создать стоп-заявку

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float trigger_price: Условная цена (цена срабатывания)
        :param str comment: Пользовательский комментарий к заявке
        :param int order_end_unix_time: Срок действия (UTC) в формате Unix Time Seconds
        :return: Запрос создаёт стоп-заявку с указанными характеристиками
        """
        headers = self.get_headers()
        headers['X-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        params = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': trigger_price, 'Instrument': {'Symbol': symbol, 'Exchange': exchange},
                  'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': order_end_unix_time}
        if comment: params['comment'] = comment
        return self.check_result(post(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/actions/takeProfit', headers=headers, json=params))

    def create_take_profit_limit_order(self, trade_server_code, account, portfolio, exchange, symbol, side, quantity, trigger_price, price,
                                       comment=None, order_end_unix_time=0, time_in_force=None, iceberg_fixed=None, iceberg_variance=None):  # https://alor.dev/docs/api/http/v-2-client-orders-actions-take-profit-limit
        """Создать стоп-лимит заявку

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float trigger_price: Условная цена (цена срабатывания)
        :param float price: Цена
        :param str comment: Пользовательский комментарий к заявке
        :param int order_end_unix_time: Срок действия (UTC) в формате Unix Time Seconds
        :param str time_in_force: Тип заявки: 'oneday' - до конца дня, 'immediateorcancel' - снять остаток, 'fillorkill' - исполнить целиком или отклонить, 'goodtillcancelled' - активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :return: Запрос создаёт стоп-лимит заявку с указанными характеристиками
        """
        headers = self.get_headers()
        headers['X-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        params = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': trigger_price, 'Price': price, 'Instrument': {'Symbol': symbol, 'Exchange': exchange},
                  'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': order_end_unix_time}
        if comment: params['comment'] = comment
        if time_in_force: params['timeInForce'] = time_in_force
        if iceberg_fixed: params['icebergFixed'] = iceberg_fixed
        if iceberg_variance: params['icebergVariance'] = iceberg_variance
        return self.check_result(post(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/actions/takeProfitLimit', headers=headers, json=params))

    def create_stop_loss_limit_order(self, trade_server_code, account, portfolio, exchange, symbol, side, quantity, trigger_price, price,
                                     comment=None, order_end_unix_time=0, time_in_force=None, iceberg_fixed=None, iceberg_variance=None):  # https://alor.dev/docs/api/http/v-2-client-orders-actions-stop-loss-limit
        """Создать стоп-лосс лимит заявку

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float trigger_price: Условная цена (цена срабатывания)
        :param float price: Цена
        :param str comment: Пользовательский комментарий к заявке
        :param int order_end_unix_time: Срок действия (UTC) в формате Unix Time Seconds
        :param str time_in_force: Тип заявки: 'oneday' - до конца дня, 'immediateorcancel' - снять остаток, 'fillorkill' - исполнить целиком или отклонить, 'goodtillcancelled' - активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :return: Запрос создаёт стоп-лосс лимит заявку с указанными характеристиками
        """
        headers = self.get_headers()
        headers['X-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        params = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': trigger_price, 'Price': price, 'Instrument': {'Symbol': symbol, 'Exchange': exchange},
                  'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': order_end_unix_time}
        if comment: params['comment'] = comment
        if time_in_force: params['timeInForce'] = time_in_force
        if iceberg_fixed: params['icebergFixed'] = iceberg_fixed
        if iceberg_variance: params['icebergVariance'] = iceberg_variance
        return self.check_result(post(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/actions/stopLossLimit', headers=headers, json=params))

    def edit_stop_loss_order(self, trade_server_code, account, portfolio, exchange, order_id, symbol, side, quantity, trigger_price, comment=None, order_end_unix_time=0):  # https://alor.dev/docs/api/http/v-2-client-orders-actions-stop-loss-order-id
        """Изменить стоп-лосс заявку

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param int order_id: Идентификатор заявки
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float trigger_price: Условная цена (цена срабатывания)
        :param str comment: Пользовательский комментарий к заявке
        :param int order_end_unix_time: Срок действия (UTC) в формате Unix Time Seconds
        :return: Запрос изменяет характеристики ранее поданной стоп-лосс заявки с указанным номером
        """
        headers = self.get_headers()
        headers['X-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        params = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': trigger_price, 'Instrument': {'Symbol': symbol, 'Exchange': exchange},
                  'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': order_end_unix_time}
        if comment: params['comment'] = comment
        return self.check_result(put(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/actions/stopLoss/{order_id}', headers=headers, json=params))

    def edit_take_profit_order(self, trade_server_code, account, portfolio, exchange, order_id, symbol, side, quantity, trigger_price, comment=None, order_end_unix_time=0):
        """Изменить стоп-заявку

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param int order_id: Идентификатор заявки
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float trigger_price: Условная цена (цена срабатывания)
        :param str comment: Пользовательский комментарий к заявке
        :param int order_end_unix_time: Срок действия (UTC) в формате Unix Time Seconds
        :return: Запрос изменяет характеристики ранее поданной стоп-заявки с указанным номером
        """
        headers = self.get_headers()
        headers['X-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        params = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': trigger_price, 'Instrument': {'Symbol': symbol, 'Exchange': exchange},
                  'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': order_end_unix_time}
        if comment: params['comment'] = comment
        return self.check_result(put(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/actions/takeProfit/{order_id}', headers=headers, json=params))

    def edit_take_profit_limit_order(self, trade_server_code, account, portfolio, exchange, order_id, symbol, side, quantity, trigger_price, price,
                                     comment=None, order_end_unix_time=0, time_in_force=None, iceberg_fixed=None, iceberg_variance=None):  # https://alor.dev/docs/api/http/v-2-client-orders-actions-take-profit-limit-order-id
        """Изменение стоп-лимит заявки

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param int order_id: Идентификатор заявки
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float trigger_price: Условная цена (цена срабатывания)
        :param float price: Цена
        :param str comment: Пользовательский комментарий к заявке
        :param int order_end_unix_time: Срок действия (UTC) в формате Unix Time Seconds
        :param str time_in_force: Тип заявки: 'oneday' - до конца дня, 'immediateorcancel' - снять остаток, 'fillorkill' - исполнить целиком или отклонить, 'goodtillcancelled' - активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :return: Запрос изменяет характеристики ранее поданной стоп-лимит заявки с указанным номером
        """
        headers = self.get_headers()
        headers['X-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        params = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': trigger_price, 'Price': price, 'Instrument': {'Symbol': symbol, 'Exchange': exchange},
                  'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': order_end_unix_time}
        if comment: params['comment'] = comment
        if time_in_force: params['timeInForce'] = time_in_force
        if iceberg_fixed: params['icebergFixed'] = iceberg_fixed
        if iceberg_variance: params['icebergVariance'] = iceberg_variance
        return self.check_result(put(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/actions/takeProfitLimit/{order_id}', headers=headers, json=params))

    def edit_stop_loss_limit_order(self, trade_server_code, account, portfolio, exchange, order_id, symbol, side, quantity, trigger_price, price,
                                   comment=None, order_end_unix_time=0, time_in_force=None, iceberg_fixed=None, iceberg_variance=None):  # https://alor.dev/docs/api/http/v-2-client-orders-actions-stop-loss-limit-order-id
        """Изменить стоп-лосс лимит заявку

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param int order_id: Идентификатор заявки
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float trigger_price: Стоп цена
        :param float price: Цена
        :param str comment: Пользовательский комментарий к заявке
        :param int order_end_unix_time: Дата и время UTC в секундах завершения сделки
        :param str time_in_force: Тип заявки: 'oneday' - до конца дня, 'immediateorcancel' - снять остаток, 'fillorkill' - исполнить целиком или отклонить, 'goodtillcancelled' - активна до отмены
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :return: Запрос изменяет характеристики ранее поданной стоп-лосс лимит заявки с указанным номером
        """
        headers = self.get_headers()
        headers['X-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        params = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': trigger_price, 'Price': price, 'Instrument': {'Symbol': symbol, 'Exchange': exchange},
                  'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': order_end_unix_time}
        if comment: params['comment'] = comment
        if time_in_force: params['timeInForce'] = time_in_force
        if iceberg_fixed: params['icebergFixed'] = iceberg_fixed
        if iceberg_variance: params['icebergVariance'] = iceberg_variance
        return self.check_result(put(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/actions/stopLossLimit/{order_id}', headers=headers, json=params))

    def delete_stop_order(self, trade_server_code, portfolio, order_id, stop=True):  # https://alor.dev/docs/api/http/v-2-client-orders-actions-order-id
        """Снять стоп-заявку

        :param str trade_server_code: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str portfolio: Идентификатор клиентского портфеля
        :param int order_id: Идентификатор заявки
        :param bool stop: Является ли стоп заявкой
        :return: Снятие стоп-заявки с указанным идентификатором
        """
        headers = self.get_headers()
        headers['X-REQID'] = self.get_request_id()  # Уникальный идентификатор запроса
        params = {'portfolio': portfolio, 'stop': stop}
        return self.check_result(delete(url=f'{self.api_server}/warptrans/{trade_server_code}/v2/client/orders/{order_id}', headers=headers, params=params))

    def get_portfolios(self, user_name):
        """Получение списка серверов портфелей

        :param str user_name: Номер счета
        """
        return self.check_result(get(url=f'{self.api_server}/client/v1.0/users/{user_name}/portfolios', headers=self.get_headers()))

    def stop_orders_get_and_subscribe(self, portfolio, exchange) -> str:
        """Подписка на информацию о текущих стоп-заявках на рынке для выбранных биржи и финансового инструмента

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'StopOrdersGetAndSubscribe', 'exchange': exchange, 'portfolio': portfolio, 'format': 'Simple'}  # Запрос на подписку
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    # WebSocket API - Управление подписками

    def order_book_get_and_subscribe(self, exchange, symbol, instrument_group=None, depth=20, frequency=0, format='Simple'):  # https://alor.dev/docs/api/websocket/data-subscriptions/OrderBookGetAndSubscribe
        """Биржевой стакан

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str instrument_group: Код режима торгов
        :param int depth: Глубина стакана. Стандартное значение — 20 (20x20), максимальное — 50 (50х50)
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'OrderBookGetAndSubscribe', 'exchange': exchange, 'code': symbol, 'depth': depth, 'frequency': frequency, 'format': format}  # Запрос на подписку
        if instrument_group: request['instrumentGroup'] = instrument_group
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def bars_get_and_subscribe(self, exchange, symbol, tf, instrument_group=None, seconds_from=0, skip_history=False, split_adjust=None, frequency=0, format='Simple'):  # https://alor.dev/docs/api/websocket/data-subscriptions/BarsGetAndSubscribe
        """История цен (свечи)

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param tf: Длительность временнОго интервала в секундах или код ("D" - дни, "W" - недели, "M" - месяцы, "Y" - годы)
        :param str instrument_group: Код режима торгов
        :param int seconds_from: Дата и время UTC в секундах для первого запрашиваемого бара
        :param bool skip_history: Флаг отсеивания исторических данных: True — отображать только новые данные, False — отображать в том числе данные из истории
        :param bool split_adjust: Флаг коррекции исторических свечей инструмента с учётом сплитов, консолидаций и прочих факторов
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'BarsGetAndSubscribe', 'exchange': exchange, 'code': symbol, 'tf': tf, 'from': int(seconds_from), 'skipHistory': skip_history, 'frequency': frequency, 'format': format}  # Запрос на подписку
        if instrument_group: request['instrumentGroup'] = instrument_group
        if split_adjust: request['splitAdjust'] = split_adjust
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def quotes_subscribe(self, exchange, symbol, instrument_group=None, frequency=0, format='Simple'):  # https://alor.dev/docs/api/websocket/data-subscriptions/QuotesSubscribe
        """Котировки

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str instrument_group: Код режима торгов
        :param int frequency: Максимальная частота отдачи данных сервером в миллисекундах
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'QuotesSubscribe', 'exchange': exchange, 'code': symbol, 'frequency': frequency, 'format': format}  # Запрос на подписку
        if instrument_group: request['instrumentGroup'] = instrument_group
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def trades_get_and_subscribe_v2(self, portfolio, exchange, instrument_group=None, skip_history=False, format='Simple'):  # https://alor.dev/docs/api/websocket/data-subscriptions/TradesGetAndSubscribe
        """Все сделки по портфелю

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str instrument_group: Код режима торгов
        :param bool skip_history: Флаг отсеивания исторических данных: True — отображать только новые данные, False — отображать в том числе данные из истории
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'TradesGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'skipHistory': skip_history, 'format': format}  # Запрос на подписку
        if instrument_group: request['instrumentGroup'] = instrument_group
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def all_trades_subscribe(self, exchange, symbol, instrument_group=None, depth=0, include_virtual_trades=False, format='Simple'):  # https://alor.dev/docs/api/websocket/data-subscriptions/AllTradesGetAndSubscribe
        """Все сделки по инструменту

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str instrument_group: Код режима торгов
        :param int depth: Если указать, то перед актуальными данными придут данные о последних N сделках. Максимум 5000
        :param bool include_virtual_trades: Указывает, нужно ли отправлять виртуальные (индикативные) сделки
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'AllTradesGetAndSubscribe', 'code': symbol, 'exchange': exchange, 'depth': depth, 'includeVirtualTrades': include_virtual_trades, 'format': format}  # Запрос на подписку
        if instrument_group: request['instrumentGroup'] = instrument_group
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def positions_get_and_subscribe_v2(self, portfolio, exchange, instrument_group=None, skip_history=False, format='Simple'):  # https://alor.dev/docs/api/websocket/data-subscriptions/PositionsGetAndSubscribe
        """Текущие позиции по торговым инструментам и деньгам

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str instrument_group: Код режима торгов
        :param bool skip_history: Флаг отсеивания исторических данных: True — отображать только новые данные, False — отображать в том числе данные из истории
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'PositionsGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'skipHistory': skip_history, 'format': format}  # Запрос на подписку
        if instrument_group: request['instrumentGroup'] = instrument_group
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def summaries_get_and_subscribe_v2(self, portfolio, exchange, instrument_group=None, skip_history=False, format='Simple'):  # https://alor.dev/docs/api/websocket/data-subscriptions/SummariesGetAndSubscribeV2
        """Сводная информация о портфеле

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str instrument_group: Код режима торгов
        :param bool skip_history: Флаг отсеивания исторических данных: True — отображать только новые данные, False — отображать в том числе данные из истории
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'SummariesGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'skipHistory': skip_history, 'format': format}  # Запрос на подписку
        if instrument_group: request['instrumentGroup'] = instrument_group
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def risks_get_and_subscribe(self, portfolio, exchange, instrument_group=None, skip_history=False, format='Simple'):  # https://alor.dev/docs/api/websocket/data-subscriptions/RisksGetAndSubscribe
        """Портфельные риски

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str instrument_group: Код режима торгов
        :param bool skip_history: Флаг отсеивания исторических данных: True — отображать только новые данные, False — отображать в том числе данные из истории
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'RisksGetAndSubscribe', 'exchange': exchange, 'portfolio': portfolio, 'skipHistory': skip_history, 'format': format}  # Запрос на подписку
        if instrument_group: request['instrumentGroup'] = instrument_group
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def spectra_risks_get_and_subscribe(self, portfolio, exchange, instrument_group=None, skip_history=False, format='Simple'):  # https://alor.dev/docs/api/websocket/data-subscriptions/SpectraRisksGetAndSubscribe
        """Риски срочного рынка (FORTS)

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str instrument_group: Код режима торгов
        :param bool skip_history: Флаг отсеивания исторических данных: True — отображать только новые данные, False — отображать в том числе данные из истории
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'SpectraRisksGetAndSubscribe', 'exchange': exchange, 'portfolio': portfolio, 'skipHistory': skip_history, 'format': format}  # Запрос на подписку
        if instrument_group: request['instrumentGroup'] = instrument_group
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def instruments_get_and_subscribe_v2(self, exchange, symbol, instrument_group=None, format='Simple'):  # https://alor.dev/docs/api/websocket/data-subscriptions/InstrumentsGetAndSubscribeV2
        """Изменения информации о финансовых инструментах

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str instrument_group: Код режима торгов
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'InstrumentsGetAndSubscribeV2', 'code': symbol, 'exchange': exchange, 'format': format}  # Запрос на подписку
        if instrument_group: request['instrumentGroup'] = instrument_group
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def orders_get_and_subscribe_v2(self, portfolio, exchange, instrument_group=None, order_statuses=None, skip_history=False, format='Simple'):  # https://alor.dev/docs/api/websocket/data-subscriptions/OrdersGetAndSubscribe
        """Все заявки по портфелю

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str instrument_group: Код режима торгов
        :param list[str] order_statuses: Опциональный фильтр по статусам заявок. 'working' - на исполнении, 'filled' - исполнена, 'canceled' - отменена, 'rejected' - отклонена
        Влияет только на фильтрацию первичных исторических данных при подписке  Пример: order_statuses=['filled', 'canceled']
        :param bool skip_history: Флаг отсеивания исторических данных: True — отображать только новые данные, False — отображать в том числе данные из истории
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request: dict[str, Any] = {'opcode': 'OrdersGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'skipHistory': skip_history, 'format': format}  # Запрос на подписку
        if instrument_group: request['instrumentGroup'] = instrument_group
        if order_statuses: request['orderStatuses'] = order_statuses
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def stop_orders_get_and_subscribe_v2(self, portfolio, exchange, instrument_group=None, order_statuses=None, skip_history=False, format='Simple'):  # https://alor.dev/docs/api/websocket/data-subscriptions/StopOrdersGetAndSubscribeV2
        """Все стоп-заявки по портфелю

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str instrument_group: Код режима торгов
        :param list[str] order_statuses: Опциональный фильтр по статусам заявок. 'working' - на исполнении, 'filled' - исполнена, 'canceled' - отменена, 'rejected' - отклонена
        Влияет только на фильтрацию первичных исторических данных при подписке  Пример: order_statuses=['filled', 'canceled']
        :param bool skip_history: Флаг отсеивания исторических данных: True — отображать только новые данные, False — отображать в том числе данные из истории
        :param str format: Формат возвращаемого сервером JSON-объекта: 'Simple', 'Slim', 'Heavy'
        :return: Уникальный идентификатор подписки
        """
        request: dict[str, Any] = {'opcode': 'StopOrdersGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'skipHistory': skip_history, 'format': format}  # Запрос на подписку
        if instrument_group: request['instrumentGroup'] = instrument_group
        if order_statuses: request['orderStatuses'] = order_statuses
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    def unsubscribe(self, guid):  # https://alor.dev/docs/api/websocket/data-subscriptions/Unsubscribe
        """Отмена существующей подписки

        :param str guid: Уникальный идентификатор подписки
        :return: Уникальный идентификатор подписки
        """
        request = {'opcode': 'unsubscribe', 'token': str(self.get_jwt_token()), 'guid': guid}  # Запрос на отмену подписки
        get_event_loop().run_until_complete(self.ws_socket.send(dumps(request)))  # Отправляем запрос. Дожидаемся его выполнения
        del self.subscriptions[guid]  # Удаляем подписку из справочника
        return self.subscribe(request)  # Отправляем запрос, возвращаем уникальный идентификатор подписки

    # WebSocket API - Управление заявками

    def authorize_websocket(self):  # https://alor.dev/docs/api/websocket/commands/Authorize
        """Авторизация"""
        return self.send_websocket({'opcode': 'authorize', 'token': self.get_jwt_token()})

    def create_market_order_websocket(self, portfolio, exchange, symbol, side, quantity,
                                      board=None, comment=None, time_in_force=None, allow_margin=None, check_duplicates=None):  # https://alor.dev/docs/api/websocket/commands/CreateMarketOrder
        """Создание рыночной заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str comment: Пользовательский комментарий к заявке
        :param str time_in_force: Тип заявки: 'oneday' - до конца дня, 'immediateorcancel' - снять остаток, 'fillorkill' - исполнить целиком или отклонить, 'goodtillcancelled' - активна до отмены
        :param bool allow_margin: Флаг, подтверждающий согласие клиента с начальным уровнем риска (КНУР) на выставление заявки с потенциальной непокрытой позицией
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :return: Запрос создаёт от имени указанного портфеля рыночную заявку c указанными в теле сообщения характеристиками
        """
        request = {'opcode': 'create:market', 'side': side, 'quantity': abs(quantity), 'instrument': {'exchange': exchange, 'symbol': symbol}, 'user': {'portfolio': portfolio}}
        if board: request['board'] = board
        if comment: request['comment'] = comment
        if time_in_force: request['timeInForce'] = time_in_force
        if allow_margin: request['allowMargin'] = allow_margin
        if check_duplicates: request['checkDuplicates'] = check_duplicates
        return self.send_websocket(request)

    def create_limit_order_websocket(self, portfolio, exchange, symbol, side, quantity, price,
                                     board=None, comment=None, time_in_force=None, allow_margin=None, iceberg_fixed=None, iceberg_variance=None, check_duplicates=None):  # https://alor.dev/docs/api/websocket/commands/CreateLimitOrder
        """Создание лимитной заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float price: Цена
        :param str comment: Пользовательский комментарий к заявке
        :param str time_in_force: Тип заявки: 'oneday' - до конца дня, 'immediateorcancel' - снять остаток, 'fillorkill' - исполнить целиком или отклонить, 'goodtillcancelled' - активна до отмены
        :param bool allow_margin: Флаг, подтверждающий согласие клиента с начальным уровнем риска (КНУР) на выставление заявки с потенциальной непокрытой позицией
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :return: Запрос создаёт от имени указанного портфеля лимитную заявку c указанными в теле сообщения характеристиками
        """
        request = {'opcode': 'create:limit', 'side': side, 'quantity': abs(quantity), 'price': price, 'instrument': {'exchange': exchange, 'symbol': symbol}, 'user': {'portfolio': portfolio}}
        if board: request['board'] = board
        if comment: request['comment'] = comment
        if time_in_force: request['timeInForce'] = time_in_force
        if allow_margin: request['allowMargin'] = allow_margin
        if iceberg_fixed: request['icebergFixed'] = iceberg_fixed
        if iceberg_variance: request['icebergVariance'] = iceberg_variance
        if check_duplicates: request['checkDuplicates'] = check_duplicates
        return self.send_websocket(request)

    def create_stop_order_websocket(self, portfolio, exchange, symbol, side, quantity, trigger_price,
                                    board=None, condition='Less', stop_end_unix_time=0, allow_margin=None, check_duplicates=None, protecting_seconds=None, activate=None):  # https://alor.dev/docs/api/websocket/commands/CreateStopOrder
        """Создание стоп-заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float trigger_price: Условная цена (цена срабатывания)
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str condition: Условие срабатывания 'More', 'Less', 'MoreOrEqual', 'LessOrEqual'
        :param int stop_end_unix_time: Срок действия (UTC) в формате Unix Time Seconds
        :param bool allow_margin: Флаг, подтверждающий согласие клиента с начальным уровнем риска (КНУР) на выставление заявки с потенциальной непокрытой позицией
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :param int protecting_seconds: Защитное время. Непрерывный период времени в секундах, в течение которого рыночная цена инструмента должна соответствовать указанным в заявке цене и условию срабатывания (1-300)
        :param bool activate: Флаг активной заявки
        :return: Запрос создаёт от имени указанного портфеля стоп-заявку c указанными в теле сообщения характеристиками
        """
        request = {'opcode': 'create:stop', 'side': side, 'quantity': abs(quantity), 'condition': condition, 'triggerPrice': trigger_price,
                   'stopEndUnixTime': stop_end_unix_time, 'instrument': {'symbol': symbol, 'exchange': exchange}, 'user': {'portfolio': portfolio}}
        if board: request['board'] = board
        if allow_margin: request['allowMargin'] = allow_margin
        if check_duplicates: request['checkDuplicates'] = check_duplicates
        if protecting_seconds: request['protectingSeconds'] = protecting_seconds
        if activate: request['activate'] = activate
        return self.send_websocket(request)

    def create_stop_limit_order_websocket(self, portfolio, exchange, symbol, side, quantity, trigger_price, price,
                                          board=None, condition='Less', stop_end_unix_time=0, time_in_force=None, allow_margin=None,
                                          iceberg_fixed=None, iceberg_variance=None, check_duplicates=None, protecting_seconds=None, activate=True):  # https://alor.dev/docs/api/websocket/commands/CreateStopLimitOrder
        """Создание стоп-лимитной заявки

        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float trigger_price: Стоп цена
        :param float price: Лимитная цена
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str condition: Условие срабатывания 'More', 'Less', 'MoreOrEqual', 'LessOrEqual'
        :param int stop_end_unix_time: Срок действия (UTC) в формате Unix Time Seconds
        :param str time_in_force: Тип заявки: 'oneday' - до конца дня, 'immediateorcancel' - снять остаток, 'fillorkill' - исполнить целиком или отклонить, 'goodtillcancelled' - активна до отмены
        :param bool allow_margin: Флаг, подтверждающий согласие клиента с начальным уровнем риска (КНУР) на выставление заявки с потенциальной непокрытой позицией
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :param int protecting_seconds: Защитное время. Непрерывный период времени в секундах, в течение которого рыночная цена инструмента должна соответствовать указанным в заявке цене и условию срабатывания (1-300)
        :param bool activate: Флаг активной заявки
        :return: Запрос создаёт от имени указанного портфеля стоп-лимитную заявку c указанными в теле сообщения характеристиками
        """
        request = {'opcode': 'create:stopLimit', 'side': side, 'quantity': abs(quantity), 'price': price, 'condition': condition, 'triggerPrice': trigger_price,
                   'stopEndUnixTime': stop_end_unix_time, 'instrument': {'symbol': symbol, 'exchange': exchange}, 'user': {'portfolio': portfolio}}
        if board: request['board'] = board
        if time_in_force: request['timeInForce'] = time_in_force
        if allow_margin: request['allowMargin'] = allow_margin
        if iceberg_fixed: request['icebergFixed'] = iceberg_fixed
        if iceberg_variance: request['icebergVariance'] = iceberg_variance
        if check_duplicates: request['checkDuplicates'] = check_duplicates
        if protecting_seconds: request['protectingSeconds'] = protecting_seconds
        if activate: request['activate'] = activate
        return self.send_websocket(request)

    def edit_market_order_websocket(self, order_id, portfolio, exchange, symbol, side, quantity,
                                    board=None, comment=None, time_in_force=None, allow_margin=None, check_duplicates=None):  # https://alor.dev/docs/api/websocket/commands/UpdateMarketOrder
        """Изменение рыночной заявки

        :param int order_id: Идентификатор заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param str comment: Пользовательский комментарий к заявке
        :param str time_in_force: Тип заявки: 'oneday' - до конца дня, 'immediateorcancel' - снять остаток, 'fillorkill' - исполнить целиком или отклонить, 'goodtillcancelled' - активна до отмены
        :param bool allow_margin: Флаг, подтверждающий согласие клиента с начальным уровнем риска (КНУР) на выставление заявки с потенциальной непокрытой позицией
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :return: Запрос создаёт новую рыночную заявку с изменёнными характеристиками, автоматически отменив созданную ранее. Для определения отменяемой заявки используется её номер в параметре orderid
        """
        request = {'opcode': 'update:market', 'orderId': order_id, 'side': side, 'quantity': abs(quantity), 'instrument': {'exchange': exchange, 'symbol': symbol}, 'user': {'portfolio': portfolio}}
        if board: request['board'] = board
        if comment: request['comment'] = comment
        if time_in_force: request['timeInForce'] = time_in_force
        if allow_margin: request['allowMargin'] = allow_margin
        if check_duplicates: request['checkDuplicates'] = check_duplicates
        return self.send_websocket(request)

    def edit_limit_order_websocket(self, order_id, portfolio, exchange, symbol, side, quantity, price,
                                   board=None, comment=None, time_in_force=None, allow_margin=None, iceberg_fixed=None, iceberg_variance=None, check_duplicates=None):  # https://alor.dev/docs/api/websocket/commands/UpdateLimitOrder
        """Изменение лимитной заявки

        :param int order_id: Идентификатор заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float price: Цена
        :param str comment: Пользовательский комментарий к заявке
        :param str time_in_force: Тип заявки: 'oneday' - до конца дня, 'immediateorcancel' - снять остаток, 'fillorkill' - исполнить целиком или отклонить, 'goodtillcancelled' - активна до отмены
        :param bool allow_margin: Флаг, подтверждающий согласие клиента с начальным уровнем риска (КНУР) на выставление заявки с потенциальной непокрытой позицией
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :return: Запрос создаёт новую лимитную заявку с изменёнными характеристиками, автоматически отменив созданную ранее. Для определения отменяемой заявки используется её номер в параметре orderid
        """
        request = {'opcode': 'update:limit', 'orderId': order_id, 'side': side, 'quantity': abs(quantity), 'price': price,
                   'instrument': {'exchange': exchange, 'symbol': symbol}, 'user': {'portfolio': portfolio}}
        if board: request['board'] = board
        if comment: request['comment'] = comment
        if time_in_force: request['timeInForce'] = time_in_force
        if allow_margin: request['allowMargin'] = allow_margin
        if iceberg_fixed: request['icebergFixed'] = iceberg_fixed
        if iceberg_variance: request['icebergVariance'] = iceberg_variance
        if check_duplicates: request['checkDuplicates'] = check_duplicates
        return self.send_websocket(request)

    def edit_stop_order_websocket(self, order_id, portfolio, exchange, symbol, side, quantity, trigger_price,
                                  board=None, condition='Less', stop_end_unix_time=0, allow_margin=None, check_duplicates=None, protecting_seconds=None, activate=None):  # https://alor.dev/docs/api/websocket/commands/UpdateStopOrder
        """Изменение стоп-заявки

        :param int order_id: Идентификатор заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float trigger_price: Условная цена (цена срабатывания)
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str condition: Условие срабатывания 'More', 'Less', 'MoreOrEqual', 'LessOrEqual'
        :param int stop_end_unix_time: Срок действия (UTC) в формате Unix Time Seconds
        :param bool allow_margin: Флаг, подтверждающий согласие клиента с начальным уровнем риска (КНУР) на выставление заявки с потенциальной непокрытой позицией
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :param int protecting_seconds: Защитное время. Непрерывный период времени в секундах, в течение которого рыночная цена инструмента должна соответствовать указанным в заявке цене и условию срабатывания (1-300)
        :param bool activate: Флаг активной заявки
        :return: Запрос создаёт новую стоп-заявку с изменёнными характеристиками, автоматически отменив созданную ранее. Для определения отменяемой заявки используется её номер в параметре orderid
        """
        request = {'opcode': 'update:stop', 'orderId': order_id, 'side': side, 'quantity': abs(quantity), 'condition': condition, 'triggerPrice': trigger_price,
                   'stopEndUnixTime': stop_end_unix_time, 'instrument': {'symbol': symbol, 'exchange': exchange}, 'user': {'portfolio': portfolio}}
        if board: request['board'] = board
        if allow_margin: request['allowMargin'] = allow_margin
        if check_duplicates: request['checkDuplicates'] = check_duplicates
        if protecting_seconds: request['protectingSeconds'] = protecting_seconds
        if activate: request['activate'] = activate
        return self.send_websocket(request)

    def edit_stop_limit_order_websocket(self, order_id, portfolio, exchange, symbol, side, quantity, trigger_price, price,
                                        board=None, condition='Less', stop_end_unix_time=0, time_in_force=None, allow_margin=None,
                                        iceberg_fixed=None, iceberg_variance=None, check_duplicates=None, protecting_seconds=None, activate=True):  # https://alor.dev/docs/api/websocket/commands/UpdateStopLimitOrder
        """Изменение стоп-лимитной заявки

        :param int order_id: Идентификатор заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param str side: Направление сделки: 'buy' - покупка, 'sell' - продажа
        :param int quantity: Количество (лоты)
        :param float trigger_price: Стоп цена
        :param float price: Лимитная цена
        :param str board: Режим торгов (борд). TQBR - акции, TQOB - облигации, RFUD - фьючерсы, ...
        :param str condition: Условие срабатывания 'More', 'Less', 'MoreOrEqual', 'LessOrEqual'
        :param int stop_end_unix_time: Срок действия (UTC) в формате Unix Time Seconds
        :param str time_in_force: Тип заявки: 'oneday' - до конца дня, 'immediateorcancel' - снять остаток, 'fillorkill' - исполнить целиком или отклонить, 'goodtillcancelled' - активна до отмены
        :param bool allow_margin: Флаг, подтверждающий согласие клиента с начальным уровнем риска (КНУР) на выставление заявки с потенциальной непокрытой позицией
        :param int iceberg_fixed: Видимая постоянная часть айсберг-заявки в лотах
        :param int iceberg_variance: Амплитуда отклонения (в % от icebergFixed) случайной надбавки к видимой части айсберг-заявки. Только срочный рынок
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :param int protecting_seconds: Защитное время. Непрерывный период времени в секундах, в течение которого рыночная цена инструмента должна соответствовать указанным в заявке цене и условию срабатывания (1-300)
        :param bool activate: Флаг активной заявки
        :return: Запрос создаёт новую стоп-лимитную заявку с изменёнными характеристиками, автоматически отменив созданную ранее. Для определения отменяемой заявки используется её номер в параметре orderid
        """
        request = {'opcode': 'update:stopLimit', 'orderId': order_id, 'side': side, 'quantity': abs(quantity), 'price': price, 'condition': condition, 'triggerPrice': trigger_price,
                   'stopEndUnixTime': stop_end_unix_time, 'instrument': {'symbol': symbol, 'exchange': exchange}, 'board': board, 'user': {'portfolio': portfolio}}
        if board: request['board'] = board
        if time_in_force: request['timeInForce'] = time_in_force
        if allow_margin: request['allowMargin'] = allow_margin
        if iceberg_fixed: request['icebergFixed'] = iceberg_fixed
        if iceberg_variance: request['icebergVariance'] = iceberg_variance
        if check_duplicates: request['checkDuplicates'] = check_duplicates
        if protecting_seconds: request['protectingSeconds'] = protecting_seconds
        if activate: request['activate'] = activate
        return self.send_websocket(request)

    def delete_market_order_websocket(self, order_id, portfolio, exchange, check_duplicates=None):  # https://alor.dev/docs/api/websocket/commands/DeleteMarketOrder
        """Снятие рыночной заявки

        :param int order_id: Идентификатор заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :return: Запрос снимает выставленную ранее рыночную заявку, если она по какой-либо причине не была удовлетворена. Для определения отменяемой заявки используется её номер в параметре orderid
        """
        request = {'opcode': 'delete:market', 'orderId': order_id, 'exchange': exchange, 'user': {'portfolio': portfolio}}
        if check_duplicates: request['checkDuplicates'] = check_duplicates
        return self.send_websocket(request)

    def delete_limit_order_websocket(self, order_id, portfolio, exchange, check_duplicates=None):  # https://alor.dev/docs/api/websocket/commands/DeleteLimitOrder
        """Снятие лимитной заявки

        :param int order_id: Идентификатор заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :return: Запрос снимает выставленную ранее лимитную заявку. Для определения отменяемой заявки используется её номер в параметре orderid
        """
        request = {'opcode': 'delete:limit', 'orderId': order_id, 'exchange': exchange, 'user': {'portfolio': portfolio}}
        if check_duplicates: request['checkDuplicates'] = check_duplicates
        return self.send_websocket(request)

    def delete_stop_order_websocket(self, order_id, portfolio, exchange, check_duplicates=None):  # https://alor.dev/docs/api/websocket/commands/DeleteStopOrder
        """Снятие стоп-заявки

        :param int order_id: Идентификатор заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :return: Запрос снимает выставленную ранее стоп-заявку. Для определения отменяемой заявки используется её номер в параметре orderid
        """
        request = {'opcode': 'delete:stop', 'orderId': order_id, 'exchange': exchange, 'user': {'portfolio': portfolio}}
        if check_duplicates: request['checkDuplicates'] = check_duplicates
        return self.send_websocket(request)

    def delete_stop_limit_order_websocket(self, order_id, portfolio, exchange, check_duplicates=None):  # https://alor.dev/docs/api/websocket/commands/DeleteStopLimitOrder
        """Снятие стоп-лимитной заявки

        :param int order_id: Идентификатор заявки
        :param str portfolio: Идентификатор клиентского портфеля
        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param bool check_duplicates: Флаг, отвечающий за проверку уникальности команд
        :return: Запрос снимает выставленную ранее стоп-лимитную заявку. Для определения отменяемой заявки используется её номер в параметре orderid
        """
        request = {'opcode': 'delete:stopLimit', 'orderId': order_id, 'exchange': exchange, 'user': {'portfolio': portfolio}}
        if check_duplicates: request['checkDuplicates'] = check_duplicates
        return self.send_websocket(request)

    # Запросы REST

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
        self.logger.debug(f'Запрос : {response.request.path_url}')
        self.logger.debug(f'Ответ  : {content}')
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

    @staticmethod
    def alor_board_to_board(alor_board):
        """Канонический код режима торгов из кода режима торгов Алор

        :param str alor_board: Код режима торгов Алор
        :return: Канонический код режима торгов
        """
        if alor_board == 'RFUD':  # Для фьючерсов
            return 'SPBFUT'
        if alor_board == 'ROPD':  # Для опционов
            return 'SPBOPT'
        return alor_board

    @staticmethod
    def board_to_alor_board(board):
        """Код режима торгов Алор из канонического кода режима торгов

        :param str board: Канонический код режима торгов
        :return: Код режима торгов Алор
        """
        if board == 'SPBFUT':  # Для фьючерсов
            return 'RFUD'
        if board == 'SPBOPT':  # Для опционов
            return 'ROPD'
        return board

    def dataname_to_alor_board_symbol(self, dataname) -> tuple[Union[str, None], str]:
        """Код режима торгов Алора и тикер из названия тикера

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
            si = next((self.get_symbol_info(exchange, symbol) for exchange in self.exchanges), None)  # Пробуем получить спецификацию тикера на всех биржах
            if si is None:  # Если спецификация тикера нигде не найдена
                return board, symbol  # то возвращаем без кода режима торгов
            board = si['board']  # Канонический код режима торгов
        alor_board = self.board_to_alor_board(board)  # Код режима торгов Алор
        return alor_board, symbol

    def alor_board_symbol_to_dataname(self, alor_board, symbol) -> str:
        """Название тикера из кода режима торгов и тикера

        :param str alor_board: Код режима торгов Алор
        :param str symbol: Тикер
        :return: Название тикера
        """
        return f'{self.alor_board_to_board(alor_board)}.{symbol}'

    def get_account(self, board, account_id=0) -> Union[dict, None]:
        """Счет из кода режима торгов и номера счета

        :param str board: Код режима торгов
        :param int account_id: Порядковый номер счета
        :return: Счет
        """
        return next((account for account in self.accounts if account['account_id'] == account_id and board in account['boards']), None)

    def get_exchange(self, alor_board, symbol):
        """Биржа тикера из кода режима торгов Алора и тикера

        :param str alor_board: Код режима торгов Алор
        :param str symbol: Тикер
        :return: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        """
        for exchange in self.exchanges:  # Пробегаемся по всем биржам
            si = self.get_symbol_info(exchange, symbol)  # Получаем информацию о тикере
            if si and si['board'] == alor_board:  # Если информация о тикере найдена, и режим торгов есть на бирже
                return exchange  # то биржа найдена
        self.logger.warning(f'Биржа для {alor_board}.{symbol} не найдена')
        return None  # Если биржа не была найдена, то возвращаем пустое значение

    def get_symbol_info(self, exchange, symbol, reload=False):
        """Спецификация тикера

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
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

    def price_to_valid_price(self, exchange, symbol, alor_price) -> Union[int, float]:
        """Перевод цены в цену, которую примет Алор в заявке

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер:param str class_code: Код режима торгов
        :param float alor_price: Цена в Алор
        :return: Цена, которую примет Алор в зявке
        """
        si = self.get_symbol_info(exchange, symbol)  # Информация о тикере
        min_price_step = si['minstep']  # Шаг цены
        valid_price = alor_price // min_price_step * min_price_step  # Цена должна быть кратна шагу цены
        decimals = si['decimals']  # Кол-во десятичных знаков
        if decimals > 0:  # Если задано кол-во десятичных знаков
            return round(valid_price, decimals)  # то округляем цену кратно шага цены, возвращаем ее
        return int(valid_price)  # Если кол-во десятичных знаков = 0, то переводим цену в целое число

    def price_to_alor_price(self, exchange, symbol, price) -> Union[int, float]:
        """Перевод цены в рублях за штуку в цену Алор

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param float price: Цена в рублях за штуку
        :return: Цена в Алор
        """
        si = self.get_symbol_info(exchange, symbol)  # Информация о тикере
        min_price_step = si['minstep']  # Шаг цены
        alor_price = price  # Изначально считаем, что цена не изменится
        primary_board = si['primary_board']  # Рынок тикера
        if primary_board in ('TQOB', 'TQCB', 'TQRD', 'TQIR'):  # Для облигаций (Т+ Гособлигации, Т+ Облигации, Т+ Облигации Д, Т+ Облигации ПИР)
            alor_price = price * 100 / si['facevalue']  # Пункты цены для котировок облигаций представляют собой проценты номинала облигации
        elif primary_board == 'RFUD':  # Для рынка фьючерсов
            lot_size = si['facevalue']  # Лот
            step_price = si['pricestep']  # Стоимость шага цены
            if lot_size > 1 and step_price:  # Если есть лот и стоимость шага цены
                lot_price = price * lot_size  # Цена в рублях за лот
                alor_price = lot_price * min_price_step / step_price  # Цена
        elif primary_board == 'CETS':  # Для валют
            alor_price = price / si.lot * si['facevalue']  # Цена
        return self.price_to_valid_price(exchange, symbol, alor_price)  # Возращаем цену, которую примет Алор в заявке

    def alor_price_to_price(self, exchange, symbol, alor_price) -> float:
        """Перевод цены Алор в цену в рублях за штуку

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param float alor_price: Цена в Алор
        :return: Цена в рублях за штуку
        """
        si = self.get_symbol_info(exchange, symbol)  # Спецификация тикера
        primary_board = si['primary_board']  # Код площадки
        if primary_board in ('TQOB', 'TQCB', 'TQRD', 'TQIR'):  # Для облигаций (Т+ Гособлигации, Т+ Облигации, Т+ Облигации Д, Т+ Облигации ПИР)
            return alor_price / 100 * si['facevalue']  # Пункты цены для котировок облигаций представляют собой проценты номинала облигации
        elif primary_board == 'RFUD':  # Для фьючерсов
            lot_size = si['facevalue']  # Лот
            step_price = si['pricestep']  # Стоимость шага цены
            if lot_size > 1 and step_price:  # Если есть лот и стоимость шага цены
                min_price_step = si['minstep']  # Шаг цены
                lot_price = alor_price // min_price_step * step_price  # Цена за лот
                return lot_price / lot_size  # Цена за штуку
        elif primary_board == 'CETS':  # Для валют
            return alor_price * si['lot'] / si['facevalue']
        return alor_price

    def lots_to_size(self, exchange, symbol, lots) -> int:
        """Перевод лотов в штуки

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param int lots: Кол-во лотов
        :return: Кол-во штук
        """
        si = self.get_symbol_info(exchange, symbol)  # Спецификация тикера
        if si:  # Если тикер найден
            lot_size = si['lotsize']  # Кол-во штук в лоте
            if lot_size:  # Если задано кол-во штук в лоте
                return int(lots * lot_size)  # то возвращаем кол-во в штуках
        return lots  # В остальных случаях возвращаем количество в лотах

    def size_to_lots(self, exchange, symbol, size) -> int:
        """Перевод штуки в лоты

        :param str exchange: Код биржи: 'MOEX' — Московская биржа, 'SPBX' — СПБ Биржа
        :param str symbol: Тикер
        :param int size: Кол-во штук
        :return: Кол-во лотов
        """
        si = self.get_symbol_info(exchange, symbol)  # Спецификация тикера
        if si:  # Если тикер найден
            lot_size = int(si['lotsize'])  # Кол-во штук в лоте
            if lot_size:  # Если задано кол-во штук
                return size // lot_size  # то возвращаем количество в лотах
        return size  # В остальных случаях возвращаем кол-во в штуках

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
