if __package__ == "services":
    from core.redis_publisher import *
else:
    from ..core.redis_publisher import *
