"""Tiny helpers with no Streamlit dependency."""
import functools
import time


def ttl_cache(seconds: float):
    """Cache a function's result per-arguments for `seconds`. Use fn.cache_clear() to reset."""
    def deco(fn):
        store: dict = {}

        @functools.wraps(fn)
        def wrapper(*args):
            now = time.time()
            hit = store.get(args)
            if hit and now - hit[0] < seconds:
                return hit[1]
            value = fn(*args)
            store[args] = (now, value)
            return value

        wrapper.cache_clear = store.clear
        return wrapper
    return deco
