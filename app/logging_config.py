"""统一日志格式：时间、级别、模块、消息。"""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(level: str = "INFO") -> None:
    """配置根日志器；重复调用会覆盖之前的配置。"""
    logging.basicConfig(level=level.upper(), format=LOG_FORMAT, force=True)
