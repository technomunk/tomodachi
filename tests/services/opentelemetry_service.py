import asyncio

import tomodachi
from opentelemetry.sdk._configuration import _import_exporters
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import OTELResourceDetector, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from tomodachi.opentelemetry import TomodachiInstrumentor
from tomodachi.transport.schedule import heartbeat, schedule

resource = Resource.create({"service.name": "test_opentelemetry"}).merge(OTELResourceDetector().detect())
tracer_provider = TracerProvider(resource=resource)
logger_provider = LoggerProvider(resource=resource)

trace_exporters, _, log_exporters = _import_exporters(
    ["console"],
    [],
    ["console"],
)

for _, exporter in trace_exporters.items():
    tracer_provider._active_span_processor.add_span_processor(BatchSpanProcessor(exporter()))

for _, exporter in log_exporters.items():
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter()))


instrumentor = TomodachiInstrumentor()
instrumentor.instrument(tracer_provider=tracer_provider, logger_provider=logger_provider)


class OpenTelemetryService(tomodachi.Service):
    name = "test_opentelemetry"
    closer: asyncio.Future
    seconds_triggered = 0
    third_seconds_triggered = 0

    @heartbeat
    async def every_second(self) -> None:
        self.seconds_triggered += 1

    @schedule(interval="3 seconds")
    async def every_third_second(self) -> None:
        self.third_seconds_triggered += 1

    async def _start_service(self) -> None:
        self.closer = asyncio.Future()

    async def _started_service(self) -> None:
        async def _async() -> None:
            async def sleep_and_kill() -> None:
                await asyncio.sleep(8.0)
                if not self.closer.done():
                    self.closer.set_result(None)

            task = asyncio.ensure_future(sleep_and_kill())
            await self.closer
            if not task.done():
                task.cancel()
            tomodachi.exit()

        asyncio.ensure_future(_async())

    async def _stop_service(self) -> None:
        instrumentor.uninstrument()
        tracer_provider.shutdown()
        logger_provider.shutdown()

    def stop_service(self) -> None:
        if not self.closer.done():
            self.closer.set_result(None)
