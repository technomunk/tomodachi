import asyncio
import os
from typing import Any

import pytest

from run_test_service_helper import start_service


@pytest.mark.skipif(
    not os.environ.get("TOMODACHI_TEST_AWS_ACCESS_KEY_ID") or not os.environ.get("TOMODACHI_TEST_AWS_ACCESS_SECRET"),
    reason="AWS configuration options missing in environment",
)
def test_start_aws_sns_sqs_middleware_service(monkeypatch: Any, loop: Any) -> None:
    services, future = start_service("tests/services/aws_sns_sqs_service_middleware.py", monkeypatch)

    assert services is not None
    assert len(services) == 1
    instance = services.get("test_aws_sns_sqs_middleware")
    assert instance is not None

    assert instance.uuid is not None

    loop.run_until_complete(asyncio.sleep(10))
    instance.stop_service()
    loop.run_until_complete(future)
