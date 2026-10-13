from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class VoteRequest(_message.Message):
    __slots__ = ("client_id", "choice")
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    CHOICE_FIELD_NUMBER: _ClassVar[int]
    client_id: str
    choice: str
    def __init__(self, client_id: _Optional[str] = ..., choice: _Optional[str] = ...) -> None: ...

class VoteResponse(_message.Message):
    __slots__ = ("success", "vote_id", "error", "lamport_ts")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    VOTE_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    vote_id: str
    error: str
    lamport_ts: int
    def __init__(self, success: _Optional[bool] = ..., vote_id: _Optional[str] = ..., error: _Optional[str] = ..., lamport_ts: _Optional[int] = ...) -> None: ...

class VoteRecord(_message.Message):
    __slots__ = ("vote_id", "client_id", "origin_node_id", "lamport_ts", "choice", "received_at_ms", "status", "commit_proof")
    VOTE_ID_FIELD_NUMBER: _ClassVar[int]
    CLIENT_ID_FIELD_NUMBER: _ClassVar[int]
    ORIGIN_NODE_ID_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TS_FIELD_NUMBER: _ClassVar[int]
    CHOICE_FIELD_NUMBER: _ClassVar[int]
    RECEIVED_AT_MS_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    COMMIT_PROOF_FIELD_NUMBER: _ClassVar[int]
    vote_id: str
    client_id: str
    origin_node_id: int
    lamport_ts: int
    choice: str
    received_at_ms: int
    status: str
    commit_proof: str
    def __init__(self, vote_id: _Optional[str] = ..., client_id: _Optional[str] = ..., origin_node_id: _Optional[int] = ..., lamport_ts: _Optional[int] = ..., choice: _Optional[str] = ..., received_at_ms: _Optional[int] = ..., status: _Optional[str] = ..., commit_proof: _Optional[str] = ...) -> None: ...

class ReplicationAck(_message.Message):
    __slots__ = ("success", "node_id", "error", "lamport_ts")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    node_id: int
    error: str
    lamport_ts: int
    def __init__(self, success: _Optional[bool] = ..., node_id: _Optional[int] = ..., error: _Optional[str] = ..., lamport_ts: _Optional[int] = ...) -> None: ...

class FinalizeRequest(_message.Message):
    __slots__ = ("vote_id", "lamport_ts")
    VOTE_ID_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TS_FIELD_NUMBER: _ClassVar[int]
    vote_id: str
    lamport_ts: int
    def __init__(self, vote_id: _Optional[str] = ..., lamport_ts: _Optional[int] = ...) -> None: ...

class FinalizeAck(_message.Message):
    __slots__ = ("success", "node_id", "error", "lamport_ts")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    node_id: int
    error: str
    lamport_ts: int
    def __init__(self, success: _Optional[bool] = ..., node_id: _Optional[int] = ..., error: _Optional[str] = ..., lamport_ts: _Optional[int] = ...) -> None: ...

class SyncRequest(_message.Message):
    __slots__ = ("requester_id", "lamport_ts", "election_term", "initiator_id")
    REQUESTER_ID_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TS_FIELD_NUMBER: _ClassVar[int]
    ELECTION_TERM_FIELD_NUMBER: _ClassVar[int]
    INITIATOR_ID_FIELD_NUMBER: _ClassVar[int]
    requester_id: int
    lamport_ts: int
    election_term: int
    initiator_id: int
    def __init__(self, requester_id: _Optional[int] = ..., lamport_ts: _Optional[int] = ..., election_term: _Optional[int] = ..., initiator_id: _Optional[int] = ...) -> None: ...

class SyncResponse(_message.Message):
    __slots__ = ("votes", "node_id", "lamport_ts")
    VOTES_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TS_FIELD_NUMBER: _ClassVar[int]
    votes: _containers.RepeatedCompositeFieldContainer[VoteRecord]
    node_id: int
    lamport_ts: int
    def __init__(self, votes: _Optional[_Iterable[_Union[VoteRecord, _Mapping]]] = ..., node_id: _Optional[int] = ..., lamport_ts: _Optional[int] = ...) -> None: ...

class HeartbeatPing(_message.Message):
    __slots__ = ("coordinator_id", "lamport_ts", "election_term", "initiator_id")
    COORDINATOR_ID_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TS_FIELD_NUMBER: _ClassVar[int]
    ELECTION_TERM_FIELD_NUMBER: _ClassVar[int]
    INITIATOR_ID_FIELD_NUMBER: _ClassVar[int]
    coordinator_id: int
    lamport_ts: int
    election_term: int
    initiator_id: int
    def __init__(self, coordinator_id: _Optional[int] = ..., lamport_ts: _Optional[int] = ..., election_term: _Optional[int] = ..., initiator_id: _Optional[int] = ...) -> None: ...

