import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3
from web3.contract import Contract
from web3.types import TxReceipt


logger = logging.getLogger(__name__)


SEPOLIA_CHAIN_ID = 11155111

DEFAULT_ADDRESSES = {
    "agent_registry": "0x97b07dDc405B0c28B17559aFFE63BdB3632d0ca3",
    "hackathon_vault": "0x0E7CD8ef9743FEcf94f9103033a044caBD45fC90",
    "risk_router": "0xd6A6952545FF6E6E6681c2d15C59f9EB8F40FdBC",
    "reputation_registry": "0x423a9904e39537a9997fbaF0f220d79D7d545763",
    "validation_registry": "0x92bF63E5C7Ac6980f237a7164Ab413BE226187F1",
}

EIP712_DOMAIN_TYPE = [
    {"name": "name", "type": "string"},
    {"name": "version", "type": "string"},
    {"name": "chainId", "type": "uint256"},
    {"name": "verifyingContract", "type": "address"},
]

TRADE_INTENT_TYPE = [
    {"name": "agentId", "type": "uint256"},
    {"name": "agentWallet", "type": "address"},
    {"name": "pair", "type": "string"},
    {"name": "action", "type": "string"},
    {"name": "amountUsdScaled", "type": "uint256"},
    {"name": "maxSlippageBps", "type": "uint256"},
    {"name": "nonce", "type": "uint256"},
    {"name": "deadline", "type": "uint256"},
]

CHECKPOINT_TYPE = [
    {"name": "agentId", "type": "uint256"},
    {"name": "timestamp", "type": "uint256"},
    {"name": "action", "type": "string"},
    {"name": "pair", "type": "string"},
    {"name": "amountUsdScaled", "type": "uint256"},
    {"name": "priceUsdScaled", "type": "uint256"},
    {"name": "reasoningHash", "type": "bytes32"},
]

# 1. AgentRegistry ABI
AGENT_REGISTRY_ABI = [
    {
        "type": "function",
        "name": "register",
        "inputs": [
            {"name": "agentWallet", "type": "address"},
            {"name": "name", "type": "string"},
            {"name": "description", "type": "string"},
            {"name": "capabilities", "type": "string[]"},
            {"name": "agentURI", "type": "string"}
        ],
        "outputs": [{"name": "agentId", "type": "uint256"}],
        "stateMutability": "nonpayable"
    },
    {
        "type": "function",
        "name": "isRegistered",
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view"
    },
    {
        "type": "function",
        "name": "getAgent",
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "operatorWallet", "type": "address"},
                    {"name": "agentWallet", "type": "address"},
                    {"name": "name", "type": "string"},
                    {"name": "description", "type": "string"},
                    {"name": "capabilities", "type": "string[]"},
                    {"name": "registeredAt", "type": "uint256"},
                    {"name": "active", "type": "bool"}
                ]
            }
        ],
        "stateMutability": "view"
    },
    {
        "type": "function",
        "name": "getSigningNonce",
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view"
    }
]

# 2. HackathonVault ABI
HACKATHON_VAULT_ABI = [
    {
        "type": "function",
        "name": "claimAllocation",
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "outputs": [],
        "stateMutability": "nonpayable"
    },
    {
        "type": "function",
        "name": "getBalance",
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view"
    },
    {
        "type": "function",
        "name": "hasClaimed",
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view"
    },
    {
        "type": "function",
        "name": "allocationPerTeam",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view"
    }
]

