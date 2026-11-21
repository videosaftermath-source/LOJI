"""/roleban: quarantine a member (every role off but the quarantine one) and give the roles back later."""

import asyncio
import logging
from datetime import timezone

import discord
from discord import app_commands
from discord.ext import commands

from core.bot.permissions import Permissions
from core.roleban import Plan, RolesList, Restorable, Rolebans

logger = logging.getLogger(__name__)
LOJI_RED = discord.Color.from_rgb(150, 12, 18)
_store: Rolebans | None = None


def Store() -> Rolebans:
    global _store
    if _store is None:
        from core.db import db

        _store = Rolebans(db)
    return _store


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

    @roleban.command(name="configurar", description="Rol y canal de cuarentena, y canal de registro")
    @app_commands.describe(
        rol="El rol de cuarentena (solo debe poder ver el canal de cuarentena)",
        canal="Donde se avisa al usuario (el canal de cuarentena)",
        registro="Canal del staff donde queda constancia (opcional)",
    )
    @Permissions("Admin")
    async def configurar(self, interaction: discord.Interaction, rol: discord.Role, canal: discord.TextChannel, registro: discord.TextChannel | None = None):
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
        await Store().SetConfig(interaction.guild.id, {"role": rol.id, "channel": canal.id, "log": registro.id if registro else None})
        Everyone = canal.permissions_for(rol)
        Tip = "" if Everyone.view_channel and Everyone.send_messages else f"\n⚠️ {rol.mention} todavía **no puede ver o escribir** en {canal.mention}: dale permiso en ese canal."
        await interaction.response.send_message(
            f"✅ Cuarentena lista: rol {rol.mention}, canal {canal.mention}"
            + (f", registro {registro.mention}" if registro else "")
            + ".\n-# Recuerda que el rol de cuarentena **no** debe ver el resto de canales (quítale *Ver canal* donde @everyone lo tenga)."
            + Tip,
            ephemeral=True,
        )

    # ---------------- add ----------------

    @roleban.command(name="add", description="Quita todos los roles a un miembro y lo deja en cuarentena")
    @app_commands.describe(usuario="A quién", motivo="Por qué (queda en el registro)")
    @Permissions("Staff")
    async def add(self, interaction: discord.Interaction, usuario: discord.Member, motivo: app_commands.Range[str, 1, 500] = "Sin motivo"):
        Guild, Mod, Me = interaction.guild, interaction.user, interaction.guild.me
        Config = await Store().Config(Guild.id)
        Quarantine = Guild.get_role(Config.get("role") or 0)
        if not Quarantine:
            return await interaction.response.send_message("❌ Falta configurarlo: `/roleban configurar`.", ephemeral=True)
        if usuario.bot or usuario.id in (Mod.id, Guild.owner_id):
            return await interaction.response.send_message("❌ No puedes ponerle cuarentena a esa persona.", ephemeral=True)
        if usuario.top_role >= Mod.top_role and Mod.id != Guild.owner_id:
            return await interaction.response.send_message("❌ No puedes: tiene un rol igual o más alto que el tuyo.", ephemeral=True)
        if usuario.top_role >= Me.top_role:
            return await interaction.response.send_message("❌ No puedo: tiene un rol igual o más alto que el mío.", ephemeral=True)
        await interaction.response.defer()
        async with self.Lock(Guild.id, usuario.id):
            if await Store().Active(Guild.id, usuario.id):
                return await interaction.followup.send(f"❌ {usuario.mention} ya está en cuarentena.", allowed_mentions=discord.AllowedMentions.none())
            Remove, Keep = Plan(usuario.roles, Quarantine.id, Me.top_role.position)
            Doc = await Store().Start(Guild.id, usuario.id, Remove, Mod.id, motivo)
            if not Doc:
                return await interaction.followup.send(f"❌ {usuario.mention} ya está en cuarentena.", allowed_mentions=discord.AllowedMentions.none())
            try:
                await usuario.edit(roles=Keep + [Quarantine], reason=f"Roleban por {Mod} ({Mod.id}): {motivo}"[:512])
            except discord.HTTPException as e:
                await Store().End(Guild.id, usuario.id, "failed", Mod.id, str(e))
                return await interaction.followup.send(f"❌ No pude cambiarle los roles: {e.text or e}")
        Saved = Doc["roles"]
        Channel = Guild.get_channel(Config.get("channel") or 0)
        if Channel:
            try:
                await Channel.send(
                    f"{usuario.mention}, has sido puesto en **cuarentena** (roleban).\n"
                    "El staff te explicará el motivo por aquí.\n"
                    "⚠️ **SI SALES DEL SERVIDOR SERÁS BANEADO.**",
                    embed=RolesEmbed(usuario, Saved, "🔒 Roles retirados"),
                    allowed_mentions=discord.AllowedMentions(users=[usuario]),
                )
            except discord.HTTPException as e:
                logger.warning(f"[Roleban] Can't post in the quarantine channel: {e}")
        Done = discord.Embed(
            description=f"🔒 {usuario.mention} está en **cuarentena**. Se le quitaron **{len(Saved)}** rol{'es' if len(Saved) != 1 else ''}."
            + (f"\n-# Se quedan {len(Keep)} que no puedo quitar (booster, bots o por encima de mi rol)." if Keep else ""),
            color=LOJI_RED,
        )
        await interaction.followup.send(embed=Done, allowed_mentions=discord.AllowedMentions.none())
        Log = RolesEmbed(usuario, Saved, "🔒 Roleban")
        Log.add_field(name="Usuario", value=f"{usuario.mention} (`{usuario.id}`)", inline=True)
        Log.add_field(name="Moderador", value=Mod.mention, inline=True)
        Log.add_field(name="Motivo", value=motivo[:1024], inline=False)
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
            Quarantine = Guild.get_role(Config.get("role") or 0)
            Now = [R for R in usuario.roles if not R.is_default() and R != Quarantine]
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
        embed.add_field(name="Motivo", value=Doc.get("reason") or "—", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @roleban.command(name="lista", description="Quién está en cuarentena ahora")
    @Permissions("Staff")
    async def lista(self, interaction: discord.Interaction):
        Docs = await Store().List(interaction.guild.id)
        embed = discord.Embed(title=f"🔒 En cuarentena ({len(Docs)})", color=LOJI_RED)
        embed.description = "\n".join(f"• <@{D['user_id']}> · por <@{D['by']}> · {(D.get('reason') or '—')[:60]}" for D in Docs)[:4000] or "Nadie."
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
        Role = member.guild.get_role((await Store().Config(member.guild.id)).get("role") or 0)
        if Role:
            try:
                await member.add_roles(Role, reason="Volvió estando en cuarentena (roleban)")
            except discord.HTTPException as e:
                logger.warning(f"[Roleban] Couldn't re-apply quarantine to {member.id}: {e}")


async def setup(client: commands.Bot) -> None:
    await client.add_cog(Roleban(client))
