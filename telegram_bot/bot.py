"""Telegram bot application wiring."""
from __future__ import annotations

import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

import handlers
from config import config

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO
)
logger = logging.getLogger("signalgate.bot")


def build_application() -> Application:
    if not config.token or config.token == "replace_me":
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Add it to your .env before running "
            "the bot."
        )

    app = Application.builder().token(config.token).build()

    # User commands.
    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler("status", handlers.status))
    app.add_handler(CommandHandler("settings", handlers.settings_cmd))
    app.add_handler(CommandHandler("provider", handlers.provider_invite))
    app.add_handler(CommandHandler("screenshothelp", handlers.screenshot_help))

    # Admin commands.
    app.add_handler(CommandHandler("testsignal", handlers.testsignal))
    app.add_handler(CommandHandler("pause", handlers.pause))
    app.add_handler(CommandHandler("resume", handlers.resume))
    app.add_handler(CommandHandler("users", handlers.users_cmd))
    app.add_handler(CommandHandler("lastsignals", handlers.lastsignals))
    app.add_handler(CommandHandler("lastcommands", handlers.lastcommands))

    # YES/NO trade-card callbacks.
    app.add_handler(CallbackQueryHandler(handlers.on_decision, pattern=r"^(YES|NO):"))

    # Screenshot -> signal workflow: photo in, Confirm/Edit/Cancel, edit text.
    app.add_handler(MessageHandler(filters.PHOTO, handlers.on_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handlers.on_document))
    app.add_handler(
        CallbackQueryHandler(handlers.on_signal_preview, pattern=r"^SIG(OK|EDIT|NO)$")
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_text)
    )

    return app


def main() -> None:
    app = build_application()
    logger.info("SignalGate Telegram bot starting (demo only).")
    app.run_polling()


if __name__ == "__main__":
    main()
