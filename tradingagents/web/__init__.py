"""Optional local browser interface (importing this package needs no web extras)."""


def create_app(**kwargs):
    from tradingagents.web.app import create_app as factory

    return factory(**kwargs)


def main():
    from tradingagents.web.__main__ import main as launch

    launch()
