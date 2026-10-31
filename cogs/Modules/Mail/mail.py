"""/mail: staff suggestions for the Tenno, decided with buttons (Se realizará / Se debatirá / Rechazada)."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.mail.config import (
    DECIDE_SUGGESTIONS, OFFICES, CheckCredential, Department, HasAny, IsStaff, Mail, MailError, OfficesOf,
)
from core.mail.suggestions import OPEN, PRIORITIES, REASON_MAX, STATUSES, TEXT_MAX, TITLE_MAX, Suggestions

logger = logging.getLogger(__name__)
CHOICE_TIMEOUT = 300
ACTIONS = {"do": "Se realizará", "debate": "Se debatirá", "reject": "Rechazada"}
_store: Suggestions | None = None


def Store() -> Suggestions:
    global _store
    if _store is None:
        from core.db import db

        _store = Suggestions(db)
    return _store


# ---------------- embeds and buttons ----------------


def SuggestionEmbed(doc: dict, config: dict, copy: bool = False) -> discord.Embed:
    Emoji, Label, Color = STATUSES[doc["status"]]
    embed = discord.Embed(title=f"📨 Sugerencia #{doc['number']} · {doc['title']}"[:256], description=doc["text"], color=Color, timestamp=doc["created_at"])
    embed.set_author(name=doc["author_name"], icon_url=doc["author_avatar"] or None)
    embed.add_field(name="Estado", value=f"{Emoji} **{Label}**", inline=True)
    D = doc.get("decision")
    if D:
        By = f"<@{D['by']}> · {OFFICES.get(D['office'], D['office'])}" + (" · 🔑" if D.get("credential") else "")
        embed.add_field(name="Decidió", value=By, inline=True)
        if D.get("department"):
            Dep = Department(config, D["department"])
            P = PRIORITIES[D["priority"]]
            embed.add_field(name="Encargado", value=f"🏢 {Dep['name'] if Dep else 'Departamento borrado'} · {P[0]} Prioridad {P[1].lower()}", inline=False)
        embed.add_field(name="Motivo", value=D["reason"][:1024], inline=False)
    embed.set_footer(text=("Copia para debatir · " if copy else "") + "Sugerencia para el Tenno")
    return embed


def DecisionView(doc: dict) -> discord.ui.View | None:
    """Buttons while the suggestion is open (a debated one can only be accepted or rejected)."""
    if doc["status"] not in OPEN:
        return None
    View = discord.ui.View(timeout=None)
    for Action in ("do", "debate", "reject"):
        if Action == "debate" and doc["status"] == "debate":
            continue
        View.add_item(DecisionButton(Action, doc["number"]))
    return View


STYLES = {"do": discord.ButtonStyle.green, "debate": discord.ButtonStyle.blurple, "reject": discord.ButtonStyle.red}


class DecisionButton(discord.ui.DynamicItem[discord.ui.Button], template=r"mail:(?P<action>do|debate|reject):(?P<number>\d+)"):
    """Works after restarts: the action and suggestion number live in the custom id."""

    def __init__(self, action: str, number: int):
        super().__init__(discord.ui.Button(
            label=ACTIONS[action], emoji=STATUSES[action][0], style=STYLES[action], custom_id=f"mail:{action}:{number}",
        ))
        self.action = action
        self.number = number

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
        return cls(match["action"], int(match["number"]))

    async def callback(self, interaction: discord.Interaction):
        Config = await Mail().Get(interaction.guild.id)
        Doc = await Store().Get(interaction.guild.id, self.number)
        if not Doc:
            return await interaction.response.send_message("❌ Esa sugerencia ya no existe.", ephemeral=True)
        if Doc["status"] not in OPEN:
            return await interaction.response.send_message("Esa sugerencia ya está decidida.", ephemeral=True)
        HasRole = HasAny(interaction.user, DECIDE_SUGGESTIONS, Config)
        await interaction.response.send_modal(ReasonModal(self.action, self.number, need_credential=not HasRole))


class ReasonModal(discord.ui.Modal):
    def __init__(self, action: str, number: int, need_credential: bool):
        super().__init__(title=f"{ACTIONS[action]} · #{number}"[:45])
        self.action = action
        self.number = number
        self.reason = discord.ui.TextInput(label="¿Por qué?", style=discord.TextStyle.paragraph, max_length=REASON_MAX)
        self.add_item(self.reason)
        self.credential = None
        if need_credential:
            self.credential = discord.ui.TextInput(label="Credencial (no tienes el rol)", placeholder="Ej. M-1808", max_length=7)
            self.add_item(self.credential)

    async def on_submit(self, interaction: discord.Interaction):
        Config = await Mail().Get(interaction.guild.id)
        try:
            if self.credential is not None:
                Office = CheckCredential(interaction.guild.id, interaction.user.id, self.credential.value, DECIDE_SUGGESTIONS, Config)
                Used = True
            else:
                Mine = OfficesOf(interaction.user, Config) & set(DECIDE_SUGGESTIONS)
                if not Mine:
                    raise MailError("Solo el Tenno y el Consejo Supremo deciden sugerencias.")
                Office, Used = next(O for O in DECIDE_SUGGESTIONS if O in Mine), False
        except MailError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        Decision = {"by": interaction.user.id, "office": Office, "credential": Used, "reason": self.reason.value.strip()}
        if self.action == "do":
            if not Config["departments"]:
                return await interaction.response.send_message("❌ No hay departamentos. Créalos en `/buzon config`.", ephemeral=True)
            View = AssignView(interaction.user, self.number, Decision, Config)
            return await interaction.response.send_message(
                f"✅ **#{self.number} se realizará.** ¿Qué departamento se encarga y con qué prioridad?", view=View, ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        Note = await Apply(interaction, self.number, self.action, Decision, Config)
        await interaction.followup.send(Note, ephemeral=True)


class AssignView(discord.ui.View):
    """Second step of 'Se realizará': department and priority."""

    def __init__(self, author, number: int, decision: dict, config: dict):
        super().__init__(timeout=CHOICE_TIMEOUT)
        self.author, self.number, self.decision, self.config = author, number, decision, config
        self.department: str | None = None
        self.priority = "medium"
        Dep = discord.ui.Select(
            placeholder="🏢 Departamento encargado",
            options=[discord.SelectOption(label=D["name"], value=D["id"], description=D.get("group") or None) for D in config["departments"]][:25],
            row=0,
        )
        Dep.callback = self.PickDepartment
        Pri = discord.ui.Select(
            placeholder="Prioridad",
            options=[discord.SelectOption(label=f"Prioridad {L.lower()}", value=K, emoji=E, default=K == "medium") for K, (E, L) in PRIORITIES.items()],
            row=1,
        )
        Pri.callback = self.PickPriority
        self.add_item(Dep)
        self.add_item(Pri)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author.id

    async def PickDepartment(self, interaction: discord.Interaction):
        self.department = interaction.data["values"][0]
        self.Confirm.disabled = False
        await interaction.response.edit_message(view=self)

    async def PickPriority(self, interaction: discord.Interaction):
        self.priority = interaction.data["values"][0]
        await interaction.response.defer()

    @discord.ui.button(label="Confirmar", emoji="✅", style=discord.ButtonStyle.green, disabled=True, row=2)
    async def Confirm(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        self.stop()
        Note = await Apply(interaction, self.number, "do", {**self.decision, "department": self.department, "priority": self.priority}, self.config)
        await interaction.edit_original_response(content=Note, view=None)


# ---------------- applying a decision ----------------


async def Refresh(guild: discord.Guild, ref: dict | None, embed: discord.Embed, view):
    """Edits a posted suggestion (main message or debate copy)."""
    if not ref:
        return
    Channel = guild.get_channel(ref["channel"])
    if Channel is None:
        return
    try:
        await Channel.get_partial_message(ref["id"]).edit(embed=embed, view=view)
    except discord.HTTPException as e:
        logger.warning(f"[Mail] Couldn't update suggestion message: {e}")


async def Apply(interaction: discord.Interaction, number: int, action: str, decision: dict, config: dict) -> str:
    """Saves the decision, updates the messages, sends the debate copy and tells the author."""
    Guild = interaction.guild
    Doc = await Store().Decide(Guild.id, number, action, decision)
    if not Doc:
        return "Esa sugerencia ya estaba decidida."
    View = DecisionView(Doc)
    await Refresh(Guild, Doc["message"], SuggestionEmbed(Doc, config), View)
    if action == "debate":
        Channel = Guild.get_channel(config.get("debate_channel") or 0)
        if Channel:
            try:
                Copy = await Channel.send(embed=SuggestionEmbed(Doc, config, copy=True), view=DecisionView(Doc))
                await Store().SetMessage(Guild.id, number, "debate_message", Channel.id, Copy.id)
            except discord.HTTPException as e:
                logger.warning(f"[Mail] Couldn't post to the debate channel: {e}")
    else:
        await Refresh(Guild, Doc.get("debate_message"), SuggestionEmbed(Doc, config, copy=True), None)
    Emoji, Label, _ = STATUSES[action]
    Text = f"{Emoji} Tu sugerencia **#{number} «{Doc['title']}»** en **{Guild.name}**: **{Label}**.\n> {decision['reason'][:1500]}"
    if action == "do":
        Dep = Department(config, decision["department"])
        Text += f"\n🏢 Se encarga **{Dep['name'] if Dep else '—'}** · prioridad {PRIORITIES[decision['priority']][1].lower()}."
    Author = Guild.get_member(Doc["author_id"])
    if Author:
        try:
            await Author.send(Text)
        except discord.HTTPException:
            pass
    return f"{Emoji} Sugerencia #{number}: **{Label}**." + (" Enviada a «Cosas por debatir»." if action == "debate" else "")


# ---------------- /mail ----------------


class SuggestionModal(discord.ui.Modal, title="Sugerencia para el Tenno"):
    heading = discord.ui.TextInput(label="Título", max_length=TITLE_MAX)
    body = discord.ui.TextInput(label="Tu sugerencia", style=discord.TextStyle.paragraph, max_length=TEXT_MAX)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        Config = await Mail().Get(interaction.guild.id)
        Channel = interaction.guild.get_channel(Config.get("suggestions_channel") or 0)
        if Channel is None:
            return await interaction.followup.send("❌ El canal de sugerencias no está configurado.", ephemeral=True)
        Doc = await Store().Create(interaction.guild.id, interaction.user, self.heading.value, self.body.value)
        try:
            Message = await Channel.send(embed=SuggestionEmbed(Doc, Config), view=DecisionView(Doc))
        except discord.HTTPException:
            return await interaction.followup.send("❌ No puedo escribir en el canal de sugerencias.", ephemeral=True)
        await Store().SetMessage(interaction.guild.id, Doc["number"], "message", Channel.id, Message.id)
        await interaction.followup.send(f"📨 Sugerencia **#{Doc['number']}** enviada. Te avisaré por MD cuando se decida.", ephemeral=True)


class MailCog(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    async def cog_load(self):
        self.client.add_dynamic_items(DecisionButton)
        await Store().Setup()

    @app_commands.command(name="mail", description="Envía una sugerencia al Tenno (solo staff)")
    @app_commands.guild_only()
    async def mail(self, interaction: discord.Interaction):
        Config = await Mail().Get(interaction.guild.id)
        if not IsStaff(interaction.user, Config):
            return await interaction.response.send_message("❌ `/mail` es solo para el staff.", ephemeral=True)
        await interaction.response.send_modal(SuggestionModal())


async def setup(client: commands.Bot) -> None:
    await client.add_cog(MailCog(client))