# 3. RiskRouter ABI
RISK_ROUTER_ABI = [
    {
        "type": "function",
        "name": "submitTradeIntent",
        "inputs": [
            {
                "name": "intent",
                "type": "tuple",
                "components": [
                    {"name": "agentId", "type": "uint256"},
                    {"name": "agentWallet", "type": "address"},
                    {"name": "pair", "type": "string"},
                    {"name": "action", "type": "string"},
                    {"name": "amountUsdScaled", "type": "uint256"},
                    {"name": "maxSlippageBps", "type": "uint256"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "deadline", "type": "uint256"}
                ]
            },
            {"name": "signature", "type": "bytes"}
        ],
        "outputs": [],
        "stateMutability": "nonpayable"
    },
    {
        "type": "function",
        "name": "simulateIntent",
        "inputs": [
            {
                "name": "intent",
                "type": "tuple",
                "components": [
                    {"name": "agentId", "type": "uint256"},
                    {"name": "agentWallet", "type": "address"},
                    {"name": "pair", "type": "string"},
                    {"name": "action", "type": "string"},
                    {"name": "amountUsdScaled", "type": "uint256"},
                    {"name": "maxSlippageBps", "type": "uint256"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "deadline", "type": "uint256"}
                ]
            }
        ],
        "outputs": [
            {"name": "valid", "type": "bool"},
            {"name": "reason", "type": "string"}
        ],
        "stateMutability": "view"
    },
    {
        "type": "function",
        "name": "getIntentNonce",
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view"
    },
    {
        "type": "event",
        "name": "TradeApproved",
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "agentId", "type": "uint256"},
            {"indexed": False, "name": "intentHash", "type": "bytes32"},
            {"indexed": False, "name": "amountUsdScaled", "type": "uint256"}
        ]
    },
    {
        "type": "event",
        "name": "TradeRejected",
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "agentId", "type": "uint256"},
            {"indexed": False, "name": "intentHash", "type": "bytes32"},
            {"indexed": False, "name": "reason", "type": "string"}
        ]
    }
]

# 4. ValidationRegistry ABI
VALIDATION_REGISTRY_ABI = [
    {
        "type": "function",
        "name": "postAttestation",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "checkpointHash", "type": "bytes32"},
            {"name": "score", "type": "uint8"},
            {"name": "proofType", "type": "uint8"},
            {"name": "proof", "type": "bytes"},
            {"name": "notes", "type": "string"}
        ],
        "outputs": [],
        "stateMutability": "nonpayable"
    },
    {
        "type": "function",
        "name": "postEIP712Attestation",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "checkpointHash", "type": "bytes32"},
            {"name": "score", "type": "uint8"},
            {"name": "notes", "type": "string"}
        ],
        "outputs": [],
        "stateMutability": "nonpayable"
    },
    {
        "type": "function",
        "name": "getAverageValidationScore",
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view"
    }
]

# 5. ReputationRegistry ABI
REPUTATION_REGISTRY_ABI = [
    {
        "type": "function",
        "name": "submitFeedback",
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "score", "type": "uint8"},
            {"name": "outcomeRef", "type": "bytes32"},
            {"name": "comment", "type": "string"},
            {"name": "feedbackType", "type": "uint8"}
        ],
        "outputs": [],
        "stateMutability": "nonpayable"
    },
    {
        "type": "function",
        "name": "getAverageScore",
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view"
    }
]


@dataclass
class TxResult:
    tx_hash: str
    receipt: TxReceipt


