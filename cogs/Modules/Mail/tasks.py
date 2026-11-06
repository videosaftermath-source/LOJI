"""Tasks: posted in each department's channel, claimed and closed by its members; /tareas lists them."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.mail.config import (
    DECIDE_SUGGESTIONS, MANAGE_ANY_TASK, OFFICES, CheckCredential, Department, HasAny, InDepartment, IsStaff, Mail, MailError,
    OfficesOf,
)
from core.mail.suggestions import PRIORITIES
from core.mail.tasks import ACTIVE, DONE_COLOR, LIST_LIMIT, PRIORITY_COLORS, TASK_STATUSES, Tasks

logger = logging.getLogger(__name__)
LIST_TIMEOUT = 300
CHOICE_TIMEOUT = 300
LOJI_RED = discord.Color.from_rgb(150, 12, 18)
CENTRAL = "👑 Mando Central"
# Who takes a task, besides a department.
OWNERS = {"self": ("Lo haré yo", "🙋", "Queda a tu cargo; nadie más puede tomarla"), "done": ("Ya lo hice", "✅", "Queda resuelta al momento")}
ACTIONS = {
    "claim": ("Reclamar", "🙋", discord.ButtonStyle.blurple),
    "release": ("Soltar", "↩️", discord.ButtonStyle.grey),
    "done": ("Hecha", "✅", discord.ButtonStyle.green),
    "reopen": ("Reabrir", "🔄", discord.ButtonStyle.grey),
}
BUTTONS_BY_STATUS = {"open": ("claim", "done"), "claimed": ("done", "release"), "done": ("reopen",)}
_store: Tasks | None = None


def Store() -> Tasks:
    global _store
    if _store is None:
        from core.db import db

        _store = Tasks(db)
    return _store


def DepartmentName(config: dict, department_id: str | None) -> str:
    if not department_id:
        return CENTRAL
    D = Department(config, department_id)
    return D["name"] if D else "Departamento borrado"


def TaskEmbed(task: dict, config: dict) -> discord.embeds.Embed:
    Emoji, Label = TASK_STATUSES[task["status"]]
    P = PRIORITIES[task["priority"]]
    Color = DONE_COLOR if task["status"] == "done" else PRIORITY_COLORS[task["priority"]]
    embed = discord.Embed(title=f"📋 Tarea #{task['number']} · {task['title']}"[:256], description=task["text"][:4000], color=Color, timestamp=task["created_at"])
    Where = DepartmentName(config, task["department"])
    embed.add_field(name="Departamento", value=Where if not task["department"] else f"🏢 {Where}", inline=True)
    embed.add_field(name="Prioridad", value=f"{P[0]} {P[1]}", inline=True)
    State = f"{Emoji} **{Label}**"
    if task["status"] == "claimed":
        State += f" por <@{task['claimed_by']}>"
    elif task["status"] == "done":
        State += f" por <@{task['done_by']}>"
    embed.add_field(name="Estado", value=State, inline=True)
    embed.set_footer(text=f"De la sugerencia #{task['suggestion']} · Mando Central de LOJI" if task.get("suggestion") else "Tarea directa · Mando Central de LOJI")
    return embed


def TaskView(task: dict) -> discord.ui.View:
    View = discord.ui.View(timeout=None)
    for Action in BUTTONS_BY_STATUS[task["status"]]:
        View.add_item(TaskButton(Action, task["number"]))
    return View


async def CreateTask(guild: discord.Guild, suggestion: dict, decision: dict, config: dict) -> dict:
    """Turns an accepted suggestion into a task and posts it in the department's channel."""
    Task = await Store().Create(
        guild.id, suggestion, decision.get("department"), decision["priority"], decision["by"],
        title=decision.get("title", ""), text=decision.get("text", ""), owner=decision.get("owner", "dept"),
    )
    Dep = Department(config, Task["department"]) if Task["department"] else None
    Channel = guild.get_channel((Dep or {}).get("channel") or 0)
    if Channel:
        Ping = f"<@&{Dep['role']}> nueva tarea" if Dep.get("role") else None
        try:
            Message = await Channel.send(content=Ping, embed=TaskEmbed(Task, config), view=TaskView(Task),
                                         allowed_mentions=discord.AllowedMentions(roles=True))
            await Store().SetMessage(guild.id, Task["number"], Channel.id, Message.id)
        except discord.HTTPException as e:
            logger.warning(f"[Mail] Couldn't post task: {e}")
    return Task


# ---------------- buttons ----------------


