"""Fixed loopback room-audio reads. No stop/write transport is admitted here."""
import http.client
import json
import random
import time


def read_status(port, *, connection_factory=http.client.HTTPConnection,
                clock=time.monotonic, sleep=time.sleep):
    if port not in (8791, 8793):
        raise ValueError('invalid speaker')
    deadline = clock() + 7.0
    for attempt in range(3):
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError('room audio read deadline')
        connection = connection_factory('127.0.0.1', port, timeout=min(2.0, remaining))
        try:
            connection.request('GET', '/control/status')
            response = connection.getresponse()
            data = response.read(4097)
            if response.status in (502, 503, 504):
                raise ConnectionError('temporary room audio failure')
            if response.status != 200 or len(data) > 4096:
                raise ValueError('invalid room audio response')
            value = json.loads(data)
            if not isinstance(value, dict) or value.get('ok') is not True:
                raise ValueError('invalid room audio response')
            safe = {key: value.get(key) for key in
                    ('ok', 'clientOnline', 'phase', 'turnID', 'canStop', 'ageSeconds')}
            if safe['phase'] not in {'idle', 'processing', 'speaking', 'cancelling', 'unavailable'}:
                raise ValueError('invalid room audio phase')
            return safe
        except (ConnectionError, TimeoutError, http.client.RemoteDisconnected):
            if attempt == 2:
                raise
        finally:
            connection.close()
        delay = random.uniform(0.1, 0.25) * (attempt + 1)
        if clock() + delay >= deadline:
            raise TimeoutError('room audio read deadline')
        sleep(delay)
