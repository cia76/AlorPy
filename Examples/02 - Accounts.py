from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config  # Файл конфигурации


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    apProvider = AlorPy(Config.UserName, Config.RefreshToken)  # Подключаемся к торговому счету. Логин и Refresh Token берутся из файла Config.py
    # apProvider = AlorPy(Config.DemoUserName, Config.DemoRefreshToken, True)  # Подключаемся к демо счету
    print('Кол-во тикеров на бирже:')
    for exchange in apProvider.exchanges:  # Пробегаемся по всем биржам
        securities = apProvider.GetSecuritiesExchange(exchange)  # Получаем все тикеры на бирже
        print(f'- {exchange} {len(securities)}')
        boards = tuple(set(security['primary_board'] for security in securities))  # Все классы инструментов
        for board in boards:  # Пробегаемся по всем классам
            boardSymbols = [security for security in securities if security['primary_board'] == board]
            print(f'  - {board} {len(boardSymbols)}')
    portfolios = apProvider.GetPortfolios()  # Портфели: Фондовый рынок / Фьючерсы и опционы / Валютный рынок
    for p in portfolios:  # Пробегаемся по всем портфелям
        portfolioName = portfolios[p][0]['portfolio']  # Название портфеля
        account = portfolios[p][0]['tks']  # Счет
        print(f'{p}: Портфель {portfolioName}, Счет {account}')
        tradeServersInfo = portfolios[p][0]['tradeServersInfo']  # Торговый сервер
        print('- Торговые серверы')
        for tradeServerInfo in tradeServersInfo:  # Пробегаемся по всем торговым серверам
            print(f'  - {tradeServerInfo["tradeServerCode"]} для контрактов {tradeServerInfo["contracts"]}')
        for exchange in apProvider.exchanges:  # Пробегаемся по всем биржам
            print(f'- Биржа {exchange}')
            positions = apProvider.GetPositions(portfolioName, exchange, True)  # Позиции без денежной позиции
            for position in positions:  # Пробегаемся по всем позициям
                symbol = position['symbol']  # Тикер
                symbolInfo = apProvider.GetSymbol(exchange, symbol)  # Информация о тикере
                size = position['qty'] * symbolInfo['lotsize']  # Кол-во в штуках
                entryPrice = round(position['volume'] / size, 2)  # Цена входа
                pl = position['unrealisedPl'] * symbolInfo['priceMultiplier']  # Бумажная прибыль/убыток
                lastPrice = round((position['volume'] + pl) / size, 2)  # Последняя цена
                print(f'  - Позиция {position["shortName"]} ({symbol}) {size} @ {entryPrice} / {lastPrice}')
            money = apProvider.GetMoney(portfolioName, exchange)  # Денежная позиция
            print(f'  - Баланс {round(money["portfolio"] - money["cash"], 2)} / {money["cash"]}')
            orders = apProvider.GetOrders(portfolioName, exchange)  # Получаем список активных заявок
            for order in orders:  # Пробегаемся по всем активным заявкам
                print(f'  - Заявка номер {order["id"]} {"Покупка" if order["side"] == "buy" else "Продажа"} {order["exchange"]}.{order["symbol"]} {order["qty"]} @ {order["price"]}')
            stopOrders = apProvider.GetStopOrders(portfolioName, exchange)  # Получаем список активных стоп заявок
            for stopOrder in stopOrders:  # Пробегаемся по всем активным стоп заявкам
                print(f'  - Стоп заявка номер {stopOrder["id"]} {"Покупка" if stopOrder["side"] == "buy" else "Продажа"} {stopOrder["exchange"]}.{stopOrder["symbol"]} {stopOrder["qty"]} @ {stopOrder["price"]}')
