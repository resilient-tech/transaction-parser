from transaction_parser.transaction_parser.utils import is_enabled


def boot_session(bootinfo):
    bootinfo.transaction_parser_enabled = is_enabled(throw=False)
