import re
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple, cast

from aiohttp import hdrs, web

from opentelemetry import metrics, trace
from opentelemetry.sdk.trace import Span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.util.http import ExcludeList
from opentelemetry.util.types import AttributeValue
from tomodachi.transport.aws_sns_sqs import MessageAttributesType
from tomodachi.transport.http import get_forwarded_remote_ip


class OpenTelemetryTomodachiMiddleware:
    duration_instrument_args: Tuple[str, str, str]
    duration_instrument_attributes: Tuple[str, ...]
    active_tasks_instrument_args: Tuple[str, str, str]
    active_tasks_instrument_attributes: Tuple[str, ...]

    _duration_histogram: Optional[metrics.Histogram] = None
    _active_tasks_counter: Optional[metrics.UpDownCounter] = None

    def __init__(
        self, service: Any, tracer: Optional[trace.Tracer] = None, meter: Optional[metrics.Meter] = None, **kwargs: Any
    ) -> None:
        self.service = service
        self.tracer = tracer
        self.meter = meter

        if meter:
            self._duration_histogram = meter.create_histogram(*self.duration_instrument_args)
            self._active_tasks_counter = meter.create_up_down_counter(*self.active_tasks_instrument_args)

    def increase_active_tasks(
        self, span: Span, extra_attributes: Optional[Dict[str, AttributeValue]] = None, *, value: int = 1
    ) -> None:
        if self._active_tasks_counter and span.attributes:
            attributes = span.attributes
            attributes_ = {k: attributes[k] for k in self.active_tasks_instrument_attributes if k in attributes}
            if extra_attributes:
                attributes_.update(extra_attributes)
            self._active_tasks_counter.add(value, attributes_)

    def decrease_active_tasks(
        self, span: Span, extra_attributes: Optional[Dict[str, AttributeValue]] = None, *, value: int = -1
    ) -> None:
        self.increase_active_tasks(span, extra_attributes, value=value)

    def record_duration(self, span: Span, extra_attributes: Optional[Dict[str, AttributeValue]] = None) -> None:
        if self._duration_histogram and span.start_time and span.end_time and span.attributes:
            attributes = span.attributes
            attributes_ = {k: attributes[k] for k in self.duration_instrument_attributes if k in attributes}
            if extra_attributes:
                attributes_.update(extra_attributes)

            duration_ns = span.end_time - span.start_time
            duration = duration_ns / 1e9

            self._duration_histogram.record(duration, attributes_)


