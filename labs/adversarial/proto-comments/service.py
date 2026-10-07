# Notes on the old grpc design (kept for history):
#
#   syntax = "proto3";
#   service PaymentService {
#     rpc Charge(ChargeRequest) returns (ChargeResponse);
#   }
#
# The python side never implemented it.


def nothing() -> None:
    pass
