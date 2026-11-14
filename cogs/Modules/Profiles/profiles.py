"""/perfil: automatic staff profiles, the staff panel (by department) and each member's own text."""

import logging
import time
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from core.mail.config import DECIDE_SUGGESTIONS, CanConfigure, HasAny, Mail
from core.staff.profiles import ADMIN_GROUP, DESCRIPTION_MAX, SPECIALTY_MAX, Aware, Duration, Groups, Profiles, Rank

logger = logging.getLogger(__name__)
LOJI_RED = discord.Color.from_rgb(150, 12, 18)
PANEL_TIMEOUT = 600
MAX_LISTED = 25
TICKETS = "Tickets"  # Birb's ticket documents
TICKET_CACHE_SECONDS = 120  # so not every message in the server hits the database
_store: Profiles | None = None


def Store() -> Profiles:
    global _store
    if _store is None:
        from core.db import db

        _store = Profiles(db)
    return _store


def StaffRoles(guild: discord.Guild, config: dict) -> set[int]:
    """The roles the admins chose for staff profiles (only those that still exist)."""
    return {R for R in config.get("profile_roles") or [] if guild.get_role(R)}


async def SyncPlan(guild: discord.Guild, staff: set[int]) -> dict:
    """What a sync would do, without doing it: new profiles, rank changes and archived ones."""
    Profiles_ = {P["staff"]: P for P in await Store().col.find({"guild_id": guild.id}).to_list(length=None)}
    Plan = {"new": [], "changed": [], "archived": []}
    Seen = set()
    for Member in guild.members:
        if Member.bot:
            continue
        R = Rank(Member, staff)
        Old = Profiles_.get(Member.id)
        if R is None:
            continue
        Seen.add(Member.id)
        if not Old or not Old.get("active"):
            Plan["new"].append((Member, R))
        elif Old.get("rank") != R.id:
            Plan["changed"].append((Member, guild.get_role(Old.get("rank") or 0), R))
    Plan["archived"] = [P["staff"] for P in Profiles_.values() if P.get("active") and P["staff"] not in Seen]
    return Plan


def PlanEmbed(guild: discord.Guild, staff: set[int], plan: dict) -> discord.Embed:
    Order = sorted((guild.get_role(R) for R in staff), key=lambda R: -R.position)
    embed = discord.Embed(title="🔄 Revisa antes de sincronizar", color=discord.Color.orange())
    embed.description = (
        f"**{len(plan['changed'])}** cambian de rango · **{len(plan['new'])}** perfiles nuevos · **{len(plan['archived'])}** se archivan.\n"
        "-# El rango es el rol **más alto en la lista de roles de Discord** de entre los elegidos. Si alguien sale con un rango que no es, "
        "revisa que su rol real esté elegido en `/config` → Mando Central → Roles con perfil y que esté **por encima** en Discord."
    )
    embed.add_field(name="Orden de rangos (de mayor a menor)", value=" > ".join(R.mention for R in Order)[:1024] or "—", inline=False)
    if plan["changed"]:
        Lines = [f"{M.mention}: {Old.mention if Old else '¿?'} → **{New.mention}**" for M, Old, New in plan["changed"][:20]]
        if len(plan["changed"]) > 20:
            Lines.append(f"…y {len(plan['changed']) - 20} más")
        embed.add_field(name="Cambios de rango", value="\n".join(Lines)[:1024], inline=False)
    if plan["archived"]:
        embed.add_field(name="Se archivan (ya no tienen ningún rol elegido)", value=" ".join(f"<@{U}>" for U in plan["archived"][:30])[:1024], inline=False)
    embed.set_footer(text="Si algo no cuadra, cancela y corrige los roles. Si confirmas por error, /perfil reparar lo deshace.")
    return embed


async def ApplySync(guild: discord.Guild, staff: set[int]) -> tuple[int, int]:
    Synced = Archived = 0
    Seen = set()
    for Member in guild.members:
        if Member.bot:
            continue
        if await Store().Sync(guild.id, Member, Rank(Member, staff)):
            Synced += 1
            Seen.add(Member.id)
    for P in await Store().Active(guild.id):
        if P["staff"] not in Seen:
            await Store().col.update_one({"_id": P["_id"]}, {"$set": {"active": False}})
            Archived += 1
    return Synced, Archived


