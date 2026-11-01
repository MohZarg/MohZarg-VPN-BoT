"""
GhYiAb V2 — SQLite Unit of Work
==================================

پیاده‌سازی Protocol `UnitOfWork` از `repository/interface.py` روی یک اتصال
SQLite واحد با `BEGIN IMMEDIATE` — همان الگوی اتمیکی که در Audit به‌عنوان KEEP
مشخص شد، اما این‌بار پشت یک Interface مستقل از دیتابیس.

استفاده:
    with SqliteUnitOfWork(db_path) as uow:
        bal = uow.wallet.adjust(user_id, "TOMAN", 1000)
        uow.audit.append(actor_id=OWNER_ID, action="wallet.adjust", ...)
    # با خروج بدون Exception → commit خودکار؛ با Exception → rollback خودکار
"""

from __future__ import annotations

import sqlite3

from repository.sqlite.connection import get_conn
from repository.sqlite.users_repo import SqliteUsersRepository
from repository.sqlite.wallet_repo import SqliteWalletRepository
from repository.sqlite.inventory_repo import SqliteInventoryRepository
from repository.sqlite.orders_repo import SqliteOrdersRepository
from repository.sqlite.pending_requests_repo import SqlitePendingRequestsRepository
from repository.sqlite.audit_repo import SqliteAuditRepository
from repository.sqlite.rbac_repo import SqliteRbacRepository
from repository.sqlite.products_repo import SqliteProductsRepository
from repository.sqlite.categories_repo import SqliteCategoriesRepository
from repository.sqlite.product_variants_repo import SqliteProductVariantsRepository
from repository.sqlite.providers_repo import SqliteProvidersRepository
from repository.sqlite.settings_tx_repo import SqliteSettingsTxRepository
from repository.sqlite.commerce_repos import (
    SqliteCouponsRepository, SqliteResellersRepository, SqliteReferralsRepository, SqliteDiceRepository,
)
from repository.sqlite.ops_repos import (
    SqliteTicketsRepository, SqliteBroadcastsRepository, SqliteConfirmationsRepository,
    SqliteJobsRepository, SqliteProvisioningRepository, SqliteReportsRepository, SqliteRenewalsRepository,
)


class SqliteUnitOfWork:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn_ctx = None
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> "SqliteUnitOfWork":
        self._conn_ctx = get_conn(self._db_path)
        self._conn = self._conn_ctx.__enter__()
        self._conn.execute("BEGIN IMMEDIATE")

        self.users = SqliteUsersRepository(self._conn)
        self.wallet = SqliteWalletRepository(self._conn)
        self.inventory = SqliteInventoryRepository(self._conn)
        self.orders = SqliteOrdersRepository(self._conn)
        self.pending_requests = SqlitePendingRequestsRepository(self._conn)
        self.audit = SqliteAuditRepository(self._conn)
        self.rbac = SqliteRbacRepository(self._conn)
        self.products = SqliteProductsRepository(self._conn)
        self.categories = SqliteCategoriesRepository(self._conn)
        self.product_variants = SqliteProductVariantsRepository(self._conn)
        self.providers = SqliteProvidersRepository(self._conn)
        self.settings = SqliteSettingsTxRepository(self._conn)
        self.coupons = SqliteCouponsRepository(self._conn)
        self.resellers = SqliteResellersRepository(self._conn)
        self.referrals = SqliteReferralsRepository(self._conn)
        self.dice = SqliteDiceRepository(self._conn)
        self.tickets = SqliteTicketsRepository(self._conn)
        self.broadcasts = SqliteBroadcastsRepository(self._conn)
        self.confirmations = SqliteConfirmationsRepository(self._conn)
        self.jobs = SqliteJobsRepository(self._conn)
        self.provisioning = SqliteProvisioningRepository(self._conn)
        self.reports = SqliteReportsRepository(self._conn)
        self.renewals = SqliteRenewalsRepository(self._conn)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        assert self._conn is not None
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._conn_ctx.__exit__(exc_type, exc, tb)
            self._conn = None
