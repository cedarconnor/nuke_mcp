from uuid import uuid4


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def request(instance=None, session=None, **changes):
    value = dict(protocol_version=2, request_id=str(uuid4()),
                 client_session_id=session or str(uuid4()),
                 server_instance_id=instance or str(uuid4()),
                 command="ping", params={}, timeout_ms=30000)
    value.update(changes)
    return value
