import asyncio
import time

from src.cache import SQLiteCache


def test_refinery_order_lifecycle_and_user_isolation(tmp_path) -> None:
    async def scenario() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "orders.sqlite3"))
        try:
            order_id = await cache.save_user_refinery_order(
                10,
                {
                    "label": "Gold run",
                    "material": "Gold",
                    "quantity": 32,
                    "refinery": "ARC-L1",
                    "method": "Dinyx",
                    "location": "Lyria",
                    "crew": "Alex, Sam",
                    "notes": "Sell together",
                    "completes_at": int(time.time()) + 3600,
                },
            )
            orders = await cache.user_refinery_orders(10)
            assert orders[0]["id"] == order_id
            assert orders[0]["status"] == "refining"
            assert await cache.user_refinery_orders(11) == []
            assert await cache.update_user_refinery_order_status(10, order_id, "collected")
            assert (await cache.user_refinery_orders(10))[0]["status"] == "collected"
            assert not await cache.delete_user_refinery_order(11, order_id)
            assert await cache.delete_user_refinery_order(10, order_id)
        finally:
            await cache.close()

    asyncio.run(scenario())


def test_elapsed_refinery_order_becomes_ready(tmp_path) -> None:
    async def scenario() -> None:
        cache = await SQLiteCache.create(str(tmp_path / "orders.sqlite3"))
        try:
            await cache.save_user_refinery_order(
                10,
                {"label": "Finished", "completes_at": int(time.time()) - 1},
            )
            assert (await cache.user_refinery_orders(10))[0]["status"] == "ready"
        finally:
            await cache.close()

    asyncio.run(scenario())