class HeartbeatPong(_message.Message):
    __slots__ = ("node_id", "lamport_ts")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TS_FIELD_NUMBER: _ClassVar[int]
    node_id: int
    lamport_ts: int
    def __init__(self, node_id: _Optional[int] = ..., lamport_ts: _Optional[int] = ...) -> None: ...

class ElectionMessage(_message.Message):
    __slots__ = ("sender_id", "candidate_id", "lamport_ts", "election_term", "initiator_id")
    SENDER_ID_FIELD_NUMBER: _ClassVar[int]
    CANDIDATE_ID_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TS_FIELD_NUMBER: _ClassVar[int]
    ELECTION_TERM_FIELD_NUMBER: _ClassVar[int]
    INITIATOR_ID_FIELD_NUMBER: _ClassVar[int]
    sender_id: int
    candidate_id: int
    lamport_ts: int
    election_term: int
    initiator_id: int
    def __init__(self, sender_id: _Optional[int] = ..., candidate_id: _Optional[int] = ..., lamport_ts: _Optional[int] = ..., election_term: _Optional[int] = ..., initiator_id: _Optional[int] = ...) -> None: ...

class ElectionResponse(_message.Message):
    __slots__ = ("ok", "node_id", "lamport_ts")
    OK_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TS_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    node_id: int
    lamport_ts: int
    def __init__(self, ok: _Optional[bool] = ..., node_id: _Optional[int] = ..., lamport_ts: _Optional[int] = ...) -> None: ...

class CoordinatorMessage(_message.Message):
    __slots__ = ("coordinator_id", "lamport_ts", "election_term", "initiator_id")
    COORDINATOR_ID_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TS_FIELD_NUMBER: _ClassVar[int]
    ELECTION_TERM_FIELD_NUMBER: _ClassVar[int]
    INITIATOR_ID_FIELD_NUMBER: _ClassVar[int]
    coordinator_id: int
    lamport_ts: int
    election_term: int
    initiator_id: int
    def __init__(self, coordinator_id: _Optional[int] = ..., lamport_ts: _Optional[int] = ..., election_term: _Optional[int] = ..., initiator_id: _Optional[int] = ...) -> None: ...

class ClusterStatus(_message.Message):
    __slots__ = ("coordinator_id", "this_node_id", "election_algorithm", "known_peers", "active_peers", "role", "election_term", "lamport_ts", "accepting_votes")
    COORDINATOR_ID_FIELD_NUMBER: _ClassVar[int]
    THIS_NODE_ID_FIELD_NUMBER: _ClassVar[int]
    ELECTION_ALGORITHM_FIELD_NUMBER: _ClassVar[int]
    KNOWN_PEERS_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_PEERS_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    ELECTION_TERM_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TS_FIELD_NUMBER: _ClassVar[int]
    ACCEPTING_VOTES_FIELD_NUMBER: _ClassVar[int]
    coordinator_id: int
    this_node_id: int
    election_algorithm: str
    known_peers: _containers.RepeatedScalarFieldContainer[int]
    active_peers: _containers.RepeatedScalarFieldContainer[int]
    role: str
    election_term: int
    lamport_ts: int
    accepting_votes: bool
    def __init__(self, coordinator_id: _Optional[int] = ..., this_node_id: _Optional[int] = ..., election_algorithm: _Optional[str] = ..., known_peers: _Optional[_Iterable[int]] = ..., active_peers: _Optional[_Iterable[int]] = ..., role: _Optional[str] = ..., election_term: _Optional[int] = ..., lamport_ts: _Optional[int] = ..., accepting_votes: _Optional[bool] = ...) -> None: ...

class TallyResponse(_message.Message):
    __slots__ = ("tally", "total_votes", "lamport_ts")
    class TallyEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    TALLY_FIELD_NUMBER: _ClassVar[int]
    TOTAL_VOTES_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TS_FIELD_NUMBER: _ClassVar[int]
    tally: _containers.ScalarMap[str, int]
    total_votes: int
    lamport_ts: int
    def __init__(self, tally: _Optional[_Mapping[str, int]] = ..., total_votes: _Optional[int] = ..., lamport_ts: _Optional[int] = ...) -> None: ...

class Ack(_message.Message):
    __slots__ = ("success", "lamport_ts")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    LAMPORT_TS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    lamport_ts: int
    def __init__(self, success: _Optional[bool] = ..., lamport_ts: _Optional[int] = ...) -> None: ...

class Empty(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...
