"""Async wrapper over mongomock so the economy code can be tested without a real Mongo."""

import asyncio

import mongomock


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def sort(self, *a, **k):
        self.cursor = self.cursor.sort(*a, **k)
        return self

    def skip(self, n):
        self.cursor = self.cursor.skip(n)
        return self

    def limit(self, n):
        self.cursor = self.cursor.limit(n)
        return self

    async def to_list(self, length=None):
        return list(self.cursor)


class Collection:
    def __init__(self, collection):
        self.c = collection

    def __getattr__(self, name):
        method = getattr(self.c, name)

        async def call(*args, session=None, **kwargs):
            # Yield to the loop like a real network call, to expose races.
            await asyncio.sleep(0)
            return method(*args, **kwargs)

        return call

    def find(self, *args, session=None, **kwargs):
        return Cursor(self.c.find(*args, **kwargs))

    async def aggregate(self, pipeline, session=None, **kwargs):
        # Like PyMongo async: aggregate() must be awaited and returns a cursor.
        await asyncio.sleep(0)
        return Cursor(list(self.c.aggregate(pipeline, **kwargs)))


class DB:
    def __init__(self):
        self.db = mongomock.MongoClient(tz_aware=False).db

    def __getitem__(self, name):
        return Collection(self.db[name])
