from sqlitedict import SqliteDict
import time

class StripeKVCache:
    def __init__(self, path="stripe_cache.sqlite"):
        self.db = SqliteDict(path, autocommit=True)

    def get(self, key):
        cache = self.db.get(key)
        if cache is None:
            return None
        else:
            return cache["data"]

    def set(self, key, value):
        self.db[key] = {
            "ts": time.time(),
            "data": value,
        }

    def close(self):
        self.db.close()

