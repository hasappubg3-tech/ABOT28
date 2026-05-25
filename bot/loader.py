import importlib

MODULE_NAMES = [
    "data_access",
    "features",
    "keyboards",
    "content_delivery",
    "message_handlers",
    "callback_handlers",
    "ai_backup_payments",
    "mlz_feature",
    "lifecycle",
]

def load_bot_symbols():
    modules = [importlib.import_module(f"bot.{name}") for name in MODULE_NAMES]
    symbols = {}
    for module in modules:
        symbols.update({name: value for name, value in vars(module).items() if not name.startswith("__")})
    for module in modules:
        vars(module).update(symbols)
    return symbols
