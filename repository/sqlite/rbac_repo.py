from __future__ import annotations
import sqlite3
from typing import Sequence


class SqliteRbacRepository:
    """
    طبق دستور صریح Owner: فعلاً فقط نقش OWNER فعال است. جدول‌های Role/Permission
    از روز اول در schema هستند (RBAC-ready) اما این Repository عمداً فقط دو
    عملیات را expose می‌کند که V1 هم داشت: کیست OWNER، و مدیریت لیست تخت ادمین‌ها
    (برای حفظ رفتار فعلی ربات بدون افزودن قابلیت جدید خارج از Phase 1).
    """

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def ensure_owner_role(self, owner_user_id: int) -> None:
        self._c.execute("INSERT OR IGNORE INTO roles (name) VALUES ('OWNER')")
        role_id = self._c.execute("SELECT id FROM roles WHERE name='OWNER'").fetchone()[0]
        self._c.execute(
            "INSERT INTO users (user_id, created_at) VALUES (?, datetime('now')) "
            "ON CONFLICT(user_id) DO NOTHING",
            (owner_user_id,),
        )
        self._c.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (owner_user_id, role_id),
        )

    def is_owner(self, user_id: int) -> bool:
        row = self._c.execute(
            "SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
            "WHERE ur.user_id=? AND r.name='OWNER'",
            (user_id,),
        ).fetchone()
        return row is not None

    def list_admins(self) -> Sequence[int]:
        # معادل جدول تخت admins قدیمی: هر کسی با نقش OWNER یا ADMIN
        rows = self._c.execute(
            "SELECT DISTINCT ur.user_id FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
            "WHERE r.name IN ('OWNER', 'ADMIN')"
        ).fetchall()
        return [r[0] for r in rows]

    def grant_admin(self, user_id: int) -> None:
        self._c.execute("INSERT OR IGNORE INTO roles (name) VALUES ('ADMIN')")
        role_id = self._c.execute("SELECT id FROM roles WHERE name='ADMIN'").fetchone()[0]
        self._c.execute(
            "INSERT INTO users (user_id, created_at) VALUES (?, datetime('now')) "
            "ON CONFLICT(user_id) DO NOTHING",
            (user_id,),
        )
        self._c.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (user_id, role_id),
        )

    def revoke_admin(self, user_id: int) -> None:
        self._c.execute(
            "DELETE FROM user_roles WHERE user_id=? AND role_id IN "
            "(SELECT id FROM roles WHERE name='ADMIN')",
            (user_id,),
        )
        self._c.execute("DELETE FROM user_permissions WHERE user_id=?", (user_id,))

    def is_admin(self, user_id: int) -> bool:
        row = self._c.execute(
            "SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
            "WHERE ur.user_id=? AND r.name IN ('OWNER', 'ADMIN')",
            (user_id,),
        ).fetchone()
        return row is not None

    def has_permission(self, user_id: int, permission_name: str) -> bool:
        # (1) Permissionهای سطح-نقش (فقط OWNER دارد)  (2) grant per-user فقط برای
        # کسی که واقعاً نقش ADMIN دارد (revoke_admin هر دو را پاک می‌کند).
        row = self._c.execute(
            "SELECT 1 FROM user_roles ur "
            "JOIN role_permissions rp ON rp.role_id = ur.role_id "
            "JOIN permissions p ON p.id = rp.permission_id "
            "WHERE ur.user_id=? AND p.name=? "
            "UNION "
            "SELECT 1 FROM user_permissions up "
            "JOIN permissions p ON p.id = up.permission_id "
            "JOIN user_roles ur ON ur.user_id = up.user_id "
            "JOIN roles r ON r.id = ur.role_id AND r.name='ADMIN' "
            "WHERE up.user_id=? AND p.name=?",
            (user_id, permission_name, user_id, permission_name),
        ).fetchone()
        return row is not None

    def list_permissions_for_role(self, role_name: str) -> Sequence[str]:
        rows = self._c.execute(
            "SELECT p.name FROM role_permissions rp "
            "JOIN permissions p ON p.id = rp.permission_id "
            "JOIN roles r ON r.id = rp.role_id "
            "WHERE r.name=? ORDER BY p.name",
            (role_name,),
        ).fetchall()
        return [r[0] for r in rows]

    def list_permissions_for_user(self, user_id: int) -> Sequence[str]:
        rows = self._c.execute(
            "SELECT p.name FROM user_roles ur "
            "JOIN role_permissions rp ON rp.role_id = ur.role_id "
            "JOIN permissions p ON p.id = rp.permission_id WHERE ur.user_id=? "
            "UNION "
            "SELECT p.name FROM user_permissions up "
            "JOIN permissions p ON p.id = up.permission_id "
            "JOIN user_roles ur ON ur.user_id = up.user_id "
            "JOIN roles r ON r.id = ur.role_id AND r.name='ADMIN' WHERE up.user_id=? "
            "ORDER BY 1",
            (user_id, user_id),
        ).fetchall()
        return [r[0] for r in rows]

    def list_user_grants(self, user_id: int) -> Sequence[str]:
        rows = self._c.execute(
            "SELECT p.name FROM user_permissions up JOIN permissions p ON p.id=up.permission_id "
            "WHERE up.user_id=? ORDER BY p.name", (user_id,)).fetchall()
        return [r[0] for r in rows]

    def set_user_grants(self, user_id: int, permissions: Sequence[str], granted_by: int) -> None:
        self._c.execute("DELETE FROM user_permissions WHERE user_id=?", (user_id,))
        for name in permissions:
            self._c.execute(
                "INSERT INTO user_permissions (user_id, permission_id, granted_by, granted_at) "
                "SELECT ?, id, ?, datetime('now') FROM permissions WHERE name=?",
                (user_id, granted_by, name),
            )

    def catalog_names(self) -> Sequence[str]:
        return [r[0] for r in self._c.execute("SELECT name FROM permissions ORDER BY name").fetchall()]
