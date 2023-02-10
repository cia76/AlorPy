from datetime import datetime
from time import time_ns  # Текущее время в наносекундах, прошедших с 01.01.1970 UTC
from pytz import timezone, utc  # Работаем с временнОй зоной и UTC
from uuid import uuid4  # Номера подписок должны быть уникальными во времени и пространстве
from json import loads, JSONDecodeError, dumps  # Сервер WebSockets работает с JSON сообщениями
from requests import post, get, put, delete  # Запросы/ответы от сервера запросов
from websockets import connect, ConnectionClosed  # Работа с сервером WebSockets
from asyncio import create_task, run, CancelledError  # Работа с асинхронными функциями
from threading import Thread  # Подписки сервера WebSockets будем получать в отдельном потоке


class Singleton(type):
    """Метакласс для создания Singleton классов"""
    def __init__(cls, *args, **kwargs):
        """Инициализация класса"""
        super(Singleton, cls).__init__(*args, **kwargs)
        cls._singleton = None  # Экземпляра класса еще нет

    def __call__(cls, *args, **kwargs):
        """Вызов класса"""
        if cls._singleton is None:  # Если класса нет в экземплярах класса
            cls._singleton = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._singleton  # Возвращаем экземпляр класса


class AlorPy(metaclass=Singleton):  # Singleton класс
    """Работа с Alor OpenAPI V2 из Python https://alor.dev/docs"""
    tzMsk = timezone('Europe/Moscow')  # Время UTC в Alor OpenAPI будем приводить к московскому времени
    jwtTokenTTL = 60  # Время жизни токена JWT в секундах
    exchanges = ('MOEX', 'SPBX',)  # Биржи

    def DefaultHandler(self, response):
        """Пустой обработчик события по умолчанию. Его можно заменить на пользовательский"""
        pass

    # Функции для запросов/ответов

    def GetJWTToken(self):
        """Получение, выдача, обновление JWT токена"""
        now = int(datetime.timestamp(datetime.now()))  # Текущая дата/время в виде UNIX времени в секундах
        if self.jwtToken is None or now - self.jwtTokenIssued > self.jwtTokenTTL:  # Если токен JWT не был выдан или был просрочен
            response = post(url=f'{self.oauthServer}/refresh', params={'token': self.refreshToken})  # Запрашиваем новый JWT токен с сервера аутентификации
            if response.status_code != 200:  # Если при получение возникла ошибка
                print(f'Ошибка получения JWT токена: {response.status_code}')
                self.jwtToken = None  # Сбрасываем токен JWT
                self.jwtTokenIssued = 0  # Сбрасываем время выдачи токена JWT
            token = response.json()  # Читаем данные JSON
            self.jwtToken = token.get('AccessToken')  # Получаем токен JWT
            self.jwtTokenIssued = now  # Дата выдачи токена JWT
        return self.jwtToken

    def UTCTimeStampToMskDatetime(self, seconds):
        """Перевод кол-ва секунд, прошедших с 01.01.1970 00:00 UTC в московское время

        :param int seconds: Кол-во секунд, прошедших с 01.01.1970 00:00 UTC
        :return: Московское время без временнОй зоны
        """
        dt_utc = datetime.utcfromtimestamp(seconds)  # Переводим кол-во секунд, прошедших с 01.01.1970 в UTC
        return self.UTCToMskDateTime(dt_utc)  # Переводим время из UTC в московское

    def MskDatetimeToUTCTimeStamp(self, dt):
        """Перевод московского времени в кол-во секунд, прошедших с 01.01.1970 00:00 UTC

        :param datetime dt: Московское время
        :return: Кол-во секунд, прошедших с 01.01.1970 00:00 UTC
        """
        dt_msk = self.tzMsk.localize(dt)  # Заданное время ставим в зону МСК
        return int(dt_msk.timestamp())  # Переводим в кол-во секунд, прошедших с 01.01.1970 в UTC

    def UTCToMskDateTime(self, dt):
        """Перевод времени из UTC в московское

        :param datetime dt: Время UTC
        :return: Московское время
        """
        dt_msk = utc.localize(dt).astimezone(self.tzMsk)  # Переводим UTC в МСК
        return dt_msk.replace(tzinfo=None)  # Убираем временнУю зону

    def GetHeaders(self):
        """Получение хедеров для запросов"""
        return {'Content-Type': 'application/json', 'Authorization': f'Bearer {self.GetJWTToken()}'}

    def GetRequestId(self):
        """Получение уникального кода запроса"""
        return f'{self.userName}{time_ns()}'  # Логин и текущее время в наносекундах, прошедших с 01.01.1970 в UTC

    @staticmethod
    def CheckResult(response):
        """Анализ результата запроса

        :param response response: Результат запроса
        :return: Справочник из JSON, текст, None в случае веб ошибки
        """
        if response.status_code != 200:  # Если статус ошибки
            print('Response Web Error:', response.status_code, response.content.decode('utf-8'), response.request)  # Декодируем и выводим ошибку
            return None  # то возвращаем пустое значение
        content = response.content.decode('utf-8')  # Значение
        try:
            return loads(content)  # Декодируем JSON в справочник, возвращаем его. Ошибки также могут приходить в виде JSON
        except JSONDecodeError:  # Если произошла ошибка при декодировании JSON, например, при удалении заявок
            return content  # то возвращаем значение в виде текста

    # Работа с WebSocket

    async def WebSocketAsync(self):
        """Подключение к серверу WebSocket и получение с него подписок"""
        try:
            self.webSocket = await connect(self.wsServer)  # Подключаемся к серверу WebSocket
            print(datetime.now(self.tzMsk).strftime("%d.%m.%Y %H:%M:%S"), '- WebSocket Task: Connected')
            if len(self.subscriptions) > 0:  # Если есть подписки
                print(f'Возобновление подписок ({len(self.subscriptions)})')
                resubscribe = self.subscriptions.copy()  # Подписки, которые были до этого, удалим
                self.subscriptions.clear()  # Удаляем подписки из списка
                for s in resubscribe:  # Пробегаемся по всем подпискам
                    request = list(s.values())[0]  # Извлекаем запрос из подписки
                    # Дублируем функционал WebSocketSend, чтобы не попасть в петлю сервера/запросов при переподключении
                    guid = str(uuid4())  # Уникальный идентификатор создаваемой подписки
                    subscriptionRequest = request.copy()  # Копируем запрос в подписку
                    sub = {guid: subscriptionRequest}
                    if subscriptionRequest['opcode'] == 'BarsGetAndSubscribe':  # Для подписки на новые бары добавляем атрибуты
                        sub['mode'] = 0  # 0 - история, 1 - первый несформированный бар, 2 - новый бар
                        sub['last'] = 0  # Время последнего бара
                        sub['same'] = 1  # Кол-во повторяющихся баров
                        sub['prev'] = None  # Предыдущий ответ
                    self.subscriptions.append(sub)  # Заносим подписку в список
                    request['token'] = self.GetJWTToken()  # Получаем JWT токен, ставим его в запрос
                    request['guid'] = guid  # Уникальный идентификатор подписки тоже ставим в запрос
                    await self.webSocket.send(dumps(request))  # Отправляем запрос
            self.webSocketReady = True  # Готов принимать запросы
            print(datetime.now(self.tzMsk).strftime("%d.%m.%Y %H:%M:%S"), '- WebSocket Task: Listening')
            while True:  # Слушаем ответ до отмены
                responseJson = await self.webSocket.recv()  # Ожидаем следующую строку в виде JSON
                response = loads(responseJson)  # Переводим JSON в словарь
                if 'data' not in response:  # Если пришло сервисное сообщение о подписке/отписке
                    continue  # то его не разбираем, пропускаем
                sub = next((item for item in self.subscriptions if response['guid'] in item), None)  # Поиск подписки по GUID
                if sub is None:  # Если подписка не найдена
                    continue  # то мы не можем сказать, что это за подписка, пропускаем ее
                response['subscription'] = sub[response['guid']]  # Ставим информацию о подписке в ответ
                opcode = response['subscription']['opcode']  # Разбираем по типу подписки
                if opcode == 'OrderBookGetAndSubscribe':  # Биржевой стакан
                    self.OnChangeOrderBook(response)
                elif opcode == 'BarsGetAndSubscribe':  # Новый бар
                    # print(f'DEBUG: {datetime.now()} - {response["data"]}')
                    seconds = response['data']['time']  # Время пришедшего бара
                    if sub['mode'] == 0:  # История
                        if seconds != sub['last']:  # Если пришел следующий бар истории
                            sub['last'] = seconds  # то запоминаем его
                            if sub['prev'] is not None:  # Мы не знаем, когда придет первый дубль
                                self.OnNewBar(sub['prev'])  # Поэтому, выдаем бар с задержкой на 1
                        else:  # Если пришел дубль
                            sub['same'] = 2  # Есть 2 одинаковых бара
                            sub['mode'] = 1  # Переходим к обработке первого несформированного бара
                    elif sub['mode'] == 1:  # Первый несформированный бар
                        if sub['same'] < 3:  # Если уже есть 2 одинаковых бара
                            sub['same'] += 1  # то следующий бар будет таким же. 3 одинаковых бара
                        else:  # Если пришел следующий бар
                            sub['last'] = seconds  # то запоминаем бар
                            sub['same'] = 1  # Повторов нет
                            sub['mode'] = 2  # Переходим к обработке новых баров
                            self.OnNewBar(sub['prev'])
                    elif sub['mode'] == 2:  # Новый бар
                        if sub['same'] < 2:  # Если нет повторов
                            sub['same'] += 1  # то следующий бар будет таким же. 2 одинаковых бара
                        else:  # Если пришел следующий бар
                            sub['last'] = seconds  # то запоминаем бар
                            sub['same'] = 1  # Повторов нет
                            self.OnNewBar(sub['prev'])
                    sub['prev'] = response  # Запоминаем пришедший бар
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
                elif opcode == 'OrdersGetAndSubscribeV2':  # Заявки
                    self.OnOrder(response)
                elif opcode == 'InstrumentsGetAndSubscribeV2':  # Информация о финансовых инструментах
                    self.OnSymbol(response)
        except CancelledError:  # Если задачу отменили
            print(datetime.now(self.tzMsk).strftime("%d.%m.%Y %H:%M:%S"), '- WebSocket Task: Canceled')
            raise   # Передаем исключение на уровень WebSocketHandler
        except ConnectionClosed:  # При отключении от сервера WebSockets
            print(datetime.now(self.tzMsk).strftime("%d.%m.%Y %H:%M:%S"), '- WebSocket Task: Disconnected')
        except OSError:  # Если был таймаут на websockets
            print('WebSocket Task: Timeout')
        except Exception as ex:  # Другие типы ошибок
            print(datetime.now(self.tzMsk).strftime("%d.%m.%Y %H:%M:%S"), '- WebSocket Task: Error', ex)
        finally:
            self.webSocketReady = False  # Не готов принимать запросы
            self.webSocket = None  # Сбрасываем подключение

    async def WebSocketHandler(self):
        """Запуск и управление задачей подписок"""
        print(datetime.now(self.tzMsk).strftime("%d.%m.%Y %H:%M:%S"), '- WebSocket Thread: Started')
        while True:  # Будем держать соединение с сервером WebSocket до отмены
            self.webSocketTask = create_task(self.WebSocketAsync())  # Запускаем задачу подключения к серверу WebSocket и получения с него подписок
            try:
                await self.webSocketTask  # Ожидаем отмены задачи
            except CancelledError:  # Если задачу отменили
                break  # то выходим, дальше не продолжаем
        dt = datetime.now(self.tzMsk)  # Берем текущее время на рынке
        print(dt.strftime("%d.%m.%Y %H:%M:%S"), '- WebSocket Thread: Completed')

    def WebSocketSend(self, request):
        """Отправка запроса подписки на сервер WebSocket

        :param request request: Запрос
        :return: Уникальный идентификатор подписки
        """
        if not self.webSocketReady:  # Если WebSocket не готов принимать запросы
            print(datetime.now(self.tzMsk).strftime("%d.%m.%Y %H:%M:%S"), '- WebSocket Thread: Starting')
            Thread(target=run, args=(self.WebSocketHandler(),)).start()  # то создаем и запускаем поток управления подписками
        while not self.webSocketReady:  # Подключение к серверу WebSocket выполняется в отдельном потоке
            pass  # Подождем, пока WebSocket не будет готов принимать запросы
        guid = str(uuid4())  # Уникальный идентификатор создаваемой подписки для сообщений
        subscriptionRequest = request.copy()  # Копируем запрос в подписку
        sub = {guid: subscriptionRequest}
        if subscriptionRequest['opcode'] == 'BarsGetAndSubscribe':  # Для подписки на новые бары добавляем атрибуты
            sub['mode'] = 0  # 0 - история, 1 - первый несформированный бар, 2 - новый бар
            sub['last'] = 0  # Время последнего бара
            sub['same'] = 1  # Кол-во повторяющихся баров
            sub['prev'] = None  # Предыдущий ответ
        self.subscriptions.append(sub)  # Заносим подписку в список
        request['token'] = self.GetJWTToken()  # Получаем JWT токен, ставим его в запрос
        request['guid'] = guid  # Уникальный идентификатор подписки тоже ставим в запрос
        run(self.webSocket.send(dumps(request)))  # Отправляем запрос
        return guid

    # Инициализация и вход

    def __init__(self, UserName, RefreshToken, Demo=False):
        """Инициализация
        :param str UserName: Имя пользователя
        :param str RefreshToken: Токен
        :param bool Demo: Режим демо торговли. По умолчанию установлен режим реальной торговли
        """
        self.oauthServer = f'https://oauth{"dev" if Demo else ""}.alor.ru'  # Сервер аутентификации
        self.apiServer = f'https://api{"dev" if Demo else ""}.alor.ru'  # Сервер запросов
        self.wsServer = f'wss://api{"dev" if Demo else ""}.alor.ru/ws'  # Сервер подписок и событий WebSocket

        self.userName = UserName  # Имя пользователя
        self.refreshToken = RefreshToken  # Токен

        self.jwtToken = None  # Токен JWT
        self.jwtTokenIssued = 0  # UNIX время в секундах выдачи токена JWT

        self.webSocketTask = None  # Задача управления подписками WebSocket
        self.webSocket = None  # Подключение к серверу WebSocket
        self.webSocketReady = False  # WebSocket готов принимать запросы
        self.subscriptions = []  # Список подписок

        self.OnChangeOrderBook = self.DefaultHandler  # Биржевой стакан
        self.OnNewBar = self.DefaultHandler  # Новый бар
        self.OnNewQuotes = self.DefaultHandler  # Котировки
        self.OnAllTrades = self.DefaultHandler  # Все сделки
        self.OnPosition = self.DefaultHandler  # Позиции по ценным бумагам и деньгам
        self.OnSummary = self.DefaultHandler  # Сводная информация по портфелю
        self.OnRisk = self.DefaultHandler  # Портфельные риски
        self.OnSpectraRisk = self.DefaultHandler  # Риски срочного рынка (FORTS)
        self.OnTrade = self.DefaultHandler  # Сделки
        self.OnStopOrder = self.DefaultHandler  # Стоп заявки
        self.OnOrder = self.DefaultHandler  # Заявки
        self.OnSymbol = self.DefaultHandler  # Информация о финансовых инструментах

    def __enter__(self):
        """Вход в класс, например, с with"""
        return self

    # Информация о клиенте

    def GetPortfolios(self):
        """Получение списка серверов портфелей"""
        return self.CheckResult(get(url=f'{self.apiServer}/client/v1.0/users/{self.userName}/portfolios', headers=self.GetHeaders()))

    def GetOrders(self, portfolio, exchange):
        """Получение информации о всех заявках

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/clients/{exchange}/{portfolio}/orders', headers=self.GetHeaders()))

    def GetOrder(self, portfolio, exchange, orderId):
        """Получение информации о выбранной заявке

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int orderId: Номер заявки на бирже
        """
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/clients/{exchange}/{portfolio}/orders/{orderId}', headers=self.GetHeaders()))

    def GetMoney(self, portfolio, exchange):
        """Получение информации по деньгам для выбранного портфеля

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/clients/legacy/{exchange}/{portfolio}/money', headers=self.GetHeaders()))

    def GetPortfolioSummary(self, portfolio, exchange):
        """Получение информации о портфеле

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/clients/{exchange}/{portfolio}/summary', headers=self.GetHeaders()))

    def GetPositions(self, portfolio, exchange, withoutCurrency=False):
        """Получение информации о позициях

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param bool withoutCurrency: Исключить из ответа все денежные инструменты, по умолчанию false
        """
        params = {'withoutCurrency': withoutCurrency}
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/Clients/{exchange}/{portfolio}/positions', params=params, headers=self.GetHeaders()))

    def GetPosition(self, portfolio, exchange, symbol):
        """Получение информации о позициях выбранного инструмента

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        """
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/Clients/{exchange}/{portfolio}/positions/{symbol}', headers=self.GetHeaders()))

    def GetTrades(self, portfolio, exchange):
        """Получение информации о сделках

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/Clients/{exchange}/{portfolio}/trades', headers=self.GetHeaders()))

    def GetTrade(self, portfolio, exchange, symbol):
        """Получение информации о сделках по выбранному инструменту

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        """
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/Clients/{exchange}/{portfolio}/{symbol}/trades', headers=self.GetHeaders()))

    def GetFortsRisk(self, portfolio, exchange):
        """Получение информации о рисках на срочном рынке

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/Clients/{exchange}/{portfolio}/fortsrisk', headers=self.GetHeaders()))

    def GetRisk(self, portfolio, exchange):
        """Получение информации о рисках

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/Clients/{exchange}/{portfolio}/risk/', headers=self.GetHeaders()))

    def GetTradesHistory(self, portfolio, exchange, dateFrom=None, idFrom=None, limit=None, descending=None):
        """Получение истории сделок

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str dateFrom: Начиная с какой даты отдавать историю сделок. Например, '2021-10-13'
        :param int idFrom: Начиная с какого ID (номера сделки) отдавать историю сделок
        :param int limit: Ограничение на количество выдаваемых результатов поиска
        :param bool descending: Флаг обратной сортировки выдачи
        """
        params = {}
        if dateFrom is not None:
            params['dateFrom'] = dateFrom
        if idFrom is not None:
            params['from'] = idFrom
        if limit is not None:
            params['limit'] = limit
        if descending is not None:
            params['descending'] = descending
        if params == {}:
            return self.CheckResult(get(url=f'{self.apiServer}/md/stats/{exchange}/{portfolio}/history/trades', headers=self.GetHeaders()))
        return self.CheckResult(get(url=f'{self.apiServer}/md/stats/{exchange}/{portfolio}/history/trades', params=params, headers=self.GetHeaders()))

    def GetTradesSymbol(self, portfolio, exchange, symbol, dateFrom=None, idFrom=None, limit=None, descending=None):
        """Получение истории сделок (один тикер)

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str dateFrom: Начиная с какой даты отдавать историю сделок. Например, '2021-10-13'
        :param int idFrom: Начиная с какого ID (номера сделки) отдавать историю сделок
        :param int limit: Ограничение на количество выдаваемых результатов поиска
        :param bool descending: Флаг загрузки элементов с конца списка
        """
        params = {}
        if dateFrom is not None:
            params['dateFrom'] = dateFrom
        if idFrom is not None:
            params['from'] = idFrom
        if limit is not None:
            params['limit'] = limit
        if descending is not None:
            params['descending'] = descending
        if params == {}:
            return self.CheckResult(get(url=f'{self.apiServer}/md/stats/{exchange}/{portfolio}/history/trades/{symbol}', headers=self.GetHeaders()))
        return self.CheckResult(get(url=f'{self.apiServer}/md/stats/{exchange}/{portfolio}/history/trades/{symbol}', params=params, headers=self.GetHeaders()))

    def GetStopOrders(self, portfolio, exchange):
        """Получение информации о стоп-заявках

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/clients/{exchange}/{portfolio}/stoporders', headers=self.GetHeaders()))

    def GetStopOrder(self, portfolio, exchange, orderId):
        """Получение информации о выбранной стоп-заявке

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int orderId: Номер заявки на бирже
        """
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/clients/{exchange}/{portfolio}/stoporders/{orderId}', headers=self.GetHeaders()))

    # Ценные бумаги / инструменты

    def GetSecurities(self, symbol, limit=None, offset=None, sector=None, cficode=None, exchange=None):
        """Получение информации о торговых инструментах

        :param str symbol: Маска тикера. Например SB выведет SBER, SBERP, SBRB ETF и пр.
        :param int limit: Ограничение на количество выдаваемых результатов поиска
        :param int offset: Смещение начала выборки (для пагинации)
        :param str sector: Рынок на бирже. FOND, FORTS, CURR
        :param str cficode: Код финансового инструмента по стандарту ISO 10962. EXXXXX
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        params = {'query': symbol}
        if limit is not None:
            params['limit'] = limit
        if offset is not None:
            params['offset'] = offset
        if sector is not None:
            params['sector'] = sector
        if cficode is not None:
            params['cficode'] = cficode
        if exchange is not None:
            params['exchange'] = exchange
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/Securities', params=params, headers=self.GetHeaders()))

    def GetSecuritiesExchange(self, exchange):
        """Получение информации о торговых инструментах на выбранной бирже

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        """
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/Securities/{exchange}', headers=self.GetHeaders()))

    def GetSymbol(self, exchange, symbol):
        """Получение информации о выбранном финансовом инструменте

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        """
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/Securities/{exchange}/{symbol}', headers=self.GetHeaders()))

    def GetQuotes(self, symbols):
        """Получение информации о котировках для выбранных инструментов

        :param str symbols: Принимает несколько пар биржа-тикер. Пары отделены запятыми. Биржа и тикер разделены двоеточием.
        Пример: MOEX:SBER,MOEX:GAZP,SPBX:AAPL
        """
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/Securities/{symbols}/quotes', headers=self.GetHeaders()))

    def GetOrderBook(self, exchange, symbol, depth=20):
        """Получение информации о биржевом стакане

        :param exchange: Биржа 'MOEX' или 'SPBX'
        :param symbol: Тикер
        :param depth: Глубина стакана. Стандартное и максимальное значение - 20 (20х20)
        """
        params = {'depth': depth}
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/orderbooks/{exchange}/{symbol}', params=params, headers=self.GetHeaders()))

    def GetAllTrades(self, exchange, symbol, secondsFrom=None, secondsTo=None, take=None, descending=None):
        """Получение информации о всех сделках по ценным бумагам за сегодня

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param int secondsFrom: Дата и время UTC в секундах для первой запрашиваемой сделки
        :param int secondsTo: Дата и время UTC в секундах для первой запрашиваемой сделки
        :param int take: Количество загружаемых элементов
        :param bool descending: Флаг загрузки элементов с конца списка
        """
        params = {}
        if secondsFrom is not None:
            params['from'] = secondsFrom
        if secondsTo is not None:
            params['to'] = secondsTo
        if take is not None:
            params['take'] = take
        if descending is not None:
            params['descending'] = descending
        if params == {}:
            return self.CheckResult(get(url=f'{self.apiServer}/md/v2/Securities/{exchange}/{symbol}/alltrades', headers=self.GetHeaders()))
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/Securities/{exchange}/{symbol}/alltrades', params=params, headers=self.GetHeaders()))

    def GetActualFuturesQuote(self, exchange, symbol):
        """Получение котировки по ближайшему фьючерсу (код)

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        """
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/Securities/{exchange}/{symbol}/actualFuturesQuote', headers=self.GetHeaders()))

    def GetRiskRates(self, exchange, symbol=None, riskCategoryId=None, search=None):
        """Запрос ставок риска

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер, код инструмента, ISIN для облигаций
        :param int riskCategoryId: Id вашей (или той которая интересует) категории риска. Можно получить из запроса информации по клиенту или через кабинет клиента
        :param str search: Часть Тикера, кода инструмента, ISIN для облигаций. Вернет все совпадения, начинающиеся с
        """
        params = {'exchange': exchange}
        if symbol is not None:
            params['symbol'] = symbol
        if riskCategoryId is not None:
            params['riskCategoryId'] = riskCategoryId
        if search is not None:
            params['search'] = search
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/risk/rates', params=params, headers=self.GetHeaders()))

    def GetHistory(self, exchange, symbol, tf, secondsFrom=0, secondsTo=32536799999, untraded=False):
        """Запрос истории рынка для выбранных биржи и финансового инструмента

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str tf: Длительность таймфрейма в секундах или код ("D" - дни, "W" - недели, "M" - месяцы, "Y" - годы)
        :param int secondsFrom: Дата и время UTC в секундах для первого запрашиваемого бара
        :param int secondsTo: Дата и время UTC в секундах для последнего запрашиваемого бара
        :paran bool untraded: Флаг для поиска данных по устаревшим или экспирированным инструментам. При использовании требуется точное совпадение тикера
        """
        params = {'exchange': exchange, 'symbol': symbol, 'tf': tf, 'from': secondsFrom, 'to': secondsTo, 'untraded': untraded}
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/history', params=params, headers=self.GetHeaders()))

    # Другое

    def GetTime(self):
        """Запрос текущего UTC времени в секундах на сервере
        Если этот запрос выполнен без авторизации, то будет возвращено время, которое было 15 минут назад
        """
        return self.CheckResult(get(url=f'{self.apiServer}/md/v2/time', headers=self.GetHeaders()))

    # Работа с заявками

    def CreateMarketOrder(self, portfolio, exchange, symbol, side, quantity):
        """Создание рыночной заявки

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        """
        headers = self.GetHeaders()
        headers['X-ALOR-REQID'] = f'{portfolio};{self.GetRequestId()}'  # Портфель с уникальным идентификатором запроса
        j = {'side': side, 'type': 'market', 'quantity': abs(quantity), 'instrument': {'symbol': symbol, 'exchange': exchange}, 'user': {'portfolio': portfolio}}
        return self.CheckResult(post(url=f'{self.apiServer}/commandapi/warptrans/TRADE/v2/client/orders/actions/market', headers=headers, json=j))

    def CreateLimitOrder(self, portfolio, exchange, symbol, side, quantity, limitPrice):
        """Создание лимитной заявки

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float limitPrice: Лимитная цена
        """
        headers = self.GetHeaders()
        headers['X-ALOR-REQID'] = f'{portfolio};{self.GetRequestId()}'  # Портфель с уникальным идентификатором запроса
        j = {'side': side, 'type': 'limit', 'quantity': abs(quantity), 'price': limitPrice, 'instrument': {'symbol': symbol, 'exchange': exchange}, 'user': {'portfolio': portfolio}}
        return self.CheckResult(post(url=f'{self.apiServer}/commandapi/warptrans/TRADE/v2/client/orders/actions/limit', headers=headers, json=j))

    def CreateStopLossOrder(self, tradeServerCode, account, portfolio, exchange, symbol, side, quantity, stopPrice, secondsOrderEnd=0):
        """Создание стоп-лосс заявки

        :param str tradeServerCode: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stopPrice: Стоп цена
        :param int secondsOrderEnd: Дата и время UTC в секундах завершения сделки
        """
        headers = self.GetHeaders()
        headers['X-ALOR-REQID'] = self.GetRequestId()  # Уникальный идентификатор запроса
        j = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': stopPrice, 'Instrument': {'Symbol': symbol, 'Exchange': exchange}, 'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': secondsOrderEnd}
        return self.CheckResult(post(url=f'{self.apiServer}/warptrans/{tradeServerCode}/v2/client/orders/actions/stopLoss', headers=headers, json=j))

    def CreateTakeProfitOrder(self, tradeServerCode, account, portfolio, exchange, symbol, side, quantity, stopPrice, secondsOrderEnd=0):
        """Создание стоп-заявки

        :param str tradeServerCode: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stopPrice: Стоп цена
        :param int secondsOrderEnd: Дата и время UTC в секундах завершения сделки
        """
        headers = self.GetHeaders()
        headers['X-ALOR-REQID'] = self.GetRequestId()  # Уникальный идентификатор запроса
        j = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': stopPrice, 'Instrument': {'Symbol': symbol, 'Exchange': exchange}, 'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': secondsOrderEnd}
        return self.CheckResult(post(url=f'{self.apiServer}/warptrans/{tradeServerCode}/v2/client/orders/actions/takeProfit', headers=headers, json=j))

    def CreateTakeProfitLimitOrder(self, tradeServerCode, account, portfolio, exchange, symbol, side, quantity, stopPrice, limitPrice, secondsOrderEnd=0):
        """Создание стоп-лимит заявки

        :param str tradeServerCode: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stopPrice: Стоп цена
        :param float limitPrice: Лимитная цена
        :param int secondsOrderEnd: Дата и время UTC в секундах завершения сделки
        """
        headers = self.GetHeaders()
        headers['X-ALOR-REQID'] = self.GetRequestId()  # Уникальный идентификатор запроса
        j = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': stopPrice, 'Price': limitPrice, 'Instrument': {'Symbol': symbol, 'Exchange': exchange}, 'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': secondsOrderEnd}
        return self.CheckResult(post(url=f'{self.apiServer}/warptrans/{tradeServerCode}/v2/client/orders/actions/takeProfitLimit', headers=headers, json=j))

    def CreateStopLossLimitOrder(self, tradeServerCode, account, portfolio, exchange, symbol, side, quantity, stopPrice, limitPrice, secondsOrderEnd=0):
        """Создание стоп-лосс лимит заявки

        :param str tradeServerCode: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stopPrice: Стоп цена
        :param float limitPrice: Лимитная цена
        :param int secondsOrderEnd: Дата и время UTC в секундах завершения сделки
        """
        headers = self.GetHeaders()
        headers['X-ALOR-REQID'] = self.GetRequestId()  # Уникальный идентификатор запроса
        j = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': stopPrice, 'Price': limitPrice, 'Instrument': {'Symbol': symbol, 'Exchange': exchange}, 'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': secondsOrderEnd}
        return self.CheckResult(post(url=f'{self.apiServer}/warptrans/{tradeServerCode}/v2/client/orders/actions/stopLossLimit', headers=headers, json=j))

    def EditMarketOrder(self, account, portfolio, exchange, orderId, symbol, side, quantity):
        """Изменение рыночной заявки

        :param str account: Счет
        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int orderId: Номер заявки
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        """
        headers = self.GetHeaders()
        headers['X-ALOR-REQID'] = f'{portfolio};{orderId};{quantity}'  # Портфель с уникальным идентификатором запроса и кол-вом в лотах
        j = {'side': side, 'type': 'market', 'id': orderId, 'quantity': abs(quantity), 'instrument': {'symbol': symbol, 'exchange': exchange}, 'user': {'account': account, 'portfolio': portfolio}}
        return self.CheckResult(put(url=f'{self.apiServer}/commandapi/warptrans/TRADE/v2/client/orders/actions/market/{orderId}', headers=headers, json=j))

    def EditLimitOrder(self, portfolio, exchange, orderId, symbol, side, quantity, limitPrice):
        """Изменение лимитной заявки

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int orderId: Номер заявки
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float limitPrice: Лимитная цена
        """
        headers = self.GetHeaders()
        headers['X-ALOR-REQID'] = f'{portfolio};{orderId};{quantity}'  # Портфель с уникальным идентификатором запроса и кол-вом в лотах
        j = {'side': side, 'type': 'limit', 'quantity': abs(quantity), 'price': limitPrice, 'instrument': {'symbol': symbol, 'exchange': exchange}, 'user': {'portfolio': portfolio}}
        return self.CheckResult(put(url=f'{self.apiServer}/commandapi/warptrans/TRADE/v2/client/orders/actions/limit/{orderId}', headers=headers, json=j))

    def EditStopLossOrder(self, tradeServerCode, account, portfolio, exchange, orderId, symbol, side, quantity, stopPrice, secondsOrderEnd=0):
        """Изменение стоп-лосс заявки

        :param str tradeServerCode: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int orderId: Номер заявки
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stopPrice: Стоп цена
        :param int secondsOrderEnd: Дата и время UTC в секундах завершения сделки
        """
        headers = self.GetHeaders()
        headers['X-ALOR-REQID'] = self.GetRequestId()  # Уникальный идентификатор запроса
        j = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': stopPrice, 'Instrument': {'Symbol': symbol, 'Exchange': exchange}, 'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': secondsOrderEnd}
        return self.CheckResult(put(url=f'{self.apiServer}/warptrans/{tradeServerCode}/v2/client/orders/actions/stopLoss/{orderId}', headers=headers, json=j))

    def EditTakeProfitOrder(self, tradeServerCode, account, portfolio, exchange, orderId, symbol, side, quantity, stopPrice, secondsOrderEnd=0):
        """Изменение стоп-заявки

        :param str tradeServerCode: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int orderId: Номер заявки
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stopPrice: Стоп цена
        :param int secondsOrderEnd: Дата и время UTC в секундах завершения сделки
        """
        headers = self.GetHeaders()
        headers['X-ALOR-REQID'] = self.GetRequestId()  # Уникальный идентификатор запроса
        j = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': stopPrice, 'Instrument': {'Symbol': symbol, 'Exchange': exchange}, 'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': secondsOrderEnd}
        return self.CheckResult(put(url=f'{self.apiServer}/warptrans/{tradeServerCode}/v2/client/orders/actions/takeProfit/{orderId}', headers=headers, json=j))

    def EditTakeProfitLimitOrder(self, tradeServerCode, account, portfolio, exchange, orderId, symbol, side, quantity, stopPrice, limitPrice, secondsOrderEnd=0):
        """Изменение стоп-лимит заявки

        :param str tradeServerCode: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int orderId: Номер заявки
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stopPrice: Стоп цена
        :param float limitPrice: Лимитная цена
        :param int secondsOrderEnd: Дата и время UTC в секундах завершения сделки
        """
        headers = self.GetHeaders()
        headers['X-ALOR-REQID'] = self.GetRequestId()  # Уникальный идентификатор запроса
        j = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': stopPrice, 'Price': limitPrice, 'Instrument': {'Symbol': symbol, 'Exchange': exchange}, 'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': secondsOrderEnd}
        return self.CheckResult(put(url=f'{self.apiServer}/warptrans/{tradeServerCode}/v2/client/orders/actions/takeProfitLimit/{orderId}', headers=headers, json=j))

    def EditStopLossLimitOrder(self, tradeServerCode, account, portfolio, exchange, orderId, symbol, side, quantity, stopPrice, limitPrice, secondsOrderEnd=0):
        """Изменение стоп-лосс лимит заявки

        :param str tradeServerCode: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str account: Счет
        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int orderId: Номер заявки
        :param str symbol: Тикер
        :param str side: Покупка 'buy' или продажа 'sell'
        :param int quantity: Кол-во в лотах
        :param float stopPrice: Стоп цена
        :param float limitPrice: Лимитная цена
        :param int secondsOrderEnd: Дата и время UTC в секундах завершения сделки
        """
        headers = self.GetHeaders()
        headers['X-ALOR-REQID'] = self.GetRequestId()  # Уникальный идентификатор запроса
        j = {'Quantity': abs(quantity), 'Side': side, 'TriggerPrice': stopPrice, 'Price': limitPrice, 'Instrument': {'Symbol': symbol, 'Exchange': exchange}, 'User': {'Account': account, 'Portfolio': portfolio}, 'OrderEndUnixTime': secondsOrderEnd}
        return self.CheckResult(put(url=f'{self.apiServer}/warptrans/{tradeServerCode}/v2/client/orders/actions/stopLossLimit/{orderId}', headers=headers, json=j))

    def DeleteOrder(self, portfolio, exchange, orderId, stop):
        """Снятие заявки

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param int orderId: Номер заявки
        :param bool stop: Является ли стоп-заявкой
        """
        headers = self.GetHeaders()
        headers['X-ALOR-REQID'] = self.GetRequestId()  # Уникальный идентификатор запроса
        params = {'portfolio': portfolio, 'exchange': exchange, 'stop': stop, 'jsonResponse': True, 'format': 'Simple'}
        return self.CheckResult(delete(url=f'{self.apiServer}/commandapi/warptrans/TRADE/v2/client/orders/{orderId}', headers=headers, params=params))

    def DeleteStopOrder(self, tradeServerCode, portfolio, orderId, stop):
        """Снятие стоп-заявки

        :param str tradeServerCode: Код торгового сервера 'TRADE' (ценные бумаги), 'ITRADE' (ипотечные ценные бумаги), 'FUT1' (фьючерсы), 'OPT1' (опционы), 'FX1' (валюта)
        :param str portfolio: Клиентский портфель
        :param int orderId: Номер заявки
        :param bool stop: Является ли стоп-заявкой
        """
        headers = self.GetHeaders()
        headers['X-ALOR-REQID'] = self.GetRequestId()  # Уникальный идентификатор запроса
        params = {'portfolio': portfolio, 'stop': stop}
        return self.CheckResult(delete(url=f'{self.apiServer}/warptrans/{tradeServerCode}/v2/client/orders/{orderId}', headers=headers, params=params))

    def EstimateOrder(self, portfolio, exchange, symbol, price, quantity, board):
        """Провести оценку одной заявки

        :param str portfolio: Клиентский портфель
        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param float price: Цена покупки
        :param int quantity: Кол-во в лотах
        :param str board: Режим торгов (борд) TODO Какие значения она принимает?
        """
        j = {'portfolio': portfolio, 'ticker': symbol, 'exchange': exchange, 'price': price, 'lotQuantity': quantity, 'board': board}
        return self.CheckResult(post(url=f'{self.apiServer}/commandapi/warptrans/TRADE/v2/client/orders/estimate', json=j))

    def EstimateOrders(self, orders):
        """Провести оценку нескольких заявок

        :param dict orders: Список заявок. Оформлять каждую заявку как в EstimateOrder:
        {'portfolio': portfolio, 'ticker': symbol, 'exchange': exchange, 'price': price, 'lotQuantity': quantity, 'board': board}
        """
        return self.CheckResult(post(url=f'{self.apiServer}/commandapi/warptrans/TRADE/v2/client/orders/estimate/all', json=orders))

    # Подписки и события (WebSocket)

    def OrderBookGetAndSubscribe(self, exchange, symbol, depth=20):
        """Подписка на информацию о биржевом стакане для выбранных биржи и финансового инструмента

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param int depth: Глубина стакана. Стандартное и максимальное значение - 20 (20х20)
        """
        request = {'opcode': 'OrderBookGetAndSubscribe', 'exchange': exchange, 'code': symbol, 'depth': depth, 'format': 'Simple'}  # Запрос на подписку
        return self.WebSocketSend(request)  # Отправляем запрос, возвращаем GUID подписки

    def BarsGetAndSubscribe(self, exchange, symbol, tf, secondsFrom):
        """Подписка на историю цен (свечи) для выбранных биржи и финансового инструмента

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param str tf: Длительность таймфрейма в секундах или код ("D" - дни, "W" - недели, "M" - месяцы, "Y" - годы)
        :param int secondsFrom: Дата и время UTC в секундах для первого запрашиваемого бара
        """
        # Ответ ALOR OpenAPI Support: Чтобы получать последний бар сессии на первом тике следующей сессии, нужно использовать скрытый параметр frequency в ms с очень большим значением
        request = {'opcode': 'BarsGetAndSubscribe', 'exchange': exchange, 'code': symbol, 'tf': tf, 'from': int(secondsFrom), 'delayed': False, 'frequency': 1000000000, 'format': 'Simple'}  # Запрос на подписку
        # if type(tf) is not str:  # Для внутридневных баров
        #     request['frequency'] = (tf + 10) * 1000  # Задержка в ms. Позволяет получать новый бар не на каждом тике, а на первом и последнем тике. Последний бар сессии придет через 10 секунд после закрытия биржи
        return self.WebSocketSend(request)  # Отправляем запрос, возвращаем GUID подписки

    def QuotesSubscribe(self, exchange, symbol):
        """Подписка на информацию о котировках для выбранных инструментов и бирж

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        """
        request = {'opcode': 'QuotesSubscribe', 'exchange': exchange, 'code': symbol, 'format': 'Simple'}  # Запрос на подписку
        return self.WebSocketSend(request)  # Отправляем запрос, возвращаем GUID подписки

    def AllTradesSubscribe(self, exchange, symbol, depth=0):
        """Подписка на все сделки

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        :param int depth: Если указать, то перед актуальными данными придут данные о последних N сделках. Максимум 5000
        """
        request = {'opcode': 'AllTradesGetAndSubscribe', 'code': symbol, 'exchange': exchange, 'format': 'Simple', 'depth': depth}  # Запрос на подписку
        return self.WebSocketSend(request)  # Отправляем запрос, возвращаем GUID подписки

    def PositionsGetAndSubscribeV2(self, portfolio, exchange):
        """Подписка на информацию о текущих позициях по ценным бумагам и деньгам

        :param portfolio: Клиентский портфель
        :param exchange: Биржа 'MOEX' или 'SPBX'
        """
        request = {'opcode': 'PositionsGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'format': 'Simple'}  # Запрос на подписку
        return self.WebSocketSend(request)  # Отправляем запрос, возвращаем GUID подписки

    def SummariesGetAndSubscribeV2(self, portfolio, exchange):
        """Подписка на сводную информацию по портфелю

        :param portfolio: Клиентский портфель
        :param exchange: Биржа 'MOEX' или 'SPBX'
        """
        request = {'opcode': 'SummariesGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'format': 'Simple'}  # Запрос на подписку
        return self.WebSocketSend(request)  # Отправляем запрос, возвращаем GUID подписки

    def RisksGetAndSubscribe(self, portfolio, exchange):
        """Подписка на сводную информацию по портфельным рискам

        :param portfolio: Клиентский портфель
        :param exchange: Биржа 'MOEX' или 'SPBX'
        """
        request = {'opcode': 'RisksGetAndSubscribe', 'exchange': exchange, 'portfolio': portfolio, 'format': 'Simple'}  # Запрос на подписку
        return self.WebSocketSend(request)  # Отправляем запрос, возвращаем GUID подписки

    def SpectraRisksGetAndSubscribe(self, portfolio, exchange):
        """Подписка на информацию по рискам срочного рынка (FORTS)

        :param portfolio: Клиентский портфель
        :param exchange: Биржа 'MOEX' или 'SPBX'
        """
        request = {'opcode': 'SpectraRisksGetAndSubscribe', 'exchange': exchange, 'portfolio': portfolio, 'format': 'Simple'}  # Запрос на подписку
        return self.WebSocketSend(request)  # Отправляем запрос, возвращаем GUID подписки

    def TradesGetAndSubscribeV2(self, portfolio, exchange):
        """Подписка на информацию о сделках

        :param portfolio: Клиентский портфель
        :param exchange: Биржа 'MOEX' или 'SPBX'
        """
        request = {'opcode': 'TradesGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'format': 'Simple'}  # Запрос на подписку
        return self.WebSocketSend(request)  # Отправляем запрос, возвращаем GUID подписки

    def StopOrdersGetAndSubscribe(self, portfolio, exchange):
        """Подписка на информацию о текущих стоп заявках на рынке для выбранных биржи и финансового инструмента

        :param portfolio: Клиентский портфель
        :param exchange: Биржа 'MOEX' или 'SPBX'
        """
        request = {'opcode': 'StopOrdersGetAndSubscribe', 'exchange': exchange, 'portfolio': portfolio, 'format': 'Simple'}  # Запрос на подписку
        return self.WebSocketSend(request)  # Отправляем запрос, возвращаем GUID подписки

    def OrdersGetAndSubscribeV2(self, portfolio, exchange):
        """Подписка на информацию о текущих заявках на рынке для выбранных биржи и финансового инструмента

        :param portfolio: Клиентский портфель
        :param exchange: Биржа 'MOEX' или 'SPBX'
        """
        request = {'opcode': 'OrdersGetAndSubscribeV2', 'exchange': exchange, 'portfolio': portfolio, 'format': 'Simple'}  # Запрос на подписку
        return self.WebSocketSend(request)  # Отправляем запрос, возвращаем GUID подписки

    def InstrumentsGetAndSubscribeV2(self, exchange, symbol):
        """Подписка на изменение информации о финансовых инструментах на выбранной бирже

        :param str exchange: Биржа 'MOEX' или 'SPBX'
        :param str symbol: Тикер
        """
        request = {'opcode': 'InstrumentsGetAndSubscribeV2', 'code': symbol, 'exchange': exchange, 'format': 'Simple'}  # Запрос на подписку
        return self.WebSocketSend(request)  # Отправляем запрос, возвращаем GUID подписки

    def Unsubscribe(self, guid):
        """Отмена существующей подписки

        :param guid: Код подписки
        """
        request = {'opcode': 'unsubscribe', 'token': str(self.GetJWTToken()), 'guid': str(guid)}  # Запрос на отмену подписки
        run(self.webSocket.send(dumps(request)))  # Отправляем запрос
        return guid  # Возвращаем GUID отмененной подписки

    # Выход и закрытие

    def CloseWebSocket(self):
        """Закрытие соединения с сервером WebSocket"""
        if self.webSocket is not None:  # Если запущена задача управления подписками WebSocket
            self.webSocketTask.cancel()  # то отменяем задачу. Генерируем на ней исключение asyncio.CancelledError

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Выход из класса, например, с with"""
        self.CloseWebSocket()  # Закрываем соединение с сервером WebSocket

    def __del__(self):
        self.CloseWebSocket()  # Закрываем соединение с сервером WebSocket
