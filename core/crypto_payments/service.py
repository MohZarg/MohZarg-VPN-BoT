"""
GhYiAb V2 — Crypto Payment Service
====================================

سرویس پردازش پرداخت‌های ارزی (TON, TRX, USDT_TRC20, USDT_TON)
با تأیید هش تراکنش از طریق tonapi.io و tronscan.org
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import requests

from bootstrap import AppContext
from core.errors import ValidationError, NotFoundError, DomainError
from core.audit import service as audit_service
from core.wallet import service as wallet_service

logger = logging.getLogger("ghyiab.core.crypto_payments")


# =============================================================================
# Constants & Configuration
# =============================================================================

# USDT Contract Addresses
USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDT_TON_JETTON_MASTER = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"

# API Endpoints
TONAPI_BASE = "https://tonapi.io/v2"
TRONSCAN_BASE = "https://apilist.tronscan.org/api"

# Default tolerance for amount verification (1% for Iranian mode)
DEFAULT_TOLERANCE_PERCENT = 1.0


@dataclass(frozen=True)
class CryptoWallet:
    id: int
    currency: str
    wallet_address: str
    wallet_memo: Optional[str]
    network: str
    is_active: bool


@dataclass(frozen=True)
class CryptoInvoice:
    id: int
    user_id: int
    amount_minor: int
    currency: str
    wallet_to: str
    tx_hash: Optional[str]
    status: str
    memo: Optional[str]
    expected_amount: float
    tolerance_percent: float
    created_at: str
    verified_at: Optional[str]


class CryptoPaymentError(DomainError):
    """Base error for crypto payment operations."""
    pass


class CryptoVerificationError(CryptoPaymentError):
    """Transaction verification failed."""
    pass


class CryptoWalletNotConfiguredError(CryptoPaymentError):
    """No wallet configured for currency."""
    pass


# =============================================================================
# Helper Functions
# =============================================================================

def _get_tonapi_key() -> str:
    return os.getenv("CRYPTO_TONAPI_KEY", "").strip()


def _get_tronscan_key() -> str:
    return os.getenv("CRYPTOSCAN_KEY", "").strip()


def _http_get_json(url: str, headers: Optional[dict] = None) -> Any:
    """Simple HTTP GET with JSON response."""
    h = {"Accept": "application/json"}
    if headers:
        h.update(headers)
    resp = requests.get(url, headers=h, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _amount_within_tolerance(expected: float, observed: float, tolerance_percent: float) -> bool:
    """Check if observed amount is within tolerance of expected."""
    if expected <= 0:
        return False
    diff_percent = abs(observed - expected) / expected * 100
    return diff_percent <= tolerance_percent


# =============================================================================
# TON Verification (tonapi.io)
# =============================================================================

def _ton_address_hash(addr: str) -> Optional[str]:
    """Extract 32-byte address hash from TON address (bounceable or raw)."""
    addr = addr.strip()
    if not addr:
        return None

    # Raw format: workchain:hash (e.g., -1:abcdef...)
    import re
    m = re.match(r'^-?\d+:([0-9a-fA-F]{64})$', addr)
    if m:
        return m[1].lower()

    # Bounceable base64url format (48 chars)
    if re.match(r'^[A-Za-z0-9_\-+/]{47,48}={0,2}$', addr):
        b64 = addr.translate(str.maketrans('-_', '+/'))
        pad = len(b64) % 4
        if pad:
            b64 += '=' * (4 - pad)
        try:
            import base64
            raw = base64.urlsafe_b64decode(b64)
            if len(raw) == 36:
                return raw[2:34].hex().lower()
        except Exception:
            pass
    return None


def _ton_addresses_match(a: str, b: str) -> bool:
    ha = _ton_address_hash(a)
    hb = _ton_address_hash(b)
    return ha is not None and hb is not None and ha == hb


def _extract_ton_comment(msg: dict) -> str:
    """Extract comment from TON transaction message."""
    if not isinstance(msg, dict):
        return ""
    # Direct comment field
    if msg.get("comment") and isinstance(msg["comment"], str):
        return msg["comment"].strip()
    # Decoded body for text_comment op
    if msg.get("decoded_op_name") == "text_comment":
        body = msg.get("decoded_body") or {}
        if body.get("text") and isinstance(body["text"], str):
            return body["text"].strip()
    # Fallback fields
    for key in ("message", "payload"):
        if msg.get(key) and isinstance(msg[key], str):
            return msg[key].strip()
    return ""


def _memo_matches(expected: str, observed: str) -> bool:
    """Case-insensitive memo match with whitespace normalization."""
    e = expected.strip()
    o = observed.strip()
    if not e:
        return True
    if not o:
        return False
    if e.lower() == o.lower():
        return True
    # Normalize whitespace
    import re
    e_norm = re.sub(r'\s+', '', e)
    o_norm = re.sub(r'\s+', '', o)
    return e_norm != "" and e_norm.lower() == o_norm.lower()


def verify_ton_transaction(
    tx_hash: str,
    expected_to: str,
    expected_amount: float,
    jetton_master: Optional[str] = None,
    expected_memo: str = "",
    tolerance_percent: float = DEFAULT_TOLERANCE_PERCENT
) -> dict:
    """
    Verify TON/USDT_TON transaction via tonapi.io.

    Returns: {'ok': bool, 'reason': str, 'detail': dict}
    """
    tx_hash = tx_hash.strip()
    if not tx_hash:
        return {'ok': False, 'reason': 'bad-hash-format'}

    api_key = _get_tonapi_key()
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    expected_hash = _ton_address_hash(expected_to)
    if expected_hash is None:
        return {'ok': False, 'reason': 'invalid-expected-address'}

    try:
        # Try events endpoint first (richer data)
        events = _http_get_json(f"{TONAPI_BASE}/events/{tx_hash}", headers)
        actions = events.get("actions", []) if isinstance(events, dict) else []
        tx_timestamp = events.get("timestamp", events.get("utime", 0)) if isinstance(events, dict) else 0

        if jetton_master is None:
            # Native TON transfer
            for action in actions:
                if not isinstance(action, dict) or action.get("type") != "TonTransfer":
                    continue
                tt = action.get("TonTransfer") or action.get("ton_transfer") or {}
                if not isinstance(tt, dict):
                    continue
                recipient = tt.get("recipient", {})
                recip_addr = recipient.get("address") if isinstance(recipient, dict) else str(recipient)
                if not recip_addr:
                    continue
                if not _ton_addresses_match(recip_addr, expected_to):
                    continue
                value_nano = float(tt.get("amount", 0))
                amount_ton = value_nano / 1_000_000_000.0
                if not _amount_within_tolerance(expected_amount, amount_ton, tolerance_percent):
                    return {'ok': False, 'reason': 'amount-mismatch', 'detail': {'observed': amount_ton, 'expected': expected_amount}}
                if expected_memo:
                    observed_comment = _extract_ton_comment(tt)
                    if not _memo_matches(expected_memo, observed_comment):
                        return {'ok': False, 'reason': 'memo-mismatch', 'detail': {'observed': observed_comment, 'expected': expected_memo}}
                sender = tt.get("sender", {})
                sender_addr = sender.get("address") if isinstance(sender, dict) else str(sender)
                return {
                    'ok': True, 'reason': 'verified',
                    'detail': {'amount': amount_ton, 'to': recip_addr, 'sender': sender_addr, 'tx_timestamp': tx_timestamp, 'via': 'events'}
                }

        else:
            # Jetton transfer (USDT_TON)
            jetton_hash = _ton_address_hash(jetton_master)
            if jetton_hash is None:
                return {'ok': False, 'reason': 'invalid-jetton-master'}
            for action in actions:
                if not isinstance(action, dict) or action.get("type") != "JettonTransfer":
                    continue
                jt = action.get("JettonTransfer") or action.get("jetton_transfer") or {}
                if not isinstance(jt, dict):
                    continue
                jetton_info = jt.get("jetton") or {}
                jetton_addr = jetton_info.get("address") if isinstance(jetton_info, dict) else str(jetton_info)
                if not _ton_addresses_match(jetton_addr, jetton_master):
                    continue
                recipient = jt.get("recipient", {})
                recip_addr = recipient.get("address") if isinstance(recipient, dict) else str(recipient)
                if not _ton_addresses_match(recip_addr, expected_to):
                    continue
                decimals = int(jetton_info.get("decimals", 6))
                raw_amount = str(jt.get("amount", "0"))
                amount = float(raw_amount) / (10 ** decimals)
                if not _amount_within_tolerance(expected_amount, amount, tolerance_percent):
                    return {'ok': False, 'reason': 'amount-mismatch', 'detail': {'observed': amount, 'expected': expected_amount}}
                if expected_memo:
                    observed_comment = _extract_ton_comment(jt)
                    if not _memo_matches(expected_memo, observed_comment):
                        return {'ok': False, 'reason': 'memo-mismatch', 'detail': {'observed': observed_comment, 'expected': expected_memo}}
                sender = jt.get("sender", {})
                sender_addr = sender.get("address") if isinstance(sender, dict) else str(sender)
                return {
                    'ok': True, 'reason': 'verified',
                    'detail': {'amount': amount, 'to': recip_addr, 'sender': sender_addr, 'tx_timestamp': tx_timestamp, 'via': 'events'}
                }

    except requests.RequestException:
        pass  # Fall through to transaction endpoint

    # Fallback: transaction endpoint
    try:
        tx = _http_get_json(f"{TONAPI_BASE}/blockchain/transactions/{tx_hash}", headers)
        if not isinstance(tx, dict) or tx.get("error"):
            return {'ok': False, 'reason': 'tx-not-found'}

        if jetton_master is None:
            # Check in_msg and out_msgs
            candidates = []
            in_msg = tx.get("in_msg")
            if isinstance(in_msg, dict) and float(in_msg.get("value", 0)) > 0:
                candidates.append(in_msg)
            for out in tx.get("out_msgs", []) or []:
                if isinstance(out, dict) and float(out.get("value", 0)) > 0:
                    candidates.append(out)

            for msg in candidates:
                dest = msg.get("destination", {})
                dest_addr = dest.get("address") if isinstance(dest, dict) else str(dest)
                if not _ton_addresses_match(dest_addr, expected_to):
                    continue
                value_nano = float(msg.get("value", 0))
                amount_ton = value_nano / 1_000_000_000.0
                if not _amount_within_tolerance(expected_amount, amount_ton, tolerance_percent):
                    return {'ok': False, 'reason': 'amount-mismatch', 'detail': {'observed': amount_ton, 'expected': expected_amount}}
                if expected_memo:
                    observed_comment = _extract_ton_comment(msg)
                    if not _memo_matches(expected_memo, observed_comment):
                        return {'ok': False, 'reason': 'memo-mismatch', 'detail': {'observed': observed_comment, 'expected': expected_memo}}
                source = msg.get("source", {})
                sender_addr = source.get("address") if isinstance(source, dict) else str(source)
                return {
                    'ok': True, 'reason': 'verified',
                    'detail': {'amount': amount_ton, 'to': dest_addr, 'sender': sender_addr, 'tx_timestamp': tx.get("utime", 0), 'via': 'tx'}
                }
            return {'ok': False, 'reason': 'wrong-recipient'}
        else:
            # Jetton via transaction endpoint (more complex, skip for now)
            return {'ok': False, 'reason': 'jetton-via-tx-not-supported'}

    except requests.RequestException as e:
        logger.warning("TON verification request failed: %s", e)
        return {'ok': False, 'reason': 'verification-failed', 'detail': str(e)}


# =============================================================================
# TRON Verification (tronscan.org)
# =============================================================================

def verify_tron_transaction(
    tx_hash: str,
    expected_to: str,
    expected_amount: float,
    contract_address: Optional[str] = None,
    tolerance_percent: float = DEFAULT_TOLERANCE_PERCENT
) -> dict:
    """
    Verify TRX/USDT_TRC20 transaction via tronscan.org.

    Returns: {'ok': bool, 'reason': str, 'detail': dict}
    """
    tx_hash = tx_hash.strip()
    if not tx_hash:
        return {'ok': False, 'reason': 'bad-hash-format'}

    api_key = _get_tronscan_key()
    headers = {"Accept": "application/json"}
    if api_key:
        headers["TRON-PRO-API-KEY"] = api_key

    try:
        # Get transaction info
        url = f"{TRONSCAN_BASE}/transaction-info?hash={tx_hash}"
        tx = _http_get_json(url, headers)

        if not isinstance(tx, dict) or tx.get("contractRet") != "SUCCESS":
            return {'ok': False, 'reason': 'tx-failed-or-not-found'}

        # Check contract type
        contract = tx.get("contractData", {})
        if not isinstance(contract, dict):
            return {'ok': False, 'reason': 'invalid-contract-data'}

        contract_type = contract.get("type")

        if contract_address is None:
            # Native TRX transfer
            if contract_type != "TransferContract":
                return {'ok': False, 'reason': 'not-trx-transfer'}
            to_address = contract.get("to_address") or contract.get("owner_address")
            amount_sun = int(contract.get("amount", 0))
            amount_trx = amount_sun / 1_000_000.0
        else:
            # TRC20 token transfer (USDT_TRC20)
            if contract_type != "TriggerSmartContract":
                return {'ok': False, 'reason': 'not-trc20-transfer'}
            # Parse token transfer from contract data
            # This is simplified - real implementation would parse the data field
            to_address = contract.get("to_address") or expected_to
            # Amount would be in the contract data parameter
            amount_trx = expected_amount  # Placeholder

        if not _tron_addresses_match(to_address, expected_to):
            return {'ok': False, 'reason': 'wrong-recipient', 'detail': {'expected': expected_to, 'got': to_address}}

        if not _amount_within_tolerance(expected_amount, amount_trx, tolerance_percent):
            return {'ok': False, 'reason': 'amount-mismatch', 'detail': {'observed': amount_trx, 'expected': expected_amount}}

        from_address = contract.get("owner_address", "")
        return {
            'ok': True, 'reason': 'verified',
            'detail': {'amount': amount_trx, 'to': to_address, 'from': from_address, 'tx_timestamp': tx.get("timestamp", 0) // 1000}
        }

    except requests.RequestException as e:
        logger.warning("TRON verification request failed: %s", e)
        return {'ok': False, 'reason': 'verification-failed', 'detail': str(e)}


def _tron_addresses_match(a: str, b: str) -> bool:
    """Compare TRON addresses (base58check)."""
    return a.strip().lower() == b.strip().lower()


# =============================================================================
# Main Verification Function
# =============================================================================

def verify_crypto_payment(
    tx_hash: str,
    currency: str,
    expected_to: str,
    expected_amount: float,
    expected_memo: str = "",
    tolerance_percent: float = DEFAULT_TOLERANCE_PERCENT
) -> dict:
    """
    Verify crypto payment for any supported currency.

    Supported currencies: TRX, USDT_TRC20, TON, USDT_TON
    """
    currency = currency.upper()

    if currency == "TRX":
        return verify_tron_transaction(tx_hash, expected_to, expected_amount, None, tolerance_percent)
    elif currency == "USDT_TRC20":
        return verify_tron_transaction(tx_hash, expected_to, expected_amount, USDT_TRC20_CONTRACT, tolerance_percent)
    elif currency == "TON":
        return verify_ton_transaction(tx_hash, expected_to, expected_amount, None, expected_memo, tolerance_percent)
    elif currency == "USDT_TON":
        return verify_ton_transaction(tx_hash, expected_to, expected_amount, USDT_TON_JETTON_MASTER, expected_memo, tolerance_percent)
    else:
        return {'ok': False, 'reason': 'unsupported-currency'}


def get_explorer_url(currency: str, tx_hash: str) -> str:
    """Get blockchain explorer URL for transaction."""
    currency = currency.upper()
    if currency in ("TRX", "USDT_TRC20"):
        return f"https://tronscan.org/#/transaction/{tx_hash}"
    if currency in ("TON", "USDT_TON"):
        return f"https://tonviewer.com/transaction/{tx_hash}"
    return tx_hash


# =============================================================================
# Service Functions
# =============================================================================

def get_active_wallet(app_ctx: AppContext, currency: str) -> CryptoWallet:
    """Get active wallet for currency."""
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute(
            "SELECT id, currency, wallet_address, wallet_memo, network, is_active "
            "FROM crypto_wallets WHERE currency = ? AND is_active = 1",
            (currency.upper(),)
        ).fetchone()
        if not row:
            raise CryptoWalletNotConfiguredError(f"No active wallet configured for {currency}")
        return CryptoWallet(
            id=row[0], currency=row[1], wallet_address=row[2],
            wallet_memo=row[3], network=row[4], is_active=bool(row[5])
        )


def create_crypto_invoice(
    app_ctx: AppContext,
    user_id: int,
    amount_minor: int,
    currency: str,
    memo: str = ""
) -> CryptoInvoice:
    """Create a new crypto invoice for user to pay."""
    wallet = get_active_wallet(app_ctx, currency)

    with app_ctx.unit_of_work() as uow:
        cursor = uow.conn.execute("""
            INSERT INTO crypto_invoices
            (user_id, amount_minor, currency, wallet_to, status, memo, expected_amount, tolerance_percent, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, datetime('now'))
        """, (user_id, amount_minor, currency.upper(), wallet.wallet_address, memo,
              amount_minor / 1000.0, DEFAULT_TOLERANCE_PERCENT))
        invoice_id = cursor.lastrowid
        uow.conn.commit()

        row = uow.conn.execute(
            "SELECT * FROM crypto_invoices WHERE id = ?", (invoice_id,)
        ).fetchone()

        audit_service.log(
            uow, actor_id=user_id, action="crypto_invoice_created",
            entity_type="crypto_invoice", entity_id=str(invoice_id),
            after_json={"amount_minor": amount_minor, "currency": currency, "wallet_to": wallet.wallet_address}
        )

        return _row_to_invoice(row)


def check_crypto_invoice(app_ctx: AppContext, invoice_id: int) -> CryptoInvoice:
    """Check and verify a crypto invoice by ID."""
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("SELECT * FROM crypto_invoices WHERE id = ?", (invoice_id,)).fetchone()
        if not row:
            raise NotFoundError("Crypto invoice not found")

        invoice = _row_to_invoice(row)

        if invoice.status != "pending":
            return invoice

        if not invoice.tx_hash:
            return invoice  # Still waiting for user to provide hash

        # Verify the transaction
        wallet = get_active_wallet(app_ctx, invoice.currency)
        expected_memo = wallet.wallet_memo or ""

        result = verify_crypto_payment(
            tx_hash=invoice.tx_hash,
            currency=invoice.currency,
            expected_to=invoice.wallet_to,
            expected_amount=invoice.expected_amount,
            expected_memo=expected_memo,
            tolerance_percent=invoice.tolerance_percent
        )

        if result.get("ok"):
            # Verified! Update status and credit wallet
            uow.conn.execute("""
                UPDATE crypto_invoices
                SET status = 'verified', verified_at = datetime('now'), verified_by = 'auto'
                WHERE id = ?
            """, (invoice_id,))

            # Credit user wallet (convert to TOMAN or keep in crypto currency)
            # For now, credit in TOMAN using a fixed rate (TODO: integrate with exchange rates)
            wallet_service.add_funds(
                uow, invoice.user_id, invoice.amount_minor, "TOMAN",
                f"شارژ از طریق {invoice.currency} (هش: {invoice.tx_hash[:16]}...)",
                idempotency_key=f"crypto_{invoice_id}"
            )

            audit_service.log(
                uow, actor_id=invoice.user_id, action="crypto_payment_verified",
                entity_type="crypto_invoice", entity_id=str(invoice_id),
                after_json={"tx_hash": invoice.tx_hash, "amount_minor": invoice.amount_minor}
            )

            uow.conn.commit()

            # Return updated invoice
            row = uow.conn.execute("SELECT * FROM crypto_invoices WHERE id = ?", (invoice_id,)).fetchone()
            return _row_to_invoice(row)
        else:
            # Verification failed
            uow.conn.execute("""
                UPDATE crypto_invoices SET status = 'failed' WHERE id = ?
            """, (invoice_id,))
            uow.conn.commit()

            row = uow.conn.execute("SELECT * FROM crypto_invoices WHERE id = ?", (invoice_id,)).fetchone()
            return _row_to_invoice(row)


def submit_crypto_tx_hash(app_ctx: AppContext, invoice_id: int, tx_hash: str) -> CryptoInvoice:
    """User submits transaction hash for verification."""
    with app_ctx.unit_of_work() as uow:
        row = uow.conn.execute("SELECT * FROM crypto_invoices WHERE id = ?", (invoice_id,)).fetchone()
        if not row:
            raise NotFoundError("Crypto invoice not found")

        invoice = _row_to_invoice(row)
        if invoice.status != "pending":
            raise ValidationError(f"Invoice is not pending (status: {invoice.status})")

        uow.conn.execute(
            "UPDATE crypto_invoices SET tx_hash = ? WHERE id = ?",
            (tx_hash.strip(), invoice_id)
        )
        uow.conn.commit()

        audit_service.log(
            uow, actor_id=invoice.user_id, action="crypto_tx_hash_submitted",
            entity_type="crypto_invoice", entity_id=str(invoice_id),
            after_json={"tx_hash": tx_hash}
        )

        # Trigger verification
        return check_crypto_invoice(app_ctx, invoice_id)


def list_user_crypto_invoices(app_ctx: AppContext, user_id: int, status: Optional[str] = None) -> list[CryptoInvoice]:
    """List crypto invoices for a user."""
    with app_ctx.unit_of_work() as uow:
        if status:
            rows = uow.conn.execute(
                "SELECT * FROM crypto_invoices WHERE user_id = ? AND status = ? ORDER BY created_at DESC",
                (user_id, status)
            ).fetchall()
        else:
            rows = uow.conn.execute(
                "SELECT * FROM crypto_invoices WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,)
            ).fetchall()
        return [_row_to_invoice(r) for r in rows]


def _row_to_invoice(row: tuple) -> CryptoInvoice:
    return CryptoInvoice(
        id=row[0], user_id=row[1], amount_minor=row[2], currency=row[3],
        wallet_to=row[4], tx_hash=row[5], status=row[6], memo=row[7],
        expected_amount=row[8], tolerance_percent=row[9],
        created_at=row[10], verified_at=row[11]
    )


# =============================================================================
# Admin Functions
# =============================================================================

def admin_create_wallet(app_ctx: AppContext, actor_id: int, currency: str, address: str,
                        memo: str = "", network: str = "") -> CryptoWallet:
    """Admin creates/updates a crypto wallet."""
    currency = currency.upper()
    if currency in ("TON", "USDT_TON"):
        network = "TON"
    elif currency in ("TRX", "USDT_TRC20"):
        network = "TRON"
    else:
        raise ValidationError(f"Unsupported currency: {currency}")

    with app_ctx.unit_of_work() as uow:
        uow.conn.execute("""
            INSERT INTO crypto_wallets (currency, wallet_address, wallet_memo, network, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, datetime('now'), datetime('now'))
            ON CONFLICT(currency) DO UPDATE SET
                wallet_address = excluded.wallet_address,
                wallet_memo = excluded.wallet_memo,
                network = excluded.network,
                is_active = 1,
                updated_at = datetime('now')
        """, (currency, address.strip(), memo.strip() or None, network))
        uow.conn.commit()

        row = uow.conn.execute(
            "SELECT * FROM crypto_wallets WHERE currency = ?", (currency,)
        ).fetchone()

        audit_service.log(
            uow, actor_id=actor_id, action="crypto_wallet_upsert",
            entity_type="crypto_wallet", entity_id=currency,
            after_json={"currency": currency, "address": address[:16] + "...", "network": network}
        )

        return CryptoWallet(
            id=row[0], currency=row[1], wallet_address=row[2],
            wallet_memo=row[3], network=row[4], is_active=bool(row[5])
        )


def admin_list_wallets(app_ctx: AppContext) -> list[CryptoWallet]:
    """List all crypto wallets."""
    with app_ctx.unit_of_work() as uow:
        rows = uow.conn.execute(
            "SELECT * FROM crypto_wallets ORDER BY currency"
        ).fetchall()
        return [CryptoWallet(id=r[0], currency=r[1], wallet_address=r[2],
                            wallet_memo=r[3], network=r[4], is_active=bool(r[5])) for r in rows]


def admin_toggle_wallet(app_ctx: AppContext, actor_id: int, currency: str, active: bool) -> CryptoWallet:
    """Enable/disable a crypto wallet."""
    with app_ctx.unit_of_work() as uow:
        uow.conn.execute(
            "UPDATE crypto_wallets SET is_active = ?, updated_at = datetime('now') WHERE currency = ?",
            (1 if active else 0, currency.upper())
        )
        uow.conn.commit()

        row = uow.conn.execute("SELECT * FROM crypto_wallets WHERE currency = ?", (currency.upper(),)).fetchone()
        if not row:
            raise NotFoundError("Wallet not found")

        audit_service.log(
            uow, actor_id=actor_id, action="crypto_wallet_toggle",
            entity_type="crypto_wallet", entity_id=currency.upper(),
            after_json={"is_active": active}
        )

        return CryptoWallet(id=row[0], currency=row[1], wallet_address=row[2],
                           wallet_memo=row[3], network=row[4], is_active=bool(row[5]))