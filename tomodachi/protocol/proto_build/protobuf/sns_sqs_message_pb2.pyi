# @generated by generate_proto_mypy_stubs.py.  Do not edit!
import google.protobuf.message
import typing

class Service(google.protobuf.message.Message):
    name = ... # type: typing.Text
    uuid = ... # type: typing.Text

    def __init__(self,
        name : typing.Optional[typing.Text] = None,
        uuid : typing.Optional[typing.Text] = None,
        ) -> None: ...
    @classmethod
    def FromString(cls, s: bytes) -> Service: ...
    def MergeFrom(self, other_msg: google.protobuf.message.Message) -> None: ...
    def CopyFrom(self, other_msg: google.protobuf.message.Message) -> None: ...

class Metadata(google.protobuf.message.Message):
    message_uuid = ... # type: typing.Text
    protocol_version = ... # type: typing.Text
    timestamp = ... # type: float
    topic = ... # type: typing.Text
    data_encoding = ... # type: typing.Text

    def __init__(self,
        message_uuid : typing.Optional[typing.Text] = None,
        protocol_version : typing.Optional[typing.Text] = None,
        timestamp : typing.Optional[float] = None,
        topic : typing.Optional[typing.Text] = None,
        data_encoding : typing.Optional[typing.Text] = None,
        ) -> None: ...
    @classmethod
    def FromString(cls, s: bytes) -> Metadata: ...
    def MergeFrom(self, other_msg: google.protobuf.message.Message) -> None: ...
    def CopyFrom(self, other_msg: google.protobuf.message.Message) -> None: ...

class SNSSQSMessage(google.protobuf.message.Message):
    data = ... # type: bytes

    @property
    def service(self) -> Service: ...

    @property
    def metadata(self) -> Metadata: ...

    def __init__(self,
        service : typing.Optional[Service] = None,
        metadata : typing.Optional[Metadata] = None,
        data : typing.Optional[bytes] = None,
        ) -> None: ...
    @classmethod
    def FromString(cls, s: bytes) -> SNSSQSMessage: ...
    def MergeFrom(self, other_msg: google.protobuf.message.Message) -> None: ...
    def CopyFrom(self, other_msg: google.protobuf.message.Message) -> None: ...

