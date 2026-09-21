import datetime
import queue
import threading

_subscribers = set()
_subscribers_lock = threading.Lock()


def log(label, message):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {label}: {message}"
    print(line, flush=True)

    with _subscribers_lock:
        subscribers = list(_subscribers)
    for q in subscribers:
        q.put(line)


def subscribe():
    q = queue.Queue()
    with _subscribers_lock:
        _subscribers.add(q)
    return q


def unsubscribe(q):
    with _subscribers_lock:
        _subscribers.discard(q)
