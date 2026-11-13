"""Who counts as ticket staff: admins, the panel's roles, and everyone in LOJI's staff hierarchy."""

from core.mail.config import MANAGE_ANY_TASK, HasAny, InDepartment
from core.staff.feedback import IsStaff


def IsAdmin(member) -> bool:
    Perms = getattr(member, "guild_permissions", None)
    return bool(Perms and (Perms.administrator or Perms.manage_guild))


def IsTicketStaff(member, panel_roles, mail_config: dict) -> bool:
    """
    Admin, a role from the panel's permissions, or LOJI's hierarchy (/config → Mando Central):
    staff role, roles with a profile, the high offices and the departments' roles.
    """
    if IsAdmin(member):
        return True
    Roles = {R.id for R in getattr(member, "roles", [])}
    if Roles & set(panel_roles or []):
        return True
    return IsStaff(member, mail_config) or any(InDepartment(member, D) for D in mail_config.get("departments", []))


def CanForceUnclaim(member, mail_config: dict) -> bool:
    """Admins and the high offices (Tenno, Consejo Supremo, Director de Moderación)."""
    return IsAdmin(member) or HasAny(member, MANAGE_ANY_TASK, mail_config)
