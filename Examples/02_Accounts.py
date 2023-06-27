from AlorPy import AlorPy  # Работа с Alor OpenAPI V2
from AlorPy.Config import Config, ConfigIIA, ConfigDemo  # Файлы конфигурации


if __name__ == '__main__':  # Точка входа при запуске этого скрипта
    ap_providers = []  # Счета будет хранить в виде списка
    ap_providers.append((Config.UserName, Config.RefreshToken,))  # Торговый счет
    ap_providers.append((ConfigIIA.UserName, ConfigIIA.RefreshToken,))  # ИИС
    # ap_providers.append((ConfigDemo.UserName, ConfigDemo.RefreshToken,))  # Демо счет для тестов

    ap_provider = AlorPy(ap_providers[0][0], ap_providers[0][1])  # Подключаемся к торговому счету
    print('Кол-во тикеров на бирже:')
    for exchange in ap_provider.exchanges:  # Пробегаемся по всем биржам
        securities = ap_provider.get_securities_exchange(exchange)  # Получаем все тикеры на бирже
        print(f'- {exchange} {len(securities)}')
        boards = tuple(set(security['primary_board'] for security in securities))  # Все классы инструментов
        for board in boards:  # Пробегаемся по всем классам
            board_symbols = [security for security in securities if security['primary_board'] == board]
            print(f'  - {board} {len(board_symbols)}')
    print()

    for user_name, refresh_token in ap_providers:  # Пробегаемся по всем счетам
        print(f'Учетная запись: {user_name}')
        ap_provider = AlorPy(user_name, refresh_token)  # Подключаемся к счету
        portfolios = ap_provider.get_portfolios()  # Портфели: Фондовый рынок / Фьючерсы и опционы / Валютный рынок
        for p in portfolios:  # Пробегаемся по всем портфелям
            portfolio_name = portfolios[p][0]['portfolio']  # Название портфеля
            account = portfolios[p][0]['tks']  # Счет
            print(f'{p}: Портфель {portfolio_name}, Счет {account}')
            trade_servers_info = portfolios[p][0]['tradeServersInfo']  # Торговый сервер
            print('- Торговые серверы')
            for trade_server_info in trade_servers_info:  # Пробегаемся по всем торговым серверам
                print(f'  - {trade_server_info["tradeServerCode"]} для контрактов {trade_server_info["contracts"]}')
            for exchange in ap_provider.exchanges:  # Пробегаемся по всем биржам
                print(f'- Биржа {exchange}')
                positions = ap_provider.get_positions(portfolio_name, exchange, True)  # Позиции без денежной позиции
                for position in positions:  # Пробегаемся по всем позициям
                    symbol = position['symbol']  # Тикер
                    symbol_info = ap_provider.get_symbol(exchange, symbol)  # Информация о тикере
                    size = position['qty'] * symbol_info['lotsize']  # Кол-во в штуках
                    entry_price = round(position['volume'] / size, 2)  # Цена входа
                    pl = position['unrealisedPl'] * symbol_info['priceMultiplier']  # Бумажная прибыль/убыток
                    last_price = round((position['volume'] + pl) / size, 2)  # Последняя цена
                    print(f'  - Позиция {position["shortName"]} ({symbol}) {size} @ {entry_price} / {last_price}')
                money = ap_provider.get_money(portfolio_name, exchange)  # Денежная позиция
                print(f'  - Позиции {round(money["portfolio"] - money["cash"], 2)} + Свободные средства {money["cash"]} = {round(money["portfolio"], 2)}')
                orders = ap_provider.get_orders(portfolio_name, exchange)  # Получаем список активных заявок
                for order in orders:  # Пробегаемся по всем активным заявкам
                    print(f'  - Заявка номер {order["id"]} {"Покупка" if order["side"] == "buy" else "Продажа"} {order["exchange"]}.{order["symbol"]} {order["qty"]} @ {order["price"]}')
                stop_orders = ap_provider.get_stop_orders(portfolio_name, exchange)  # Получаем список активных стоп заявок
                for stop_order in stop_orders:  # Пробегаемся по всем активным стоп заявкам
                    print(f'  - Стоп заявка номер {stop_order["id"]} {"Покупка" if stop_order["side"] == "buy" else "Продажа"} {stop_order["exchange"]}.{stop_order["symbol"]} {stop_order["qty"]} @ {stop_order["price"]}')
        print()
