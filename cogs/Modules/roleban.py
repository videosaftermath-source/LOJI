"""/roleban: quarantine a member (every role off but the quarantine one) and give the roles back later."""

import asyncio
import logging
import re
from datetime import timezone

import discord
from discord import app_commands
from discord.ext import commands

from core.bot.permissions import Permissions
from core.roleban import MAX_SLOTS, Plan, RolesList, Restorable, Rolebans, SetSlot, Slots

logger = logging.getLogger(__name__)
LOJI_RED = discord.Color.from_rgb(150, 12, 18)
_store: Rolebans | None = None


def Store() -> Rolebans:
    global _store
    if _store is None:
        from core.db import db

        _store = Rolebans(db)
    return _store


MAX_BULK = 25
WARNING = "El staff te explicará el motivo por aquí.\n⚠️ **SI SALES DEL SERVIDOR SERÁS BANEADO.**"


def ParseIds(text: str) -> list[int]:
    """Mentions or IDs in any order and separator, without repeats."""
    return list(dict.fromkeys(int(I) for I in re.findall(r"\d{15,21}", text or "")))


def PickSlot(guild: discord.Guild, config: dict, canal: str) -> tuple[dict | None, str | None]:
    Available = Slots(config)
    if not Available:
        return None, "❌ Falta configurarlo: `/roleban configurar`."
    Slot = next((S for S in Available if str(S["channel"]) == (canal or "").strip().strip("<#>")), None)
    if not Slot:
        return None, "❌ Elige uno de los canales de cuarentena de la lista."
    if not guild.get_role(Slot["role"]):
        return None, "❌ El rol de ese canal de cuarentena ya no existe: vuelve a configurarlo."
    return Slot, None


def CanQuarantine(guild: discord.Guild, mod, member) -> str | None:
    if member.bot or member.id in (mod.id, guild.owner_id):
        return f"❌ {member.mention}: no se le puede poner cuarentena."
    if member.top_role >= mod.top_role and mod.id != guild.owner_id:
        return f"❌ {member.mention}: tiene un rol igual o más alto que el tuyo."
    if member.top_role >= guild.me.top_role:
        return f"❌ {member.mention}: tiene un rol igual o más alto que el mío."
    return None


def SlotsText(guild: discord.Guild, slots: list[dict], log: int | None) -> str:
    Lines = [f"{I}. <#{S['channel']}> → <@&{S['role']}>" for I, S in enumerate(slots, 1)] or ["*ninguno*"]
    return f"**Canales de cuarentena ({len(slots)}/{MAX_SLOTS}):**\n" + "\n".join(Lines) + (f"\nRegistro: <#{log}>" if log else "")


def RolesEmbed(member, roles: list[dict], title: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=f"**Roles ({len(roles)}):**\n\n{RolesList(roles)}", color=LOJI_RED)
    embed.set_author(name=member.display_name if hasattr(member, "display_name") else str(member), icon_url=member.display_avatar.url)
    return embed


