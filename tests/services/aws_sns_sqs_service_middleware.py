import asyncio
import os
import uuid
from typing import Any, Callable

import tomodachi
from tomodachi.transport.aws_sns_sqs import AWSSNSSQSInternalServiceException

data_uuid = str(uuid.uuid4())


class TestException(Exception):
    """Exception that is not propagated out of the middleware"""


async def tomodachi_catch_exception_middleware(func: Callable, *args: Any, **kwargs: Any) -> None:
    try:
        await func()
    except TestException:
        pass


@tomodachi.service
class AWSSNSSQSSservice(tomodachi.Service):
    name = "test_aws_sns_sqs_middleware"
    log_level = "INFO"
    options = {
        "aws": {
            "region_name": os.environ.get("TOMODACHI_TEST_AWS_REGION"),
            "aws_access_key_id": os.environ.get("TOMODACHI_TEST_AWS_ACCESS_KEY_ID"),
            "aws_secret_access_key": os.environ.get("TOMODACHI_TEST_AWS_ACCESS_SECRET"),
        },
        "aws_sns_sqs": {
            "queue_name_prefix": os.environ.get("TOMODACHI_TEST_SQS_QUEUE_PREFIX"),
            "topic_prefix": os.environ.get("TOMODACHI_TEST_SNS_TOPIC_PREFIX"),
        },
    }
    closer: asyncio.Future = asyncio.Future()

    message_middleware = [tomodachi_catch_exception_middleware]
    normal_flow_runs = 0
    exception_delete_message_runs = 0
    non_deleting_exception_runs = 0

    @tomodachi.aws_sns_sqs("test-normal-flow-topic")
    async def test_normal_flow(self) -> None:
        self.normal_flow_runs += 1

    @tomodachi.aws_sns_sqs("test-exception-delete-message-topic")
    async def test_exception_delete_message(self) -> None:
        self.exception_delete_message_runs += 1
        raise TestException("This should be caught by the middleware and the message should be deleted from the queue")

    @tomodachi.aws_sns_sqs("test-non-deleting-exception-topic")
    async def test_non_deleting_exception(self) -> None:
        self.non_deleting_exception_runs += 1
        raise AWSSNSSQSInternalServiceException("This should not remove the message from SQS queue")

    async def _run_test(self) -> None:
        async def _publish(topic: str) -> None:
            await tomodachi.aws_sns_sqs_publish(self, {"data": topic}, topic)

        await _publish("test-normal-flow-topic")
        await _publish("test-exception-delete-message-topic")
        await _publish("test-non-deleting-exception-topic")

        await asyncio.sleep(5)

        assert self.normal_flow_runs == 1
        assert self.exception_delete_message_runs == 1
        assert self.non_deleting_exception_runs >= 1

    async def _started_service(self) -> None:
        await self._run_test()
