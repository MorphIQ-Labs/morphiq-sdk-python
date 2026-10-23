"""Run with python -m examples.price_async; notebooks can await main() directly."""

import asyncio

from morphiq_sdk import AsyncMorphIQ

from ._shared import american_put, configure, european_call, show_price


async def main() -> None:
    configure()
    async with AsyncMorphIQ() as client:
        # Sequential awaits fit plans that allow only one concurrent request.
        european = await client.price(european_call())
        show_price(european)
        american = await client.price(american_put())
        show_price(american)


if __name__ == "__main__":
    asyncio.run(main())