class ConfirmSync(discord.ui.View):
    def __init__(self, author, staff: set[int]):
        super().__init__(timeout=300)
        self.author, self.staff = author, staff

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author.id

    @discord.ui.button(label="Confirmar", emoji="✅", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(content="⏳ Sincronizando...", embed=None, view=None)
        Synced, Archived = await ApplySync(interaction.guild, self.staff)
        await interaction.edit_original_response(
            content=f"✅ **{Synced}** perfiles al día" + (f" · {Archived} archivados" if Archived else "") + "."
        )

    @discord.ui.button(label="Cancelar", emoji="✖️", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(content="Cancelado: no se cambió nada.", embed=None, view=None)


async def RoleAddedDates(guild: discord.Guild, days: int = 45) -> dict:
    """(user, role) -> when the role was last given, from the audit log (Discord keeps ~45 days)."""
    Out = {}
    try:
        After = datetime.now(timezone.utc) - timedelta(days=days)
        async for Entry in guild.audit_logs(limit=10_000, action=discord.AuditLogAction.member_role_update, after=After, oldest_first=False):
            for R in getattr(Entry.after, "roles", None) or []:
                Out.setdefault((getattr(Entry.target, "id", 0), R.id), Entry.created_at)
    except discord.HTTPException as e:
        logger.warning(f"[Profiles] Can't read the audit log: {e}")
    return Out


async def RepairDates(guild: discord.Guild, hours: int) -> tuple[list, list]:
    """
    Profiles whose date was reset in the last `hours`: their real date for the CURRENT rank, from
    (1) the profile's own history, (2) Birb promotions, (3) the audit log. Returns (fixed, unknown).
    """
    from core.staff.profiles import RecentSince

    Now_ = datetime.now(timezone.utc)
    Cutoff = Now_ - timedelta(hours=hours)
    Recent = [P for P in await Store().Active(guild.id) if P.get("since") and Aware(P["since"]) >= Cutoff and P.get("rank")]
    if not Recent:
        return [], []
    Audit = await RoleAddedDates(guild)
    Fixed, Unknown = [], []
    for P in Recent:
        Date, Source = RecentSince(P.get("history") or [], P["rank"], Now_ + timedelta(days=1)), "historial"
        if not Date:
            Promo = await Store().db["promotions"].find({"guild_id": guild.id, "staff": P["staff"], "new": P["rank"]}).sort("timestamp", -1).limit(1).to_list(length=1)
            if Promo and isinstance(Promo[0].get("timestamp"), datetime):
                Date, Source = Aware(Promo[0]["timestamp"]), "ascenso registrado"
        if not Date and (P["staff"], P["rank"]) in Audit:
            Date, Source = Audit[(P["staff"], P["rank"])], "registro de auditoría"
        if Date and Date < Aware(P["since"]) - timedelta(minutes=1):
            await Store().SetSince(guild.id, P["staff"], Date)
            Fixed.append((P["staff"], Date, Source))
        elif not Date:
            Unknown.append(P["staff"])
    return Fixed, Unknown


def CanManage(member, config: dict) -> bool:
    return CanConfigure(member, config) or HasAny(member, DECIDE_SUGGESTIONS, config)


def Stars(rating: float | None, count: int) -> str:
    if rating is None:
        return "Sin valoraciones todavía"
    Full = round(rating / 2)
    return f"{'★' * Full}{'☆' * (5 - Full)} **{rating:.1f}/10**".replace(".", ",") + f" · {count} valoraci{'ón' if count == 1 else 'ones'}"


async def AddMedals(embed: discord.Embed, member: discord.Member, config: dict, compact: bool):
    """🏅 Medallas: icon + name in the profile, just the icons in the ticket card."""
    from core.staff.medals import Manager, MedalRoles

    Mine = MedalRoles(member, config)
    Total = len([R for R in config.get("medal_roles") or [] if member.guild.get_role(R)])
    if not Total or (compact and not Mine):
        return
    if not Mine:
        return embed.add_field(name=f"🏅 Medallas (0/{Total})", value="*Todavía ninguna.*", inline=False)
    M = Manager()
    Text = await M.Line(Mine, names=not compact) if M else " · ".join(R.name for R in Mine)
    embed.add_field(name=f"🏅 Medallas ({len(Mine)}/{Total})", value=Text[:1024], inline=False)


async def ProfileEmbed(member: discord.Member, profile: dict, config: dict, compact: bool = False) -> discord.Embed:
    """The profile card. `compact` is the short version shown in tickets."""
    Rating, Count = await Store().Rating(member.guild.id, member.id)
    Role = member.guild.get_role(profile.get("rank") or 0)
    Color = Role.color if Role and Role.color.value else LOJI_RED
    embed = discord.Embed(color=Color)
    embed.set_author(name=f"{member.display_name} · Staff de {member.guild.name}", icon_url=member.display_avatar.url)
    embed.set_thumbnail(url=member.display_avatar.url)
    Since = profile.get("since")
    Date = f" (desde {Since:%d/%m/%Y})" if Since and not compact else ""
    embed.add_field(name="🏷️ Cargo", value=Role.mention if Role else "—", inline=True)
    embed.add_field(name="⏳ En el cargo", value=Duration(Since) + Date, inline=True)
    Places = Groups(member, config)
    if Places:
        Seen, Lines = set(), []
        for Group, Dep in Places:
            if Dep not in Seen:
                Seen.add(Dep)
                Lines.append(f"{Dep}" + (f" *({Group})*" if Group not in (Dep, ADMIN_GROUP) else ""))
        embed.add_field(name="🏢 Departamento", value=" · ".join(Lines)[:1024], inline=False)
    embed.add_field(name="🎯 Especialización", value=profile.get("specialty") or "*Sin especificar*", inline=False)
    if not compact or profile.get("description"):
        embed.add_field(name="📝 Descripción", value=(profile.get("description") or "*Todavía no escribió nada. Usa `/perfil editar`.*")[:1024], inline=False)
    embed.add_field(name="⭐ Calificación", value=Stars(Rating, Count), inline=False)
    await AddMedals(embed, member, config, compact)
    embed.set_footer(text="Mando Central de LOJI · perfil de staff")
    return embed


class EditModal(discord.ui.Modal, title="Tu perfil de staff"):
    def __init__(self, profile: dict):
        super().__init__()
        self.description = discord.ui.TextInput(
            label="Descripción", style=discord.TextStyle.paragraph, max_length=DESCRIPTION_MAX, required=False,
            default=profile.get("description") or None, placeholder="Quién eres, qué haces en el staff...",
        )
        self.specialty = discord.ui.TextInput(
            label="Especialización", max_length=SPECIALTY_MAX, required=False,
            default=profile.get("specialty") or None, placeholder="Ej. Reportes, eventos, soporte...",
        )
        self.add_item(self.description)
        self.add_item(self.specialty)

    async def on_submit(self, interaction: discord.Interaction):
        await Store().SetText(interaction.guild.id, interaction.user.id, self.description.value, self.specialty.value)
        Profile = await Store().Get(interaction.guild.id, interaction.user.id)
        Config = await Mail().Get(interaction.guild.id)
        await interaction.response.send_message("✅ Perfil actualizado.", embed=await ProfileEmbed(interaction.user, Profile, Config), ephemeral=True)


# ---------------- staff panel ----------------


def Categories(members: list[discord.Member], config: dict) -> dict[str, tuple[str, str, list[discord.Member]]]:
    """key -> (emoji, label, members): the administrative department, each group (sub-units) and each department."""
    Out: dict[str, tuple[str, str, list]] = {"all": ("👥", "Todo el staff", list(members))}
    Out["admin"] = ("👑", ADMIN_GROUP, [M for M in members if any(G == ADMIN_GROUP for G, _ in Groups(M, config))])
    for Group in dict.fromkeys(D["group"] for D in config["departments"] if D.get("group")):
        Out[f"group:{Group}"] = ("🔱", f"{Group} (sub-unidades)", [M for M in members if any(G == Group for G, _ in Groups(M, config))])
    for D in config["departments"]:
        Out[f"dep:{D['id']}"] = ("🏢", D["name"], [M for M in members if any(Dep == D["name"] for _, Dep in Groups(M, config))])
    return Out


def CategoryEmbed(guild: discord.Guild, label: str, members: list[discord.Member], ranks: dict[int, int]) -> discord.Embed:
    Sorted = sorted(members, key=lambda M: -(guild.get_role(ranks.get(M.id, 0)).position if guild.get_role(ranks.get(M.id, 0)) else 0))
    Lines = []
    for M in Sorted[:MAX_LISTED]:
        Role = guild.get_role(ranks.get(M.id, 0))
        Lines.append(f"**{M.display_name}** · {Role.mention if Role else '—'}")
    embed = discord.Embed(title=f"👥 Panel de staff · {label}", description="\n".join(Lines) or "Nadie por aquí.", color=LOJI_RED)
    embed.set_footer(text=f"{len(members)} miembro{'s' if len(members) != 1 else ''} · elige a alguien abajo para ver su perfil")
    return embed


class StaffPanel(discord.ui.View):
    def __init__(self, author, guild: discord.Guild, config: dict, members: list[discord.Member], ranks: dict[int, int], key: str = "all"):
        super().__init__(timeout=PANEL_TIMEOUT)
        self.author, self.guild, self.config, self.members, self.ranks = author, guild, config, members, ranks
        self.categories = Categories(members, config)
        Pick = discord.ui.Select(
            placeholder="Buscar por departamento",
            options=[discord.SelectOption(label=f"{L} ({len(Ms)})"[:100], value=K, emoji=E, default=K == key) for K, (E, L, Ms) in self.categories.items()][:25],
            row=0,
        )
        Pick.callback = self.PickCategory
        self.add_item(Pick)
        if config.get("medal_roles"):
            Medals = discord.ui.Button(label="Medallas", emoji="🏅", style=discord.ButtonStyle.grey, row=2)
            Medals.callback = self.ShowMedals
            self.add_item(Medals)
        Shown = sorted(self.categories[key][2], key=lambda M: M.display_name.lower())[:25]
        if Shown:
            Who = discord.ui.Select(placeholder="Ver el perfil de...", options=[discord.SelectOption(label=M.display_name[:100], value=str(M.id)) for M in Shown], row=1)
            Who.callback = self.PickMember
            self.add_item(Who)
        self.key = key

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author.id

    def Embed(self) -> discord.Embed:
        _, Label, Members = self.categories[self.key]
        return CategoryEmbed(self.guild, Label, Members, self.ranks)

    async def PickCategory(self, interaction: discord.Interaction):
        View = StaffPanel(self.author, self.guild, self.config, self.members, self.ranks, interaction.data["values"][0])
        await interaction.response.edit_message(embed=View.Embed(), view=View)

    async def ShowMedals(self, interaction: discord.Interaction):
        from core.staff.medals import CatalogEmbed

        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(embed=await CatalogEmbed(self.guild, self.config, interaction.user), ephemeral=True)

    async def PickMember(self, interaction: discord.Interaction):
        Member = self.guild.get_member(int(interaction.data["values"][0]))
        Profile = await Store().Get(self.guild.id, Member.id) if Member else None
        if not Member or not Profile:
            return await interaction.response.send_message("Ese perfil ya no existe.", ephemeral=True)
        await interaction.response.send_message(embed=await ProfileEmbed(Member, Profile, self.config), ephemeral=True)


# ---------------- cog ----------------


class MedalsButton(discord.ui.DynamicItem[discord.ui.Button], template=r"medals:(?P<user>\d+)"):
    """Under the "Te atiende" card in tickets: shows that staff member's medals and how they're earned."""

    def __init__(self, user_id: int):
        super().__init__(discord.ui.Button(label="Detalle condecoraciones", emoji="🏅", style=discord.ButtonStyle.grey, custom_id=f"medals:{user_id}"))
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
        return cls(int(match["user"]))

    async def callback(self, interaction: discord.Interaction):
        from core.staff.medals import MemberMedalsEmbed

        Member = interaction.guild.get_member(self.user_id)
        if not Member:
            return await interaction.response.send_message("Esa persona ya no está en el servidor.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        Config = await Mail().Get(interaction.guild.id)
        await interaction.followup.send(embed=await MemberMedalsEmbed(Member, Config), ephemeral=True)


class StaffProfiles(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.tickets: dict[int, tuple[float, dict | None]] = {}
        from core.staff.medals import Setup

        Setup(client)

    async def cog_load(self):
        self.client.add_dynamic_items(MedalsButton)  # the button keeps working after restarts

    perfil = app_commands.Group(name="perfil", description="Perfiles del staff de LOJI", guild_only=True)

    async def Ensure(self, member: discord.Member, config: dict) -> dict | None:
        """The member's profile, created or updated from their roles right now."""
        return await Store().Sync(member.guild.id, member, Rank(member, StaffRoles(member.guild, config)))

    @perfil.command(name="ver", description="Mira tu perfil de staff (o el de alguien)")
    @app_commands.describe(usuario="De quién (por defecto, tú)")
    async def ver(self, interaction: discord.Interaction, usuario: discord.Member | None = None):
        Config = await Mail().Get(interaction.guild.id)
        if not StaffRoles(interaction.guild, Config):
            return await interaction.response.send_message("❌ Falta configurar el **roles de staff para perfiles** en `/config` → 📮 Mando Central.", ephemeral=True)
        Member = usuario or interaction.user
        Profile = await self.Ensure(Member, Config)
        if not Profile:
            return await interaction.response.send_message(f"**{Member.display_name}** no es parte del staff.", ephemeral=True)
        await interaction.response.send_message(embed=await ProfileEmbed(Member, Profile, Config), allowed_mentions=discord.AllowedMentions.none())

    @perfil.command(name="editar", description="Escribe tu descripción y tu especialización")
    async def editar(self, interaction: discord.Interaction):
        Config = await Mail().Get(interaction.guild.id)
        Profile = await self.Ensure(interaction.user, Config) if StaffRoles(interaction.guild, Config) else None
        if not Profile:
            return await interaction.response.send_message("❌ Solo el staff tiene perfil.", ephemeral=True)
        await interaction.response.send_modal(EditModal(Profile))

    @perfil.command(name="panel", description="Panel del staff: busca por departamento y mira sus perfiles")
    async def panel(self, interaction: discord.Interaction):
        Config = await Mail().Get(interaction.guild.id)
        Staff = StaffRoles(interaction.guild, Config)
        if not Staff:
            return await interaction.response.send_message("❌ Falta configurar el **roles de staff para perfiles** en `/config` → 📮 Mando Central.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild.chunked:
            await interaction.guild.chunk()
        Members, Ranks = [], {}
        for P in await Store().Active(interaction.guild.id):
            M = interaction.guild.get_member(P["staff"])
            if M and Rank(M, Staff):
                Members.append(M)
                Ranks[M.id] = P.get("rank")
        View = StaffPanel(interaction.user, interaction.guild, Config, Members, Ranks)
        await interaction.followup.send(embed=View.Embed(), view=View, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @perfil.command(name="medallas", description="Catálogo de medallas: cuáles hay, cómo se consiguen y quién las tiene")
    async def medallas(self, interaction: discord.Interaction):
        from core.staff.medals import CatalogEmbed

        await interaction.response.defer(ephemeral=True, thinking=True)
        if not interaction.guild.chunked:
            await interaction.guild.chunk()  # so the counts are right
        Config = await Mail().Get(interaction.guild.id)
        await interaction.followup.send(embed=await CatalogEmbed(interaction.guild, Config, interaction.user), ephemeral=True)

    @perfil.command(name="sincronizar", description="Crea o actualiza los perfiles de todo el staff según sus roles")
    async def sincronizar(self, interaction: discord.Interaction):
        Config = await Mail().Get(interaction.guild.id)
        if not CanManage(interaction.user, Config):
            return await interaction.response.send_message("❌ Solo el Tenno, el Consejo Supremo o un administrador.", ephemeral=True)
        Staff = StaffRoles(interaction.guild, Config)
        if not Staff:
            return await interaction.response.send_message("❌ Falta configurar el **roles de staff para perfiles** en `/config` → 📮 Mando Central.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild.chunked:
            await interaction.guild.chunk()  # the full member list, so nobody is missed
        Plan = await SyncPlan(interaction.guild, Staff)
        if not Plan["changed"] and not Plan["archived"]:
            Synced, Archived = await ApplySync(interaction.guild, Staff)
            return await interaction.followup.send(f"✅ **{Synced}** perfiles al día. Nadie cambia de rango.", ephemeral=True)
        # Rank changes reset "since": show them first so a wrong role setup can't go through unseen.
        await interaction.followup.send(embed=PlanEmbed(interaction.guild, Staff, Plan), view=ConfirmSync(interaction.user, Staff), ephemeral=True)

    @perfil.command(name="reparar", description="Recupera la fecha de cargo de perfiles que se reiniciaron por error")
    @app_commands.describe(horas="Arregla los perfiles cuya fecha se reinició en estas últimas horas (por defecto 72)")
    async def reparar(self, interaction: discord.Interaction, horas: app_commands.Range[int, 1, 2160] = 72):
        Config = await Mail().Get(interaction.guild.id)
        if not CanManage(interaction.user, Config):
            return await interaction.response.send_message("❌ Solo el Tenno, el Consejo Supremo o un administrador.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        Fixed, Unknown = await RepairDates(interaction.guild, horas)
        Lines = [f"✅ **{len(Fixed)}** fechas recuperadas."]
        Lines += [f"> <@{U}> → {D:%d/%m/%Y} ({Source})" for U, D, Source in Fixed[:15]]
        if len(Fixed) > 15:
            Lines.append(f"> …y {len(Fixed) - 15} más")
        if Unknown:
            Lines.append(f"\n⚠️ **{len(Unknown)}** sin datos para recuperar (ponlas con `/perfil fecha`):")
            Lines.append("> " + " ".join(f"<@{U}>" for U in Unknown[:40]))
        await interaction.followup.send("\n".join(Lines)[:2000], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @perfil.command(name="fecha", description="Corrige desde cuándo alguien tiene su cargo")
    @app_commands.describe(usuario="De quién", fecha="Fecha en formato DD/MM/AAAA")
    async def fecha(self, interaction: discord.Interaction, usuario: discord.Member, fecha: str):
        Config = await Mail().Get(interaction.guild.id)
        if not CanManage(interaction.user, Config):
            return await interaction.response.send_message("❌ Solo el Tenno, el Consejo Supremo o un administrador.", ephemeral=True)
        try:
            Since = datetime.strptime(fecha.strip(), "%d/%m/%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            return await interaction.response.send_message("❌ Usa el formato DD/MM/AAAA, por ejemplo `15/08/2026`.", ephemeral=True)
        if Since > datetime.now(timezone.utc):
            return await interaction.response.send_message("❌ Esa fecha está en el futuro.", ephemeral=True)
        await self.Ensure(usuario, Config)
        if not await Store().SetSince(interaction.guild.id, usuario.id, Since):
            return await interaction.response.send_message(f"**{usuario.display_name}** no tiene perfil de staff.", ephemeral=True)
        await interaction.response.send_message(f"✅ **{usuario.display_name}** tiene su cargo desde el **{Since:%d/%m/%Y}** ({Duration(Since)}).", ephemeral=True)

    # ---- tickets: "Te atiende" card ----

    async def TicketOf(self, channel_id: int) -> dict | None:
        Cached = self.tickets.get(channel_id)
        if Cached and Cached[0] > time.monotonic():
            return Cached[1]
        Doc = await Store().db[TICKETS].find_one({"ChannelID": channel_id, "closed": None})
        self.tickets[channel_id] = (time.monotonic() + TICKET_CACHE_SECONDS, Doc)
        return Doc

    async def ShowCard(self, channel, member: discord.Member, ticket: dict, config: dict):
        """Posts the staff member's profile in the ticket, once per person and ticket."""
        Profile = await self.Ensure(member, config)
        if not Profile:
            return
        Marked = await Store().db[TICKETS].update_one(
            {"_id": ticket["_id"], "profiles_shown": {"$ne": member.id}}, {"$addToSet": {"profiles_shown": member.id}}
        )
        if not Marked.modified_count:
            return
        self.tickets.pop(channel.id, None)
        embed = await ProfileEmbed(member, Profile, config, compact=True)
        embed.title = f"🎫 Te atiende {member.display_name}"
        try:
            from core.staff.medals import MedalRoles

            View = None
            if MedalRoles(member, config):
                View = discord.ui.View(timeout=None)
                View.add_item(MedalsButton(member.id))
            await channel.send(embed=embed, view=View, allowed_mentions=discord.AllowedMentions.none()) if View else await channel.send(
                embed=embed, allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.HTTPException as e:
            logger.warning(f"[Profiles] Couldn't post the profile in ticket {channel.id}: {e}")

    @commands.Cog.listener()
    async def on_ticket_claimed(self, channel, member: discord.Member):
        Ticket = await Store().db[TICKETS].find_one({"ChannelID": channel.id})
        if Ticket:
            await self.ShowCard(channel, member, Ticket, await Mail().Get(channel.guild.id))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not hasattr(message.author, "roles"):
            return
        Config = await Mail().Get(message.guild.id)
        if not Rank(message.author, StaffRoles(message.guild, Config)):
            return  # only staff (checked before touching the database)
        Ticket = await self.TicketOf(message.channel.id)
        if not Ticket or int(Ticket.get("UserID") or 0) == message.author.id or message.author.id in Ticket.get("profiles_shown", []):
            return
        await self.ShowCard(message.channel, message.author, Ticket, Config)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Profiles follow role changes: promotions restart the time in the role, leaving staff archives it."""
        if before.roles == after.roles or after.bot:
            return
        try:
            Config = await Mail().Get(after.guild.id)
            Staff = StaffRoles(after.guild, Config)
            if Staff:
                await Store().Sync(after.guild.id, after, Rank(after, Staff))
        except Exception as e:
            logger.warning(f"[Profiles] Couldn't sync {after.id}: {e}")


async def setup(client: commands.Bot) -> None:
    await client.add_cog(StaffProfiles(client))
