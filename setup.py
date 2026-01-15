from setuptools import setup, find_packages

setup(name='AlorPy',
      version='2026.01.02',  # Внутренняя версия формата <Год>.<Месяц>.<Номер>, т.к. Алор версии не ставит
      author='Чечет Игорь Александрович',
      description='Библиотека-обертка, которая позволяет работать с АЛОР Брокер API брокера Алор из Python',
      url='https://github.com/cia76/AlorPy',
      packages=find_packages(),
      install_requires=[
            'keyring',  # Безопасное хранение торгового токена
            'requests',  # Запросы/ответы через HTTP API
            'PyJWT',  # Декодирование токена JWT для получения договоров и портфелей
            'urllib3',  # Соединение с сервером не установлено за максимальное кол-во попыток подключения
            'websockets',  # Управление подписками и заявками через WebSocket API
      ],
      python_requires='>=3.12',
      )
