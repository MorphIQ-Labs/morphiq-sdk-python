"""Run both synchronous examples after configuring the API once."""

from morphiq_sdk import MorphIQ

from ._shared import american_put, configure, european_call, show_price


def main() -> None:
    configure()
    with MorphIQ() as client:
        print("European call")
        show_price(client.price(european_call()))
        print("American put")
        show_price(client.price(american_put()))


if __name__ == "__main__":
    main()