class HackathonWeb3Client:
    def __init__(
        self,
        rpc_url: str,
        operator_private_key: str,
        agent_private_key: str,
        addresses: dict[str, str] | None = None,
        chain_id: int = SEPOLIA_CHAIN_ID,
    ) -> None:
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not self.w3.is_connected():
            raise RuntimeError(f"Cannot connect to RPC: {rpc_url}")

        self.chain_id = chain_id
        self.addresses = {**DEFAULT_ADDRESSES, **(addresses or {})}

        self.operator_account = Account.from_key(operator_private_key)
        self.agent_account = Account.from_key(agent_private_key)

        self.agent_registry = self._contract("agent_registry", AGENT_REGISTRY_ABI)
        self.hackathon_vault = self._contract("hackathon_vault", HACKATHON_VAULT_ABI)
        self.risk_router = self._contract("risk_router", RISK_ROUTER_ABI)
        self.validation_registry = self._contract("validation_registry", VALIDATION_REGISTRY_ABI)
        self.reputation_registry = self._contract("reputation_registry", REPUTATION_REGISTRY_ABI)

    def _contract(self, key: str, abi: list[str]) -> Contract:
        addr = Web3.to_checksum_address(self.addresses[key])
        return self.w3.eth.contract(address=addr, abi=abi)

    def _build_tx_base(self, sender: str) -> dict[str, Any]:
        nonce = self.w3.eth.get_transaction_count(sender)
        tx_base: dict[str, Any] = {
            "from": sender,
            "nonce": nonce,
            "chainId": self.chain_id,
        }

        latest = self.w3.eth.get_block("latest")
        base_fee = latest.get("baseFeePerGas")
        if base_fee is not None:
            priority = self.w3.to_wei(2, "gwei")
            tx_base["maxPriorityFeePerGas"] = priority
            tx_base["maxFeePerGas"] = int(base_fee * 2 + priority)
        else:
            tx_base["gasPrice"] = self.w3.eth.gas_price

        return tx_base

    def _send_contract_tx(self, contract_fn: Any, sender_account: Any) -> TxResult:
        tx = contract_fn.build_transaction(self._build_tx_base(sender_account.address))
        gas_estimate = contract_fn.estimate_gas({"from": sender_account.address})
        tx["gas"] = int(gas_estimate * 1.2)

        signed = sender_account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)

        if receipt["status"] != 1:
            raise RuntimeError(f"Transaction failed: {tx_hash.hex()}")

        return TxResult(tx_hash=tx_hash.hex(), receipt=receipt)

    def register_agent(
        self,
        name: str,
        description: str,
        capabilities: list[str],
        agent_uri: str,
        agent_wallet: str | None = None,
    ) -> tuple[int | None, TxResult]:
        wallet = agent_wallet or self.agent_account.address
        tx_result = self._send_contract_tx(
            self.agent_registry.functions.register(
                Web3.to_checksum_address(wallet),
                name,
                description,
                capabilities,
                agent_uri,
            ),
            self.operator_account,
        )

        return self._extract_agent_id_from_receipt(tx_result.receipt), tx_result

    def _extract_agent_id_from_receipt(self, receipt: TxReceipt) -> int | None:
        transfer_topic = Web3.keccak(text="Transfer(address,address,uint256)").hex()
        registry = self.agent_registry.address.lower()
        for log in receipt["logs"]:
            if log["address"].lower() != registry:
                continue
            if not log["topics"] or log["topics"][0].hex().lower() != transfer_topic.lower():
                continue
            if len(log["topics"]) >= 4:
                return int(log["topics"][3].hex(), 16)
        return None

    def claim_allocation(self, agent_id: int) -> TxResult:
        return self._send_contract_tx(
            self.hackathon_vault.functions.claimAllocation(agent_id),
            self.operator_account,
        )

    def get_allocation_balance(self, agent_id: int) -> int:
        return int(self.hackathon_vault.functions.getBalance(agent_id).call())

    def has_claimed_allocation(self, agent_id: int) -> bool:
        return bool(self.hackathon_vault.functions.hasClaimed(agent_id).call())

    def get_intent_nonce(self, agent_id: int) -> int:
        return int(self.risk_router.functions.getIntentNonce(agent_id).call())

    def build_trade_intent(
        self,
        agent_id: int,
        pair: str,
        action: str,
        amount_usd_scaled: int,
        max_slippage_bps: int,
        deadline: int,
        nonce: int | None = None,
        agent_wallet: str | None = None,
    ) -> dict[str, Any]:
        if nonce is None:
            nonce = self.get_intent_nonce(agent_id)

        return {
            "agentId": int(agent_id),
            "agentWallet": Web3.to_checksum_address(agent_wallet or self.agent_account.address),
            "pair": pair,
            "action": action.upper(),
            "amountUsdScaled": int(amount_usd_scaled),
            "maxSlippageBps": int(max_slippage_bps),
            "nonce": int(nonce),
            "deadline": int(deadline),
        }

    def _risk_router_domain(self) -> dict[str, Any]:
        return {
            "name": "RiskRouter",
            "version": "1",
            "chainId": self.chain_id,
            "verifyingContract": self.risk_router.address,
        }

    def sign_trade_intent(self, intent: dict[str, Any]) -> bytes:
        typed_data = {
            "types": {
                "EIP712Domain": EIP712_DOMAIN_TYPE,
                "TradeIntent": TRADE_INTENT_TYPE,
            },
            "primaryType": "TradeIntent",
            "domain": self._risk_router_domain(),
            "message": intent,
        }
        signable = encode_typed_data(full_message=typed_data)
        signed = self.agent_account.sign_message(signable)
        return bytes(signed.signature)

    def simulate_intent(self, intent: dict[str, Any]) -> tuple[bool, str]:
        intent_tuple = self._intent_tuple(intent)
        valid, reason = self.risk_router.functions.simulateIntent(intent_tuple).call()
        return bool(valid), str(reason)

    def submit_trade_intent(self, intent: dict[str, Any], signature: bytes) -> TxResult:
        intent_tuple = self._intent_tuple(intent)
        return self._send_contract_tx(
            self.risk_router.functions.submitTradeIntent(intent_tuple, signature),
            self.operator_account,
        )

    def _intent_tuple(self, intent: dict[str, Any]) -> tuple[Any, ...]:
        return (
            int(intent["agentId"]),
            Web3.to_checksum_address(intent["agentWallet"]),
            str(intent["pair"]),
            str(intent["action"]).upper(),
            int(intent["amountUsdScaled"]),
            int(intent["maxSlippageBps"]),
            int(intent["nonce"]),
            int(intent["deadline"]),
        )

    def build_checkpoint_hash(
        self,
        agent_id: int,
        action: str,
        pair: str,
        amount_usd_scaled: int,
        price_usd_scaled: int,
        reasoning: str,
        timestamp: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        ts = int(timestamp or time.time())
        reasoning_hash = Web3.keccak(text=reasoning)

        checkpoint = {
            "agentId": int(agent_id),
            "timestamp": ts,
            "action": action.upper(),
            "pair": pair,
            "amountUsdScaled": int(amount_usd_scaled),
            "priceUsdScaled": int(price_usd_scaled),
            # bytes32 must be raw 32-byte value or 0x-prefixed 64-hex string.
            "reasoningHash": f"0x{reasoning_hash.hex()}",
        }

        domain = {
            "name": "AITradingAgent",
            "version": "1",
            "chainId": self.chain_id,
            "verifyingContract": self.agent_registry.address,
        }
        typed_data = {
            "types": {
                "EIP712Domain": EIP712_DOMAIN_TYPE,
                "Checkpoint": CHECKPOINT_TYPE,
            },
            "primaryType": "Checkpoint",
            "domain": domain,
            "message": checkpoint,
        }

        signable = encode_typed_data(full_message=typed_data)
        digest = f"0x{Web3.keccak(b'\x19' + signable.version + signable.header + signable.body).hex()}"
        return digest, checkpoint

    def post_checkpoint_attestation(
        self,
        agent_id: int,
        checkpoint_hash: str,
        score: int,
        notes: str,
    ) -> TxResult:
        if score < 0 or score > 100:
            raise ValueError("score must be in [0, 100]")

        sender_account = self.operator_account

        logger.info(
            "Submitting ValidationRegistry checkpoint from operator wallet %s",
            sender_account.address,
        )

        # ValidationRegistry.ProofType.EIP712 == 1
        proof_type_eip712 = 1
        empty_proof = b""
        normalized_hash = (
            checkpoint_hash if str(checkpoint_hash).startswith("0x") else f"0x{checkpoint_hash}"
        )

        return self._send_contract_tx(
            self.validation_registry.functions.postAttestation(
                int(agent_id),
                normalized_hash,
                int(score),
                int(proof_type_eip712),
                empty_proof,
                notes,
            ),
            sender_account,
        )

    def get_validation_score(self, agent_id: int) -> int:
        return int(self.validation_registry.functions.getAverageValidationScore(agent_id).call())

    def get_reputation_score(self, agent_id: int) -> int:
        return int(self.reputation_registry.functions.getAverageScore(agent_id).call())

    @staticmethod
    def append_checkpoint_jsonl(
        log_file: str | Path,
        checkpoint_hash: str,
        checkpoint: dict[str, Any],
        score: int,
        notes: str,
    ) -> None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = {
            "checkpointHash": checkpoint_hash,
            "checkpoint": checkpoint,
            "score": int(score),
            "notes": notes,
            "savedAt": int(time.time()),
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=True) + "\n")
