"""Run with python -m examples.price_american from the repository root."""

from morphiq_sdk import MorphIQ

from ._shared import american_put, configure, show_price


def main() -> None:
    configure()
    with MorphIQ() as client:
        response = client.price(american_put())
        show_price(response)


if __name__ == "__main__":
    main()
