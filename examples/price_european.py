"""Run with python -m examples.price_european from the repository root."""

from morphiq_sdk import MorphIQ

from ._shared import configure, european_call, show_price


def main() -> None:
    configure()
    with MorphIQ() as client:
        response = client.price(european_call())
        show_price(response)


if __name__ == "__main__":
    main()
