# collectors/__init__.py (가장 바깥쪽)
from .base import CollectorChain
from .stocks import WikipediaStrategy
from .schedules import YFinanceScheduleStrategy
from .prices import YFinancePriceStrategy