from __future__ import annotations

import functools
import time
from abc import ABC, abstractmethod
from enum import IntEnum
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar

from .core import Account, ChainInterface, default_chain
from .development_chains import AnvilDevChain, GanacheDevChain, HardhatDevChain
from .internal import TransactionRevertedError, UnknownEvent
from .json_rpc.communicator import JsonRpcError, TxParams

T = TypeVar("T")


class TransactionStatusEnum(IntEnum):
    PENDING = -1
    SUCCESS = 1
    FAILURE = 0


class TransactionTypeEnum(IntEnum):
    LEGACY = 0
    EIP2930 = 1
    EIP1559 = 2


def _fetch_tx_data(f):
    @functools.wraps(f)
    def wrapper(self: TransactionAbc):
        if self._tx_data is None:
            self._tx_data = self._chain.dev_chain.get_transaction(self.tx_hash)
        return f(self)

    return wrapper


def _fetch_tx_receipt(f):
    @functools.wraps(f)
    def wrapper(self: TransactionAbc):
        if self._tx_receipt is None:
            self.wait()
        assert self._tx_receipt is not None
        return f(self)

    return wrapper


class TransactionAbc(ABC, Generic[T]):
    _tx_hash: str
    _tx_params: TxParams
    _chain: ChainInterface
    _abi: Optional[Dict]
    _return_type: Type
    _recipient_fqn: Optional[str]
    _tx_data: Optional[Dict[str, Any]]
    _tx_receipt: Optional[Dict[str, Any]]
    _trace_transaction: Optional[List[Dict[str, Any]]]
    _debug_trace_transaction = Optional[Dict[str, Any]]
    _error: Optional[TransactionRevertedError]
    _events: Optional[List]

    def __init__(
        self,
        tx_hash: str,
        tx_params: TxParams,
        abi: Optional[Dict],
        return_type: Type,
        recipient_fqn: Optional[str],
        chain: Optional[ChainInterface] = None,
    ):
        self._tx_hash = tx_hash
        self._tx_params = tx_params
        self._abi = abi
        self._return_type = return_type
        self._recipient_fqn = recipient_fqn
        if chain is None:
            chain = default_chain
        self._chain = chain

        self._tx_data = None
        self._tx_receipt = None
        self._trace_transaction = None
        self._debug_trace_transaction = None
        self._error = None
        self._events = None

    @property
    def tx_hash(self) -> str:
        return self._tx_hash

    @property
    def chain(self) -> ChainInterface:
        return self._chain

    @property
    @_fetch_tx_data
    def block_hash(self) -> str:
        return self._tx_data["blockHash"]  # pyright: reportOptionalSubscript=false

    @property
    @_fetch_tx_data
    def block_number(self) -> int:
        return int(
            self._tx_data["blockNumber"], 16
        )  # pyright: reportOptionalSubscript=false

    @property
    @_fetch_tx_data
    def from_(self) -> Account:
        return Account(
            self._tx_data["from"], self._chain
        )  # pyright: reportOptionalSubscript=false

    @property
    @_fetch_tx_data
    def to(self) -> Account:
        return Account(
            self._tx_data["to"], self._chain
        )  # pyright: reportOptionalSubscript=false

    @property
    @_fetch_tx_data
    def gas(self) -> int:
        return int(self._tx_data["gas"], 16)  # pyright: reportOptionalSubscript=false

    @property
    @_fetch_tx_data
    def nonce(self) -> int:
        return int(self._tx_data["nonce"], 16)  # pyright: reportOptionalSubscript=false

    @property
    @_fetch_tx_data
    def tx_index(self) -> int:
        return int(
            self._tx_data["transactionIndex"], 16
        )  # pyright: reportOptionalSubscript=false

    @property
    @_fetch_tx_data
    def value(self) -> int:
        return int(self._tx_data["value"], 16)  # pyright: reportOptionalSubscript=false

    @property
    @_fetch_tx_data
    def r(self) -> int:
        return int(self._tx_data["r"], 16)  # pyright: reportOptionalSubscript=false

    @property
    @_fetch_tx_data
    def s(self) -> int:
        return int(self._tx_data["s"], 16)  # pyright: reportOptionalSubscript=false

    @property
    @_fetch_tx_receipt
    def gas_used(self) -> int:
        return int(
            self._tx_receipt["gasUsed"], 16
        )  # pyright: reportOptionalSubscript=false

    @property
    @_fetch_tx_receipt
    def cumulative_gas_used(self) -> int:
        return int(
            self._tx_receipt["cumulativeGasUsed"], 16
        )  # pyright: reportOptionalSubscript=false

    @property
    def status(self) -> TransactionStatusEnum:
        if self._tx_receipt is None:
            receipt = self._chain.dev_chain.get_transaction_receipt(self._tx_hash)
            if receipt is None:
                return TransactionStatusEnum.PENDING
            else:
                self._tx_receipt = receipt

        if int(self._tx_receipt["status"], 16) == 0:
            return TransactionStatusEnum.FAILURE
        else:
            return TransactionStatusEnum.SUCCESS

    def wait(self) -> None:
        for _ in range(40):
            if self.status != TransactionStatusEnum.PENDING:
                return

        while self.status == TransactionStatusEnum.PENDING:
            time.sleep(0.25)

    def _fetch_trace_transaction(self) -> None:
        if self._trace_transaction is None:
            dev_chain = self._chain.dev_chain
            assert isinstance(dev_chain, AnvilDevChain)
            self._trace_transaction = dev_chain.trace_transaction(self._tx_hash)

    def _fetch_debug_trace_transaction(self) -> None:
        if self._debug_trace_transaction is None:
            self._debug_trace_transaction = (
                self._chain.dev_chain.debug_trace_transaction(
                    self._tx_hash,
                    {"enableMemory": True},
                )
            )

    @property
    @_fetch_tx_receipt
    def console_logs(self) -> list:
        dev_chain = self._chain.dev_chain

        if isinstance(dev_chain, AnvilDevChain):
            self._fetch_trace_transaction()
            assert self._trace_transaction is not None
            return self._chain._process_console_logs(self._trace_transaction)
        else:
            raise NotImplementedError

    @property
    @_fetch_tx_receipt
    def events(self) -> list:
        if self._events is not None:
            return self._events

        assert self._tx_receipt is not None

        if self._recipient_fqn is None:
            assert len(self._tx_receipt["logs"]) == 0
            self._events = []
            return self._events

        self._events = self._chain._process_events(
            self._tx_hash, self._tx_receipt["logs"], self._recipient_fqn
        )
        return self._events

    @property
    @_fetch_tx_receipt
    def raw_events(self) -> List[UnknownEvent]:
        assert self._tx_receipt is not None

        ret = []
        for log in self._tx_receipt["logs"]:
            topics = [
                bytes.fromhex(t[2:]) if t.startswith("0x") else bytes.fromhex(t)
                for t in log["topics"]
            ]
            data = (
                bytes.fromhex(log["data"][2:])
                if log["data"].startswith("0x")
                else bytes.fromhex(log["data"])
            )
            ret.append(UnknownEvent(topics, data))
        return ret

    @property
    @_fetch_tx_receipt
    def error(self) -> Optional[TransactionRevertedError]:
        if self.status == TransactionStatusEnum.SUCCESS:
            return None

        if self._error is not None:
            return self._error

        dev_chain = self._chain.dev_chain

        # call with the same parameters should also revert
        try:
            dev_chain.call(self._tx_params)
            assert False, "Call should have reverted"
        except JsonRpcError as e:
            try:
                if isinstance(dev_chain, (AnvilDevChain, GanacheDevChain)):
                    revert_data = e.data["data"]
                elif isinstance(dev_chain, HardhatDevChain):
                    revert_data = e.data["data"]["data"]
                else:
                    raise NotImplementedError

                if revert_data.startswith("0x"):
                    revert_data = revert_data[2:]
            except Exception:
                raise e from None

        try:
            assert self._recipient_fqn is not None
            self._chain._process_revert_data(
                self._tx_hash, bytes.fromhex(revert_data), self._recipient_fqn
            )
        except TransactionRevertedError as e:
            self._error = e
            return e

    @property
    @_fetch_tx_receipt
    def return_value(self) -> T:
        if self.status != TransactionStatusEnum.SUCCESS:
            e = self.error
            assert e is not None
            raise e

        assert self._tx_receipt is not None
        if (
            "contractAddress" in self._tx_receipt
            and self._tx_receipt["contractAddress"] is not None
        ):
            return self._return_type(self._tx_receipt["contractAddress"], self._chain)

        assert self._abi is not None

        dev_chain = self._chain.dev_chain
        if isinstance(dev_chain, AnvilDevChain):
            self._fetch_trace_transaction()
            assert self._trace_transaction is not None
            output = bytes.fromhex(self._trace_transaction[0]["result"]["output"][2:])
            return self._chain._process_return_data(
                output, self._abi, self._return_type
            )
        else:
            self._fetch_debug_trace_transaction()
            assert self._debug_trace_transaction is not None
            output = bytes.fromhex(self._debug_trace_transaction["returnValue"])  # type: ignore
            return self._chain._process_return_data(
                output, self._abi, self._return_type
            )

    @property
    @abstractmethod
    def type(self) -> TransactionTypeEnum:
        ...


class LegacyTransaction(TransactionAbc[T]):
    @property
    @_fetch_tx_data
    def v(self) -> int:
        return int(self._tx_data["v"], 16)  # pyright: reportOptionalSubscript=false

    @property
    @_fetch_tx_data
    def gas_price(self) -> int:
        return int(
            self._tx_data["gasPrice"], 16
        )  # pyright: reportOptionalSubscript=false

    @property
    @_fetch_tx_data
    def type(self) -> TransactionTypeEnum:
        assert (
            int(self._tx_data["type"], 16) == 0
        )  # pyright: reportOptionalSubscript=false
        return TransactionTypeEnum.LEGACY