@web.middleware
class OpenTelemetryAioHTTPMiddleware(OpenTelemetryTomodachiMiddleware):
    duration_instrument_args = (
        "http.server.duration",
        "s",
        "Measures the duration of inbound HTTP requests.",
    )
    duration_instrument_attributes = (
        "http.route",
        "http.request.method",
        "http.response.status_code",
        "network.protocol.name",
        "network.protocol.version",
        "server.address",
        "server.port",
        "url.scheme",
    )
    active_tasks_instrument_args = (
        "http.server.active_requests",
        "{request}",
        "Measures the number of concurrent HTTP requests that are currently in-flight.",
    )
    active_tasks_instrument_attributes = (
        "http.request.method",
        "server.address",
        "server.port",
        "url.scheme",
    )

    def __init__(
        self,
        service: Any,
        tracer: Optional[trace.Tracer] = None,
        meter: Optional[metrics.Meter] = None,
        excluded_urls: Optional[ExcludeList] = None,
    ) -> None:
        super().__init__(service, tracer, meter)
        self.excluded_urls = excluded_urls

    def get_route(self, request: web.Request) -> Optional[str]:
        route: Optional[str]
        try:
            route = getattr(request.match_info.route._resource, "_simplified_pattern", None)
        except Exception:
            route = None

        if not route:
            pattern = request.match_info.route.get_info().get("pattern")
            if not pattern:
                return None
            simplified = re.compile(r"^\^?(.+?)\$?$").match(pattern.pattern)
            route = simplified.group(1) if simplified else None

        return route

    def get_attributes(self, request: web.Request) -> Dict[str, AttributeValue]:
        protocol_version = ".".join(map(str, request.version))
        route: Optional[str] = self.get_route(request)

        client_socket_addr = None
        client_socket_port = None
        if request._transport_peername:
            client_socket_addr, client_socket_port = cast(Tuple[str, int], request._transport_peername)

        server_ip = None
        server_port = None
        if request.transport:
            sock = request.transport.get_extra_info("socket")
            if sock:
                sockname = sock.getsockname()
                if sockname:
                    server_ip, server_port = cast(Tuple[str, int], sockname)

        host = request.headers.get(hdrs.HOST)
        port = int(host.split(":")[1]) if host and ":" in host else 80

        attributes: Dict[str, AttributeValue] = {}

        if request.method:
            attributes["http.request.method"] = request.method

        if route:
            attributes["http.route"] = route

        attributes["server.address"] = host.split(":")[0] if host is not None else (server_ip or "127.0.0.1")
        attributes["server.port"] = port if host is not None else (server_port or port)

        attributes["url.scheme"] = request.scheme
        attributes["url.path"] = request.path

        if request.query_string:
            attributes["url.query"] = request.query_string

        user_agent = request.headers.get(hdrs.USER_AGENT)
        if user_agent:
            attributes["user_agent.original"] = user_agent

        attributes["client.address"] = get_forwarded_remote_ip(request)

        if client_socket_addr and client_socket_port:
            attributes["client.socket.address"] = client_socket_addr
            attributes["client.socket.port"] = client_socket_port

        if server_ip:
            attributes["server.socket.address"] = server_ip

        attributes["server.socket.port"] = server_port or port
        attributes["network.protocol.version"] = protocol_version

        return attributes

    async def __call__(
        self,
        request: web.Request,
        handler: Callable[..., Awaitable[web.Response]],
    ) -> web.Response:
        exclude_instrumentation: bool = any(
            [
                getattr(self.service, "_is_instrumented_by_opentelemetry", False) is False,
                self.excluded_urls and self.excluded_urls.url_disabled(request.path),
            ]
        )
        if exclude_instrumentation or not self.tracer:
            return await handler(request)

        attributes = self.get_attributes(request)
        route = cast(Optional[str], attributes.get("http.route"))
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        response: Optional[web.Response] = None

        span = cast(
            Span,
            self.tracer.start_span(
                name=f"{request.method} {route}" if route else request.method,
                kind=trace.SpanKind.SERVER,
                context=ctx,
                attributes=attributes,
            ),
        )
        with trace.use_span(span, end_on_exit=False):
            try:
                self.increase_active_tasks(span)
                response = await handler(request)
            except web.HTTPException as exc:
                response = exc
                if exc.status < 100 or exc.status >= 500:
                    raise
            finally:
                if (
                    response is not None
                    and isinstance(getattr(response, "status", None), int)
                    and response.status >= 100
                    and response.status <= 599
                ):
                    span.set_attribute("http.response.status_code", response.status)
                    if response.status >= 500:
                        span.set_status(trace.StatusCode.ERROR)
                    if response.status == 499:
                        replaced_status_code = getattr(response, "_replaced_status_code", None)
                        if replaced_status_code:
                            span.set_status(
                                trace.StatusCode.ERROR,
                                "Client closed the connection while the server was still processing the request.",
                            )
                            span.set_attribute("http.response.status_code", replaced_status_code)
                        else:
                            span.set_status(
                                trace.StatusCode.ERROR,
                                "Client closed the connection before the server could start processing the request.",
                            )
                else:
                    span.set_attribute("http.response.status_code", 500)
                    span.set_status(trace.StatusCode.ERROR)
                    response = None

                span.end()
                self.record_duration(span)
                self.decrease_active_tasks(span)

        if response is None:
            response = web.HTTPInternalServerError()
            response.body = b""
            response.headers[hdrs.CONNECTION] = "close"
            response.force_close()

        if isinstance(response, (web.HTTPException, web.HTTPInternalServerError)):
            raise response

        return response


class OpenTelemetryAWSSQSMiddleware(OpenTelemetryTomodachiMiddleware):
    duration_instrument_args = (
        "messaging.amazonsqs.duration",
        "s",
        "Measures the duration of processing a message by the handler function.",
    )
    duration_instrument_attributes = (
        "messaging.source.name",
        "messaging.source.kind",
        "messaging.destination.name",
        "messaging.destination.kind",
        "code.function",
    )
    active_tasks_instrument_args = (
        "messaging.amazonsqs.active_tasks",
        "{message}",
        "Measures the number of concurrent SQS messages that are currently being processed.",
    )
    active_tasks_instrument_attributes = (
        "messaging.source.name",
        "messaging.source.kind",
        "messaging.destination.name",
        "messaging.destination.kind",
        "code.function",
    )

    async def __call__(
        self,
        handler: Callable[..., Awaitable[None]],
        *,
        topic: str,
        queue_url: str,
        message_attributes: MessageAttributesType,
        sns_message_id: str,
        sqs_message_id: str,
    ) -> None:
        if getattr(self.service, "_is_instrumented_by_opentelemetry", False) is False or not self.tracer:
            await handler()
            return

        queue_name = queue_url.rsplit("/")[-1]

        attributes: Dict[str, AttributeValue] = {
            "messaging.system": "AmazonSQS",
            "messaging.operation": "process",
            "messaging.source.name": queue_name,
            "messaging.source.kind": "queue",
            "messaging.message.id": sns_message_id or sqs_message_id,
            "messaging.destination.name": topic if topic else queue_name,
            "messaging.destination.kind": "topic" if topic else "queue",
            "code.function": handler.__name__,
        }

        ctx = TraceContextTextMapPropagator().extract(carrier=message_attributes)

        span = cast(
            Span,
            self.tracer.start_span(
                name=f"{topic} process",
                kind=trace.SpanKind.CONSUMER,
                context=ctx,
                attributes=attributes,
            ),
        )
        with trace.use_span(span, end_on_exit=False):
            try:
                self.increase_active_tasks(span)
                await handler()
                span.set_status(trace.StatusCode.OK)
            except Exception as exc:
                span.set_status(trace.StatusCode.ERROR)
                span.record_exception(exc, escaped=True)
                raise
            finally:
                span.end()
                self.record_duration(span, {"function.success": span.status.is_ok})
                self.decrease_active_tasks(span)


