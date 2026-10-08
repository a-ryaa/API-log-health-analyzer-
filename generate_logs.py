"""
generate_logs.py
Creates a realistic sample API log file (api_health.log) so the analyzer
can be demonstrated without a real server.

Log line format:
    YYYY-MM-DD HH:MM:SS | METHOD | /endpoint | STATUS | RESPONSE_TIME_MS
"""

import random
from datetime import datetime, timedelta

# endpoint -> (failure chance, normal response time range in ms)
ENDPOINTS = {
    "/api/login":    (0.05, (80, 250)),
    "/api/users":    (0.02, (60, 200)),
    "/api/products": (0.03, (100, 400)),
    "/api/orders":   (0.12, (200, 900)),   # intentionally unhealthy
    "/api/payments": (0.25, (400, 2500)),  # intentionally critical
    "/api/search":   (0.04, (150, 600)),
}
METHODS = ["GET", "POST", "PUT", "DELETE"]
OK_CODES = [200, 200, 200, 201, 204]
CLIENT_ERRORS = [400, 401, 403, 404]
SERVER_ERRORS = [500, 502, 503, 504]


def generate(filename="api_health.log", total=1000, seed=42):
    random.seed(seed)
    current = datetime(2026, 10, 3, 8, 0, 0)

    with open(filename, "w") as f:
        for _ in range(total):
            current += timedelta(seconds=random.randint(1, 30))
            endpoint = random.choice(list(ENDPOINTS))
            fail_chance, (low, high) = ENDPOINTS[endpoint]

            if random.random() < fail_chance:
                # failed request: 40% client error, 60% server error
                if random.random() < 0.4:
                    status = random.choice(CLIENT_ERRORS)
                else:
                    status = random.choice(SERVER_ERRORS)
                response_time = random.randint(high, high * 2)   # slow on failure
            else:
                status = random.choice(OK_CODES)
                response_time = random.randint(low, high)

            f.write(
                f"{current:%Y-%m-%d %H:%M:%S} | {random.choice(METHODS)} | "
                f"{endpoint} | {status} | {response_time}\n"
            )
    print(f"Generated {total} log entries in '{filename}'")


if __name__ == "__main__":
    generate()