class Roleban(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.locks: dict[tuple[int, int], asyncio.Lock] = {}

    def Lock(self, guild_id: int, user_id: int) -> asyncio.Lock:
        return self.locks.setdefault((guild_id, user_id), asyncio.Lock())

    roleban = app_commands.Group(name="roleban", description="Cuarentena: quitar todos los roles y devolverlos", guild_only=True)

    async def Log(self, guild: discord.Guild, config: dict, embed: discord.Embed):
        Channel = guild.get_channel(config.get("log") or 0)
        if Channel:
            try:
                await Channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException as e:
                logger.warning(f"[Roleban] Can't log in {Channel.id}: {e}")

    # ---------------- setup ----------------

    @roleban.command(name="configurar", description="Añade (o cambia) un canal de cuarentena con su rol (máximo 3)")
    @app_commands.describe(
        canal="Canal de cuarentena: donde se avisa al usuario",
        rol="Rol de cuarentena de ese canal (solo debe poder ver ese canal)",
        registro="Canal del staff donde queda constancia (opcional, vale para todos)",
    )
    @Permissions("Admin")
    async def configurar(self, interaction: discord.Interaction, canal: discord.TextChannel, rol: discord.Role, registro: discord.TextChannel | None = None):
        Me = interaction.guild.me
        Problems = []
        if not Me.guild_permissions.manage_roles:
            Problems.append("Me falta **Gestionar roles**.")
        if rol >= Me.top_role:
            Problems.append(f"{rol.mention} está por encima de mi rol más alto: súbeme el rol.")
        if not Me.guild_permissions.ban_members:
            Problems.append("Me falta **Banear miembros** (para banear a quien se salga en cuarentena).")
        if rol.managed or rol.is_default():
            Problems.append("Ese rol no sirve: elige un rol normal.")
        if not canal.permissions_for(Me).send_messages:
            Problems.append(f"No puedo escribir en {canal.mention}.")
        if Problems:
            return await interaction.response.send_message("❌ " + "\n❌ ".join(Problems), ephemeral=True)
        Config = await Store().Config(interaction.guild.id)
        try:
            New = SetSlot(Slots(Config), canal.id, rol.id)
        except ValueError:
            return await interaction.response.send_message(
                f"❌ Ya hay {MAX_SLOTS} canales de cuarentena. Quita uno con `/roleban quitar-canal`.", ephemeral=True,
            )
        Changes = {"slots": New}
        if registro:
            Changes["log"] = registro.id
        await Store().SetConfig(interaction.guild.id, Changes)
        Perms = canal.permissions_for(rol)
        Tip = "" if Perms.view_channel and Perms.send_messages else f"\n⚠️ {rol.mention} todavía **no puede ver o escribir** en {canal.mention}: dale permiso en ese canal."
        await interaction.response.send_message(
            f"✅ Canal de cuarentena guardado: {canal.mention} con {rol.mention}.\n"
            + SlotsText(interaction.guild, New, registro.id if registro else Config.get("log"))
            + "\n-# Cada rol de cuarentena **no** debe ver el resto de canales (quítale *Ver canal* donde @everyone lo tenga)."
            + Tip,
            ephemeral=True,
        )

    @roleban.command(name="quitar-canal", description="Quita uno de los canales de cuarentena")
    @app_commands.describe(canal="El canal de cuarentena que ya no se usará")
    @Permissions("Admin")
    async def quitar_canal(self, interaction: discord.Interaction, canal: discord.TextChannel):
        Config = await Store().Config(interaction.guild.id)
        Current = Slots(Config)
        New = [S for S in Current if S["channel"] != canal.id]
        if len(New) == len(Current):
            return await interaction.response.send_message(f"❌ {canal.mention} no es un canal de cuarentena.", ephemeral=True)
        await Store().SetConfig(interaction.guild.id, {"slots": New})
        await interaction.response.send_message(
            f"🧹 {canal.mention} ya no es canal de cuarentena.\n" + SlotsText(interaction.guild, New, Config.get("log"))
            + "\n-# Quien ya esté en cuarentena ahí sigue igual; `pardon` funciona normal.",
            ephemeral=True,
        )

    async def ChannelChoices(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        Choices = []
        for S in Slots(await Store().Config(interaction.guild.id)):
            Channel = interaction.guild.get_channel(S["channel"])
            Name = f"#{Channel.name}" if Channel else f"Canal borrado ({S['channel']})"
            if current.lower().lstrip("#") in Name.lower():
                Choices.append(app_commands.Choice(name=Name[:100], value=str(S["channel"])))
        return Choices

    # ---------------- add ----------------

    @roleban.command(name="add", description="Quita todos los roles a un miembro y lo deja en cuarentena")
    @app_commands.describe(usuario="A quién", canal="A qué canal de cuarentena va", motivo="Por qué (queda en el registro)")
    @app_commands.autocomplete(canal=ChannelChoices)
    @Permissions("Staff")
    async def add(self, interaction: discord.Interaction, usuario: discord.Member, canal: str, motivo: app_commands.Range[str, 1, 500] = "Sin motivo"):
        Guild = interaction.guild
        Config = await Store().Config(Guild.id)
        Slot, Problem = PickSlot(Guild, Config, canal)
        if Problem:
            return await interaction.response.send_message(Problem, ephemeral=True)
        Problem = CanQuarantine(Guild, interaction.user, usuario)
        if Problem:
            return await interaction.response.send_message(Problem, ephemeral=True)
        await interaction.response.defer()
        Doc, Keep, Problem = await self.Apply(Guild, interaction.user, usuario, Slot, motivo)
        if Problem:
            return await interaction.followup.send(Problem, allowed_mentions=discord.AllowedMentions.none())
        Saved = Doc["roles"]
        Channel = Guild.get_channel(Slot["channel"])
        if Channel:
            try:
                await Channel.send(
                    f"{usuario.mention}, has sido puesto en **cuarentena** (roleban).\n" + WARNING,
                    embed=RolesEmbed(usuario, Saved, "🔒 Roles retirados"),
                    allowed_mentions=discord.AllowedMentions(users=[usuario]),
                )
            except discord.HTTPException as e:
                logger.warning(f"[Roleban] Can't post in the quarantine channel: {e}")
        Done = discord.Embed(
            description=f"🔒 {usuario.mention} está en **cuarentena** en <#{Slot['channel']}>. Se le quitaron **{len(Saved)}** rol{'es' if len(Saved) != 1 else ''}."
            + (f"\n-# Se quedan {len(Keep)} que no puedo quitar (booster, bots o por encima de mi rol)." if Keep else ""),
            color=LOJI_RED,
        )
        await interaction.followup.send(embed=Done, allowed_mentions=discord.AllowedMentions.none())
        Log = RolesEmbed(usuario, Saved, "🔒 Roleban")
        Log.add_field(name="Usuario", value=f"{usuario.mention} (`{usuario.id}`)", inline=True)
        Log.add_field(name="Moderador", value=interaction.user.mention, inline=True)
        Log.add_field(name="Canal", value=f"<#{Slot['channel']}>", inline=True)
        Log.add_field(name="Motivo", value=motivo[:1024], inline=False)
        Log.timestamp = discord.utils.utcnow()
        await self.Log(Guild, Config, Log)

    async def Apply(self, guild: discord.Guild, mod, member: discord.Member, slot: dict, reason: str):
        """Takes the roles and saves them. (roleban, roles that stay, problem)."""
        Quarantine = guild.get_role(slot["role"])
        async with self.Lock(guild.id, member.id):
            if await Store().Active(guild.id, member.id):
                return None, [], f"❌ {member.mention} ya está en cuarentena."
            Remove, Keep = Plan(member.roles, Quarantine.id, guild.me.top_role.position)
            Doc = await Store().Start(guild.id, member.id, Remove, mod.id, reason, slot)
            if not Doc:
                return None, [], f"❌ {member.mention} ya está en cuarentena."
            try:
                await member.edit(roles=Keep + [Quarantine], reason=f"Roleban por {mod} ({mod.id}): {reason}"[:512])
            except discord.HTTPException as e:
                await Store().End(guild.id, member.id, "failed", mod.id, str(e))
                return None, [], f"❌ {member.mention}: no pude cambiarle los roles ({e.text or e})"
        return Doc, Keep, None

    @roleban.command(name="varios", description="Cuarentena para varios a la vez (raids): menciones o IDs")
    @app_commands.describe(
        usuarios=f"Menciones o IDs separados por espacios o comas (máximo {MAX_BULK})",
        canal="A qué canal de cuarentena van", motivo="Por qué (queda en el registro)",
    )
    @app_commands.autocomplete(canal=ChannelChoices)
    @Permissions("Staff")
    async def varios(self, interaction: discord.Interaction, usuarios: str, canal: str, motivo: app_commands.Range[str, 1, 500] = "Raid"):
        Guild, Mod = interaction.guild, interaction.user
        Config = await Store().Config(Guild.id)
        Slot, Problem = PickSlot(Guild, Config, canal)
        if Problem:
            return await interaction.response.send_message(Problem, ephemeral=True)
        Ids = ParseIds(usuarios)
        if not Ids:
            return await interaction.response.send_message("❌ No encontré ninguna mención ni ID.", ephemeral=True)
        if len(Ids) > MAX_BULK:
            return await interaction.response.send_message(f"❌ Máximo {MAX_BULK} a la vez (pusiste {len(Ids)}).", ephemeral=True)
        await interaction.response.defer()
        Done, Failed = [], []
        for Id in Ids:
            Member = Guild.get_member(Id)
            if not Member:
                try:
                    Member = await Guild.fetch_member(Id)
                except discord.HTTPException:
                    Failed.append(f"`{Id}`: no está en el servidor")
                    continue
            Problem = CanQuarantine(Guild, Mod, Member)
            if not Problem:
                Doc, _, Problem = await self.Apply(Guild, Mod, Member, Slot, motivo)
            if Problem:
                Failed.append(f"{Member.mention}: {Problem.removeprefix('❌ ').replace(Member.mention, '').strip(' :.') or 'no se pudo'}")
            else:
                Done.append((Member, Doc))
        if Done:
            Channel = Guild.get_channel(Slot["channel"])
            if Channel:
                try:
                    await Channel.send(
                        " ".join(M.mention for M, _ in Done) + "\nHabéis sido puestos en **cuarentena** (roleban).\n" + WARNING,
                        allowed_mentions=discord.AllowedMentions(users=[M for M, _ in Done]),
                    )
                except discord.HTTPException as e:
                    logger.warning(f"[Roleban] Can't post in the quarantine channel: {e}")
        Summary = discord.Embed(title="🔒 Cuarentena masiva", color=LOJI_RED)
        Summary.description = f"Canal: <#{Slot['channel']}>"
        Summary.add_field(
            name=f"✅ En cuarentena ({len(Done)})",
            value="\n".join(f"{M.mention} · {len(D['roles'])} rol{'es' if len(D['roles']) != 1 else ''}" for M, D in Done)[:1024] or "—",
            inline=False,
        )
        if Failed:
            Summary.add_field(name=f"❌ No se pudo ({len(Failed)})", value="\n".join(Failed)[:1024], inline=False)
        await interaction.followup.send(embed=Summary, allowed_mentions=discord.AllowedMentions.none())
        if Done:
            Log = Summary.copy()
            Log.add_field(name="Moderador", value=Mod.mention, inline=True)
            Log.add_field(name="Motivo", value=motivo[:1024], inline=False)
            Log.set_footer(text="Los roles de cada uno: /roleban ver")
            Log.timestamp = discord.utils.utcnow()
            await self.Log(Guild, Config, Log)

    # ---------------- pardon ----------------

    @roleban.command(name="pardon", description="Saca a un miembro de la cuarentena y le devuelve sus roles")
    @app_commands.describe(usuario="A quién", motivo="Por qué (queda en el registro)")
    @Permissions("Staff")
    async def pardon(self, interaction: discord.Interaction, usuario: discord.Member, motivo: app_commands.Range[str, 1, 500] = "Sin motivo"):
        Guild, Mod, Me = interaction.guild, interaction.user, interaction.guild.me
        Config = await Store().Config(Guild.id)
        await interaction.response.defer()
        async with self.Lock(Guild.id, usuario.id):
            Doc = await Store().Active(Guild.id, usuario.id)
            if not Doc:
                return await interaction.followup.send(f"❌ {usuario.mention} no está en cuarentena.", allowed_mentions=discord.AllowedMentions.none())
            Back, Lost = Restorable(Doc["roles"], {R.id: R for R in Guild.roles}, Me.top_role.position)
            Quarantine = {Doc.get("role")} | {S["role"] for S in Slots(Config)}  # whichever quarantine role they have
            Now = [R for R in usuario.roles if not R.is_default() and R.id not in Quarantine]
            try:
                await usuario.edit(roles=list(dict.fromkeys(Now + Back)), reason=f"Roleban levantado por {Mod} ({Mod.id}): {motivo}"[:512])
            except discord.HTTPException as e:
                return await interaction.followup.send(f"❌ No pude devolverle los roles: {e.text or e}")
            await Store().End(Guild.id, usuario.id, "pardon", Mod.id, motivo)
        Done = discord.Embed(
            description=f"🔓 {usuario.mention} sale de la cuarentena. Se le devolvieron **{len(Back)}** rol{'es' if len(Back) != 1 else ''}."
            + (f"\n-# No pude devolver {len(Lost)}: {', '.join(R['name'] for R in Lost)[:500]} (borrados o por encima de mi rol)." if Lost else ""),
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=Done, allowed_mentions=discord.AllowedMentions.none())
        Log = RolesEmbed(usuario, [{"id": R.id, "name": R.name} for R in Back], "🔓 Roleban levantado")
        Log.color = discord.Color.green()
        Log.add_field(name="Usuario", value=f"{usuario.mention} (`{usuario.id}`)", inline=True)
        Log.add_field(name="Moderador", value=Mod.mention, inline=True)
        Log.add_field(name="Motivo", value=motivo[:1024], inline=False)
        Log.timestamp = discord.utils.utcnow()
        await self.Log(Guild, Config, Log)

    # ---------------- info ----------------

    @roleban.command(name="ver", description="Mira si alguien está en cuarentena y qué roles se le guardaron")
    @Permissions("Staff")
    async def ver(self, interaction: discord.Interaction, usuario: discord.User):
        Doc = await Store().Active(interaction.guild.id, usuario.id)
        if not Doc:
            Past = len(await Store().History(interaction.guild.id, usuario.id))
            return await interaction.response.send_message(
                f"{usuario.mention} no está en cuarentena." + (f" Ha tenido **{Past}** roleban{'s' if Past != 1 else ''} antes." if Past else ""),
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
            )
        embed = RolesEmbed(usuario, Doc["roles"], "🔒 En cuarentena")
        embed.add_field(name="Desde", value=discord.utils.format_dt(Doc["at"] if Doc["at"].tzinfo else Doc["at"].replace(tzinfo=timezone.utc), "R"), inline=True)
        embed.add_field(name="Por", value=f"<@{Doc['by']}>", inline=True)
        if Doc.get("channel"):
            embed.add_field(name="Canal", value=f"<#{Doc['channel']}>", inline=True)
        embed.add_field(name="Motivo", value=Doc.get("reason") or "—", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @roleban.command(name="lista", description="Quién está en cuarentena ahora")
    @Permissions("Staff")
    async def lista(self, interaction: discord.Interaction):
        Docs = await Store().List(interaction.guild.id)
        embed = discord.Embed(title=f"🔒 En cuarentena ({len(Docs)})", color=LOJI_RED)
        embed.description = "\n".join(f"• <@{D['user_id']}> · " + (f"<#{D['channel']}> · " if D.get("channel") else "") + f"por <@{D['by']}> · {(D.get('reason') or '—')[:60]}" for D in Docs)[:4000] or "Nadie."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------------- leaving = ban ----------------

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        Doc = await Store().Active(member.guild.id, member.id)
        if not Doc:
            return
        try:
            await member.guild.ban(discord.Object(member.id), reason="Salió del servidor estando en cuarentena (roleban)", delete_message_seconds=0)
            Banned = True
        except discord.HTTPException as e:
            logger.warning(f"[Roleban] Couldn't ban {member.id} for leaving: {e}")
            Banned = False
        if Banned:  # if the ban failed, the roleban stays: rejoining puts them back in quarantine
            await Store().End(member.guild.id, member.id, "left", None, "Salió del servidor")
        Log = discord.Embed(
            title="⛔ Salió estando en cuarentena",
            description=f"<@{member.id}> (`{member.id}`) se fue del servidor durante el roleban: "
            + ("**baneado**." if Banned else "**no pude banearlo** (revisa mis permisos). Si vuelve, se le pone la cuarentena otra vez."),
            color=discord.Color.dark_red(),
            timestamp=discord.utils.utcnow(),
        )
        await self.Log(member.guild, await Store().Config(member.guild.id), Log)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not await Store().Active(member.guild.id, member.id):
            return
        Doc = await Store().Active(member.guild.id, member.id)
        Fallback = Slots(await Store().Config(member.guild.id))
        Role = member.guild.get_role(Doc.get("role") or (Fallback[0]["role"] if Fallback else 0))
        if Role:
            try:
                await member.add_roles(Role, reason="Volvió estando en cuarentena (roleban)")
            except discord.HTTPException as e:
                logger.warning(f"[Roleban] Couldn't re-apply quarantine to {member.id}: {e}")


async def setup(client: commands.Bot) -> None:
    await client.add_cog(Roleban(client))