def AllowedByRole(member, action: str, task: dict, config: dict) -> bool:
    Manager = HasAny(member, MANAGE_ANY_TASK, config)
    Member = InDepartment(member, Department(config, task["department"]) or {}) if task.get("department") else False
    if action == "claim":
        return Member or Manager
    if action == "done":
        return Member or Manager or task.get("claimed_by") == member.id
    if action == "release":
        return task.get("claimed_by") == member.id or Manager
    return Manager  # reopen


class TaskButton(discord.ui.DynamicItem[discord.ui.Button], template=r"task:(?P<action>claim|release|done|reopen):(?P<number>\d+)"):
    def __init__(self, action: str, number: int):
        Label, Emoji, Style = ACTIONS[action]
        super().__init__(discord.ui.Button(label=Label, emoji=Emoji, style=Style, custom_id=f"task:{action}:{number}"))
        self.action = action
        self.number = number

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
        return cls(match["action"], int(match["number"]))

    async def callback(self, interaction: discord.Interaction):
        Config = await Mail().Get(interaction.guild.id)
        Task = await Store().Get(interaction.guild.id, self.number)
        if not Task:
            return await interaction.response.send_message("❌ Esa tarea ya no existe.", ephemeral=True)
        if AllowedByRole(interaction.user, self.action, Task, Config):
            await interaction.response.defer(ephemeral=True)
            Office = next((O for O in MANAGE_ANY_TASK if O in OfficesOf(interaction.user, Config)), None)
            return await interaction.followup.send(await Perform(interaction, self.action, self.number, Config, Office), ephemeral=True)
        # Not by role: the high offices can still act with their credential.
        await interaction.response.send_modal(CredentialModal(self.action, self.number))


