"""gRPC/proto semantic model (§25, §27, §185)."""

from forge_doctor_api.analyzers.grpc.compat import diff_proto_models
from forge_doctor_api.analyzers.grpc.graph import grpc_graph
from forge_doctor_api.analyzers.grpc.model import (
    GRPC_MODEL_SCHEMA_VERSION,
    GrpcClientCall,
    GrpcProjectModel,
    GrpcRetryPolicy,
    GrpcServiceConfig,
    ProtoDocument,
    ProtoDocumentStatus,
    ProtoEnum,
    ProtoField,
    ProtoFile,
    ProtoIssue,
    ProtoIssueCode,
    ProtoMessage,
    ProtoMethod,
    ProtoService,
    StreamingMode,
)
from forge_doctor_api.analyzers.grpc.parser import load_grpc_project
from forge_doctor_api.analyzers.grpc.reliability import (
    extract_service_configs,
    extract_stub_calls,
)

__all__ = [
    "GRPC_MODEL_SCHEMA_VERSION",
    "GrpcClientCall",
    "GrpcProjectModel",
    "GrpcRetryPolicy",
    "GrpcServiceConfig",
    "ProtoDocument",
    "ProtoDocumentStatus",
    "ProtoEnum",
    "ProtoField",
    "ProtoFile",
    "ProtoIssue",
    "ProtoIssueCode",
    "ProtoMessage",
    "ProtoMethod",
    "ProtoService",
    "StreamingMode",
    "diff_proto_models",
    "extract_service_configs",
    "extract_stub_calls",
    "grpc_graph",
    "load_grpc_project",
]
