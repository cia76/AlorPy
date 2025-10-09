from setuptools import setup

setup(name='AlorPy',
      version='2025.10.01',  # Внутренняя версия формата <Год>.<Месяц>.<Номер>, т.к. Алор версии не ставит
      author='Чечет Игорь Александрович',
      description='Библиотека-обертка, которая позволяет работать с АЛОР Брокер API брокера Алор из Python',
      url='https://github.com/cia76/AlorPy',
      packages=['AlorPy'],
      install_requires=[
            'pytz',  # ВременнЫе зоны
            'requests',  # Запросы/ответы через HTTP API
            'PyJWT',  # Декодирование токена JWT для получения договоров и портфелей
            'urllib3',  # Соединение с сервером не установлено за максимальное кол-во попыток подключения
            'websockets',  # Управление подписками и заявками через WebSocket API
      ],
      python_requires='>=3.12',
      )