class OpenTelemetryAMQPMiddleware(OpenTelemetryTomodachiMiddleware):
    duration_instrument_args = (
        "messaging.rabbitmq.duration",
        "s",
        "Measures the duration of processing a message by the handler function.",
    )
    duration_instrument_attributes = (
        "messaging.destination.name",
        "messaging.rabbitmq.destination.routing_key",
        "code.function",
    )
    active_tasks_instrument_args = (
        "messaging.rabbitmq.active_tasks",
        "{message}",
        "Measures the number of concurrent AMQP messages that are currently being processed.",
    )
    active_tasks_instrument_attributes = (
        "messaging.destination.name",
        "messaging.rabbitmq.destination.routing_key",
        "code.function",
    )

    async def __call__(
        self,
        handler: Callable[..., Awaitable[None]],
        *,
        routing_key: str,
        exchange_name: str,
        properties: Any,
    ) -> None:
        if getattr(self.service, "_is_instrumented_by_opentelemetry", False) is False or not self.tracer:
            await handler()
            return

        if not exchange_name:
            exchange_name = "amq.topic"

        attributes: Dict[str, AttributeValue] = {
            "messaging.system": "rabbitmq",
            "messaging.operation": "process",
            "messaging.destination.name": exchange_name,
            "messaging.rabbitmq.destination.routing_key": routing_key,
            "code.function": handler.__name__,
        }

        headers = getattr(properties, "headers", {})
        if not isinstance(headers, dict):
            headers = {}
        ctx = TraceContextTextMapPropagator().extract(carrier=headers)

        span = cast(
            Span,
            self.tracer.start_span(
                name=f"{routing_key} process",
                kind=trace.SpanKind.CONSUMER,
                context=ctx,
                attributes=attributes,
            ),
        )
        with trace.use_span(span, end_on_exit=False):
            try:
                self.increase_active_tasks(span)
                await handler()
                span.set_status(trace.StatusCode.OK)
            except Exception as exc:
                span.set_status(trace.StatusCode.ERROR)
                span.record_exception(exc, escaped=True)
                raise
            finally:
                span.end()
                self.record_duration(span, {"function.success": span.status.is_ok})
                self.decrease_active_tasks(span)


class OpenTelemetryScheduleFunctionMiddleware(OpenTelemetryTomodachiMiddleware):
    duration_instrument_args = (
        "function.duration",
        "s",
        "Measures the duration of running the scheduled handler function.",
    )
    duration_instrument_attributes = ("code.function",)
    active_tasks_instrument_args = (
        "function.active_tasks",
        "{task}",
        "Measures the number of concurrent invocations of the scheduled handler that is currently running.",
    )
    active_tasks_instrument_attributes = ("code.function",)

    async def __call__(
        self,
        handler: Callable[..., Awaitable[None]],
        *,
        invocation_time: str = "",
        interval: str = "",
    ) -> None:
        if getattr(self.service, "_is_instrumented_by_opentelemetry", False) is False or not self.tracer:
            await handler()
            return

        attributes: Dict[str, AttributeValue] = {
            "code.function": handler.__name__,
            "function.trigger": "timer",
            "function.time": invocation_time,
        }

        if interval:
            attributes["function.interval"] = str(interval)

        span = cast(
            Span,
            self.tracer.start_span(
                name=handler.__name__,
                kind=trace.SpanKind.INTERNAL,
                attributes=attributes,
            ),
        )
        with trace.use_span(span, end_on_exit=False):
            try:
                self.increase_active_tasks(span)
                await handler()
                span.set_status(trace.StatusCode.OK)
            except Exception as exc:
                span.set_status(trace.StatusCode.ERROR)
                span.record_exception(exc, escaped=True)
                raise
            finally:
                span.end()
                self.record_duration(span, {"function.success": span.status.is_ok})
                self.decrease_active_tasks(span)