class CredentialModal(discord.ui.Modal):
    def __init__(self, action: str, number: int):
        super().__init__(title=f"{ACTIONS[action][0]} tarea #{number}"[:45])
        self.action = action
        self.number = number
        self.credential = discord.ui.TextInput(
            label="No tienes el rol: credencial de cargo", placeholder="Tenno, Consejo o Director. Ej. M-1808", max_length=7,
        )
        self.add_item(self.credential)

    async def on_submit(self, interaction: discord.Interaction):
        Config = await Mail().Get(interaction.guild.id)
        try:
            Office = CheckCredential(interaction.guild.id, interaction.user.id, self.credential.value, MANAGE_ANY_TASK, Config)
        except MailError as e:
            return await interaction.response.send_message(
                f"❌ {e}\n-# Las tareas las gestiona su departamento; Tenno, Consejo y Director pueden con cualquiera.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(await Perform(interaction, self.action, self.number, Config, Office, credential=True), ephemeral=True)


async def Perform(interaction: discord.Interaction, action: str, number: int, config: dict, office: str | None, credential: bool = False) -> str:
    Guild, User = interaction.guild, interaction.user
    Store_ = Store()
    if action == "claim":
        Task = await Store_.Claim(Guild.id, number, User.id)
    elif action == "release":
        Task = await Store_.Release(Guild.id, number)
    elif action == "done":
        Task = await Store_.Done(Guild.id, number, User.id)
    else:
        Task = await Store_.Reopen(Guild.id, number)
    if not Task:
        return "Esa tarea cambió mientras tanto. Mira su estado actual."
    await RefreshTask(Guild, Task, config)
    if action in ("done", "reopen"):
        await SyncSuggestion(Guild, Task, config)
    if action == "done" and Task.get("suggestion_author"):
        Author = Guild.get_member(Task["suggestion_author"])
        if Author:
            try:
                await Author.send(f"✅ Tu sugerencia **#{Task['suggestion']} «{Task['title']}»** en **{Guild.name}** ya está **hecha**. ¡Gracias!")
            except discord.HTTPException:
                pass
    Emoji, Label = TASK_STATUSES[Task["status"]]
    Via = f" (con credencial de {OFFICES[office]})" if credential and office else ""
    return f"{Emoji} Tarea #{number}: **{Label}**{Via}."


async def RefreshTask(guild: discord.Guild, task: dict, config: dict):
    Ref = task.get("message")
    Channel = guild.get_channel(Ref["channel"]) if Ref else None
    if not Channel:
        return
    try:
        await Channel.get_partial_message(Ref["id"]).edit(embed=TaskEmbed(task, config), view=TaskView(task))
    except discord.HTTPException as e:
        logger.warning(f"[Mail] Couldn't update task message: {e}")


async def SyncSuggestion(guild: discord.Guild, task: dict, config: dict):
    """Shows the task's state on the original suggestion."""
    from cogs.Modules.Mail import mail

    if not task.get("suggestion"):
        return
    Doc = await mail.Store().col.find_one_and_update(
        {"guild_id": guild.id, "number": task["suggestion"]}, {"$set": {"task_status": task["status"]}}, return_document=True
    )
    if Doc:
        await mail.Refresh(guild, Doc.get("message"), mail.SuggestionEmbed(Doc, config), mail.DecisionView(Doc))


# ---------------- choosing who does it ----------------


class OwnerPicker(discord.ui.View):
    """A department, "I'll do it" or "already done", plus a priority. Calls on_confirm(interaction, decision)."""

    def __init__(self, author, config: dict, on_confirm):
        super().__init__(timeout=CHOICE_TIMEOUT)
        self.author, self.config, self.on_confirm = author, config, on_confirm
        self.owner: str | None = None
        self.department: str | None = None
        self.priority = "medium"
        Who = discord.ui.Select(
            placeholder="¿Quién se encarga?",
            options=[discord.SelectOption(label=L, value=K, emoji=E, description=D) for K, (L, E, D) in OWNERS.items()]
            + [discord.SelectOption(label=D["name"], value=D["id"], emoji="🏢", description=D.get("group") or "Departamento") for D in config["departments"]][:23],
            row=0,
        )
        Who.callback = self.PickOwner
        Pri = discord.ui.Select(
            placeholder="Prioridad",
            options=[discord.SelectOption(label=f"Prioridad {L.lower()}", value=K, emoji=E, default=K == "medium") for K, (E, L) in PRIORITIES.items()],
            row=1,
        )
        Pri.callback = self.PickPriority
        self.add_item(Who)
        self.add_item(Pri)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author.id

    async def PickOwner(self, interaction: discord.Interaction):
        Value = interaction.data["values"][0]
        self.owner, self.department = (Value, None) if Value in OWNERS else ("dept", Value)
        self.Confirm.disabled = False
        await interaction.response.edit_message(view=self)

    async def PickPriority(self, interaction: discord.Interaction):
        self.priority = interaction.data["values"][0]
        await interaction.response.defer()

    @discord.ui.button(label="Confirmar", emoji="✅", style=discord.ButtonStyle.green, disabled=True, row=2)
    async def Confirm(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        self.stop()
        Note = await self.on_confirm(interaction, {"owner": self.owner, "department": self.department, "priority": self.priority})
        await interaction.edit_original_response(content=Note, view=None)


def OwnerText(task_or_decision: dict, config: dict) -> str:
    Owner = task_or_decision.get("owner", "dept")
    if Owner == "self":
        return "🙋 Lo hace personalmente quien lo aprobó"
    if Owner == "done":
        return "✅ Ya resuelto por quien lo aprobó"
    return f"🏢 {DepartmentName(config, task_or_decision.get('department'))}"


class NewTaskModal(discord.ui.Modal, title="Nueva tarea del Mando Central"):
    def __init__(self, need_credential: bool):
        super().__init__()
        self.heading = discord.ui.TextInput(label="Título", max_length=100)
        self.body = discord.ui.TextInput(label="Qué hay que hacer", style=discord.TextStyle.paragraph, max_length=2000)
        self.add_item(self.heading)
        self.add_item(self.body)
        self.credential = None
        if need_credential:
            self.credential = discord.ui.TextInput(label="Credencial (no tienes el rol)", placeholder="Ej. M-1808", max_length=7)
            self.add_item(self.credential)

    async def on_submit(self, interaction: discord.Interaction):
        Config = await Mail().Get(interaction.guild.id)
        try:
            if self.credential is not None:
                Office = CheckCredential(interaction.guild.id, interaction.user.id, self.credential.value, DECIDE_SUGGESTIONS, Config)
            elif not HasAny(interaction.user, DECIDE_SUGGESTIONS, Config):
                raise MailError("Solo el Tenno y el Consejo Supremo crean tareas directas.")
            else:
                Office = next(O for O in DECIDE_SUGGESTIONS if O in OfficesOf(interaction.user, Config))
        except MailError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        Base = {"by": interaction.user.id, "office": Office, "title": self.heading.value.strip(), "text": self.body.value.strip()}

        async def Create(i: discord.Interaction, choice: dict) -> str:
            Task = await CreateTask(i.guild, None, {**Base, **choice}, Config)
            return f"📋 Creada la **tarea #{Task['number']}** · {OwnerText(Task, Config)}."

        await interaction.response.send_message("📋 ¿Quién se encarga y con qué prioridad?", view=OwnerPicker(interaction.user, Config, Create), ephemeral=True)


# ---------------- /tareas ----------------

FILTERS = {"active": ("Abiertas", ACTIVE), "open": ("Sin reclamar", ("open",)), "claimed": ("Reclamadas", ("claimed",)), "done": ("Hechas", ("done",))}


def ListEmbed(tasks: list[dict], config: dict, guild: discord.Guild, status: str, department: str | None) -> discord.Embed:
    Where = CENTRAL if department == "central" else DepartmentName(config, department) if department else ""
    Title = "📋 Tareas · " + FILTERS[status][0] + (f" · {Where}" if Where else "")
    embed = discord.Embed(title=Title, color=LOJI_RED)
    Lines = []
    for T in tasks[:LIST_LIMIT]:
        P = PRIORITIES[T["priority"]][0]
        Who = f" · 🙋 <@{T['claimed_by']}>" if T["status"] == "claimed" else ""
        Ref = T.get("message")
        Link = f" · [ver](https://discord.com/channels/{guild.id}/{Ref['channel']}/{Ref['id']})" if Ref else ""
        Place = DepartmentName(config, T["department"])
        Lines.append(f"{P} **#{T['number']}** {T['title'][:60]} · {Place if not T['department'] else '🏢 ' + Place}{Who}{Link}")
    embed.description = "\n".join(Lines) or "Nada por aquí 🎉"
    if len(tasks) > LIST_LIMIT:
        embed.set_footer(text=f"Mostrando {LIST_LIMIT} de {len(tasks)} · ordenadas por prioridad")
    else:
        embed.set_footer(text="Ordenadas por prioridad · 🔴 alta · 🟡 media · 🟢 baja")
    return embed


class ListView(discord.ui.View):
    def __init__(self, author, config: dict, status: str = "active", department: str | None = None):
        super().__init__(timeout=LIST_TIMEOUT)
        self.author, self.config, self.status, self.department = author, config, status, department
        Deps = discord.ui.Select(
            placeholder="🏢 Filtrar por departamento",
            options=[discord.SelectOption(label="Todos", value="all", default=department is None),
                     discord.SelectOption(label="Mando Central (personales)", value="central", emoji="👑", default=department == "central")]
            + [discord.SelectOption(label=D["name"], value=D["id"], default=D["id"] == department) for D in config["departments"]][:24],
            row=0,
        )
        Deps.callback = self.PickDepartment
        States = discord.ui.Select(
            placeholder="Estado",
            options=[discord.SelectOption(label=L, value=K, default=K == status) for K, (L, _) in FILTERS.items()],
            row=1,
        )
        States.callback = self.PickStatus
        self.add_item(Deps)
        self.add_item(States)
        New = discord.ui.Button(label="Nueva tarea", emoji="➕", style=discord.ButtonStyle.green, row=2)
        New.callback = self.NewTask
        self.add_item(New)

    async def NewTask(self, interaction: discord.Interaction):
        """Direct tasks (no /mail): Tenno and Consejo Supremo, by role or with their credential."""
        HasRole = HasAny(interaction.user, DECIDE_SUGGESTIONS, self.config)
        await interaction.response.send_modal(NewTaskModal(need_credential=not HasRole))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author.id

    async def Show(self, interaction: discord.Interaction):
        Tasks_ = await Store().List(interaction.guild.id, FILTERS[self.status][1], self.department)
        await interaction.response.edit_message(
            embed=ListEmbed(Tasks_, self.config, interaction.guild, self.status, self.department),
            view=ListView(self.author, self.config, self.status, self.department),
        )

    async def PickDepartment(self, interaction: discord.Interaction):
        Value = interaction.data["values"][0]
        self.department = None if Value == "all" else Value
        await self.Show(interaction)

    async def PickStatus(self, interaction: discord.Interaction):
        self.status = interaction.data["values"][0]
        await self.Show(interaction)


class TasksCog(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    async def cog_load(self):
        self.client.add_dynamic_items(TaskButton)
        await Store().Setup()

    @app_commands.command(name="tareas", description="Lista de tareas del staff, por prioridad")
    @app_commands.guild_only()
    async def tareas(self, interaction: discord.Interaction):
        Config = await Mail().Get(interaction.guild.id)
        if not IsStaff(interaction.user, Config):
            return await interaction.response.send_message("❌ `/tareas` es solo para el staff.", ephemeral=True)
        # Start on the user's own department if they belong to exactly one.
        Mine = [D["id"] for D in Config["departments"] if InDepartment(interaction.user, D)]
        Dep = Mine[0] if len(Mine) == 1 else None
        Tasks_ = await Store().List(interaction.guild.id, ACTIVE, Dep)
        await interaction.response.send_message(
            embed=ListEmbed(Tasks_, Config, interaction.guild, "active", Dep), view=ListView(interaction.user, Config, "active", Dep),
            ephemeral=True,
        )


async def setup(client: commands.Bot) -> None:
    await client.add_cog(TasksCog(client))
