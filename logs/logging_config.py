"""Logging configuration for the application.

This module sets up the logging infrastructure with three handlers:
- Console: INFO and above
- File: WARNING and above, with rotation
- Email: ERROR and above

Usage:
    from logs.logging_config import setup_logging
    setup_logging()
"""

import logging
import logging.handlers

from config import DEVELOPER_EMAIL, FEEDBACK_EMAIL, LOGS_DIR
from logs.imageSMTPHandler import ImageSMTPHandler


def setup_logging(debug_mode: bool = False) -> None:
    """Configures the root logger with console, file, and email handlers.

    Should be called once at application startup, before any logging occurs.
    The log directory must exist before calling this function.

    Args:
        debug_mode: If True, the console handler will output DEBUG level
            messages. Defaults to False (INFO and above).
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    _add_console_handler(root, formatter, debug_mode)
    _add_file_handler(root, formatter)
    _add_email_handler(root, formatter)

    logging.getLogger(__name__).info("Logging initialized.")

    # avoid console overload
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def _add_console_handler(
    logger: logging.Logger,
    formatter: logging.Formatter,
    debug_mode: bool,
) -> None:
    """Adds a console (StreamHandler) to the given logger.

    Args:
        logger: The logger to add the handler to.
        formatter: The formatter to use for log messages.
        debug_mode: If True, sets the handler level to DEBUG, otherwise INFO.
    """
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG if debug_mode else logging.INFO)
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def _add_file_handler(
    logger: logging.Logger,
    formatter: logging.Formatter,
) -> None:
    """Adds a rotating file handler to the given logger.

    Logs WARNING and above to a rotating log file. Keeps 3 backup files
    of 1 MB each.

    Note: on Railway (or other ephemeral filesystems), this file is lost
    on every redeploy/restart. Fine for local testing; the console handler
    remains the reliable source once deployed.

    Args:
        logger: The logger to add the handler to.
        formatter: The formatter to use for log messages.
    """
    log_file = LOGS_DIR / "app.log"

    handler = logging.handlers.RotatingFileHandler(
        filename=log_file,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setLevel(logging.WARNING)
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def _add_email_handler(
    logger: logging.Logger,
    formatter: logging.Formatter,
) -> None:
    """Adds an SMTP email handler to the given logger.

    Sends an email for ERROR and CRITICAL level log messages.

    Args:
        logger: The logger to add the handler to.
        formatter: The formatter to use for log messages.
    """
    if not FEEDBACK_EMAIL or DEVELOPER_EMAIL:
        logging.getLogger(__name__).warning(
            "Email handler not configured: missing FEEDBACK_EMAIL and/or DEVELOPER_EMAIL"
        )
        return

    handler = ImageSMTPHandler(
        fromaddr=FEEDBACK_EMAIL,
        toaddrs=DEVELOPER_EMAIL,
        subject="PieceHunt Error",
    )
    handler.setLevel(logging.ERROR)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
