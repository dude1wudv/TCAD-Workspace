"""Optional planner sidecar; never owns Runtime, runners, leases or task status."""
from concurrent.futures import ThreadPoolExecutor


class AsyncPlanner:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="research-planner")
        self.pending = None

    def start(self, function, context, *args, **kwargs):
        if self.pending is not None:return False
        self.pending = (context, self.executor.submit(function, *args, **kwargs))
        return True

    def take(self, wait=False):
        if self.pending is None:return None
        context, future = self.pending
        if not wait and not future.done():return None
        result = future.result()
        self.pending = None
        return context, result

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)
