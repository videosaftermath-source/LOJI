"""Tasks: posted in each department's channel, claimed and closed by its members; /tareas lists them."""

import io
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.mail.config import (
    DECIDE_SUGGESTIONS, MANAGE_ANY_TASK, OFFICES, CheckCredential, Department, HasAny, InDepartment, IsStaff, Mail, MailError,
    OfficesOf,
)
from core.mail.suggestions import PRIORITIES
from core.mail.tasks import ACTIVE, DONE_COLOR, LIST_LIMIT, PRIORITY_COLORS, TASK_STATUSES, ParseDeadline, Tasks

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
    "join": ("Unirme", "➕", discord.ButtonStyle.grey),
}
BUTTONS_BY_STATUS = {"open": ("claim", "done"), "claimed": ("done", "release"), "done": ("reopen",)}
MAX_ASSIGNEES = 10
BANNER_MAX = 8 * 1024 * 1024
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
    People = task.get("assignees") or []
    if task["status"] == "claimed" and not People:
        State += f" por <@{task['claimed_by']}>"
    elif task["status"] == "claimed":
        State = "🛠️ **En curso**"
    elif task["status"] == "done":
        State += f" por <@{task['done_by']}>"
    embed.add_field(name="Estado", value=State, inline=True)
    if People:
        embed.add_field(name=f"👥 Encargados ({len(People)})", value=" ".join(f"<@{P}>" for P in People)[:1024], inline=False)
    Deadline = task.get("deadline")
    if Deadline:
        Deadline = Deadline if Deadline.tzinfo else Deadline.replace(tzinfo=timezone.utc)
        Late = task["status"] != "done" and Deadline <= datetime.now(timezone.utc)
        embed.add_field(
            name="⌛ Vencida" if Late else "⏰ Fecha límite",
            value=f"{discord.utils.format_dt(Deadline, 'F')} ({discord.utils.format_dt(Deadline, 'R')})", inline=False,
        )
        if Late:
            embed.color = discord.Color.dark_red()
    if task.get("banner"):
        embed.set_image(url=f"attachment://{task['banner']}")
    embed.set_footer(text=f"De la sugerencia #{task['suggestion']} · Mando Central de LOJI" if task.get("suggestion") else "Tarea directa · Mando Central de LOJI")
    return embed


def TaskView(task: dict) -> discord.ui.View:
    View = discord.ui.View(timeout=None)
    Actions = BUTTONS_BY_STATUS[task["status"]]
    if task["status"] == "claimed" and task.get("assignees"):  # several people: others can join, each one can leave
        Actions = ("done", "join", "release")
    for Action in Actions:
        View.add_item(TaskButton(Action, task["number"]))
    return View


async def CreateTask(guild: discord.Guild, suggestion: dict, decision: dict, config: dict) -> dict:
    """Turns an accepted suggestion into a task and posts it in the department's channel."""
    Banner = decision.get("banner_file")  # (filename, bytes)
    Task = await Store().Create(
        guild.id, suggestion, decision.get("department"), decision["priority"], decision["by"],
        title=decision.get("title", ""), text=decision.get("text", ""), owner=decision.get("owner", "dept"),
        assignees=decision.get("assignees"), deadline=decision.get("deadline"), banner=Banner[0] if Banner else None,
    )
    Dep = Department(config, Task["department"]) if Task["department"] else None
    # Department tasks go to the department's channel; the Mando Central's own ones to "Cosas por debatir".
    ChannelId = (Dep or {}).get("channel") if Dep else config.get("debate_channel")
    Channel = guild.get_channel(ChannelId or 0)
    Task["posted_in"], Task["post_problem"] = None, None
    if not Channel:
        Task["post_problem"] = (
            f"el departamento **{Dep['name']}** no tiene canal" if Dep else "no hay canal «Cosas por debatir» configurado"
        ) + " (`/config` → Mando Central)"
        return Task
    Ping = f"<@&{Dep['role']}> nueva tarea" if Dep and Dep.get("role") else None
    if Task.get("assignees"):  # given to people: they're the ones called
        Ping = " ".join(f"<@{P}>" for P in Task["assignees"]) + " · tenéis una tarea nueva"
    Extra = {"file": discord.File(io.BytesIO(Banner[1]), filename=Banner[0])} if Banner else {}
    try:
        Message = await Channel.send(content=Ping, embed=TaskEmbed(Task, config), view=TaskView(Task),
                                     allowed_mentions=discord.AllowedMentions(roles=True, users=True), **Extra)
        await Store().SetMessage(guild.id, Task["number"], Channel.id, Message.id)
        Task["message"] = {"channel": Channel.id, "id": Message.id}
        Task["posted_in"] = Channel.id
    except discord.HTTPException as e:
        logger.warning(f"[Mail] Couldn't post task: {e}")
        Task["post_problem"] = f"no puedo escribir en {Channel.mention} (revisa mis permisos ahí)"
    return Task


def PostedText(task: dict) -> str:
    """Where the task was posted, or why it wasn't (so it never 'disappears')."""
    if task.get("posted_in"):
        return f" Publicada en <#{task['posted_in']}>."
    if task.get("post_problem"):
        return f"\n⚠️ Guardada, pero **no se publicó**: {task['post_problem']}. Aparece igual en `/tareas ver`."
    return ""


# ---------------- buttons ----------------


def AllowedByRole(member, action: str, task: dict, config: dict) -> bool:
    Manager = HasAny(member, MANAGE_ANY_TASK, config)
    Member = InDepartment(member, Department(config, task["department"]) or {}) if task.get("department") else False
    Assigned = member.id in (task.get("assignees") or []) or task.get("claimed_by") == member.id
    if action in ("claim", "join"):
        return Member or Manager or (action == "join" and IsStaff(member, config))
    if action == "done":
        return Member or Manager or Assigned
    if action == "release":
        return Assigned or Manager
    return Manager  # reopen


class TaskButton(discord.ui.DynamicItem[discord.ui.Button], template=r"task:(?P<action>claim|release|done|reopen|join):(?P<number>\d+)"):
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
    if action in ("claim", "join"):
        Task = await Store_.Claim(Guild.id, number, User.id)
    elif action == "release":
        Current = await Store_.Get(Guild.id, number) or {}
        Mine = User.id in (Current.get("assignees") or []) or Current.get("claimed_by") == User.id
        Task = await Store_.Release(Guild.id, number, User.id if Mine else None)  # a manager not on it frees it
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
        self.who, self.pri = Who, Pri
        self.add_item(Who)
        self.add_item(Pri)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author.id

    def Mark(self, select: discord.ui.Select, value: str):
        """Discord forgets a select's choice when the message is edited; keep it shown."""
        for Option in select.options:
            Option.default = Option.value == value

    async def PickOwner(self, interaction: discord.Interaction):
        Value = interaction.data["values"][0]
        self.owner, self.department = (Value, None) if Value in OWNERS else ("dept", Value)
        self.Mark(self.who, Value)
        self.Mark(self.pri, self.priority)
        self.Confirm.disabled = False
        await interaction.response.edit_message(view=self)

    async def PickPriority(self, interaction: discord.Interaction):
        self.priority = interaction.data["values"][0]
        self.Mark(self.pri, self.priority)
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
            return f"📋 Creada la **tarea #{Task['number']}** · {OwnerText(Task, Config)}.{PostedText(Task)}"

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
        People = T.get("assignees") or []
        Who = (f" · 👥 {len(People)}" if len(People) > 1 else f" · 🙋 <@{T['claimed_by']}>") if T["status"] == "claimed" else ""
        if T.get("deadline"):
            D = T["deadline"] if T["deadline"].tzinfo else T["deadline"].replace(tzinfo=timezone.utc)
            Who += f" · {'⌛' if D <= datetime.now(timezone.utc) else '⏰'} {discord.utils.format_dt(D, 'R')}"
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
        self.Deadlines.start()

    async def cog_load(self):
        self.client.add_dynamic_items(TaskButton)
        await Store().Setup()

    def cog_unload(self):
        self.Deadlines.cancel()

    tareas = app_commands.Group(name="tareas", description="Tareas del staff", guild_only=True)

    @tareas.command(name="ver", description="Lista de tareas del staff, por prioridad")
    async def ver(self, interaction: discord.Interaction):
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

    async def DepartmentChoices(self, interaction: discord.Interaction, current: str):
        Config = await Mail().Get(interaction.guild.id)
        Options = [("👑 Mando Central", "central")] + [(f"🏢 {D['name']}", D["id"]) for D in Config["departments"]]
        return [app_commands.Choice(name=N[:100], value=V) for N, V in Options if current.lower() in N.lower()][:25]

    @tareas.command(name="crear", description="Crear una tarea: para una o varias personas, con fecha límite y banner (opcionales)")
    @app_commands.describe(
        titulo="Título de la tarea", descripcion="Qué hay que hacer",
        encargados="Opcional: menciones o IDs de quienes la harán (varias personas)",
        departamento="Opcional: departamento (si no, Mando Central)", prioridad="Por defecto: media",
        limite="Opcional: 3d, 12h, 2d6h… o una fecha: 05/12, 05/12 18:00",
        banner="Opcional: una imagen para la tarea", credencial="Si no tienes el rol: tu credencial de cargo",
    )
    @app_commands.choices(prioridad=[app_commands.Choice(name=f"{E} {L}", value=K) for K, (E, L) in PRIORITIES.items()])
    @app_commands.autocomplete(departamento=DepartmentChoices)
    async def crear(
        self, interaction: discord.Interaction, titulo: app_commands.Range[str, 1, 100], descripcion: app_commands.Range[str, 1, 2000],
        encargados: str | None = None, departamento: str | None = None, prioridad: str = "medium", limite: str | None = None,
        banner: discord.Attachment | None = None, credencial: str | None = None,
    ):
        import re

        Config = await Mail().Get(interaction.guild.id)
        try:
            if credencial:
                CheckCredential(interaction.guild.id, interaction.user.id, credencial, DECIDE_SUGGESTIONS, Config)
            elif not HasAny(interaction.user, DECIDE_SUGGESTIONS, Config):
                raise MailError("Solo el Tenno y el Consejo Supremo crean tareas (o usa tu credencial de cargo).")
        except MailError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        People = list(dict.fromkeys(int(I) for I in re.findall(r"\d{15,21}", encargados or "")))
        Missing = [P for P in People if not interaction.guild.get_member(P)]
        if Missing:
            return await interaction.response.send_message(f"❌ No encuentro en el servidor a: {' '.join(f'<@{P}>' for P in Missing)}", ephemeral=True)
        if len(People) > MAX_ASSIGNEES:
            return await interaction.response.send_message(f"❌ Máximo {MAX_ASSIGNEES} encargados por tarea.", ephemeral=True)
        Dep = None
        if departamento and departamento != "central":
            if not Department(Config, departamento):
                return await interaction.response.send_message("❌ Elige un departamento de la lista.", ephemeral=True)
            Dep = departamento
        Deadline = None
        if limite:
            try:
                from core.economy.config import EcoConfig

                Offset = (await EcoConfig().Get(interaction.guild.id))["activity"].get("utc_offset", 0)
            except Exception:
                Offset = 0
            try:
                Deadline = ParseDeadline(limite, datetime.now(timezone.utc), Offset)
            except ValueError:
                return await interaction.response.send_message(
                    "❌ No entiendo la fecha límite. Usa `3d`, `12h`, `2d6h`, `45m` o una fecha futura como `05/12` o `05/12 18:00`.", ephemeral=True,
                )
        BannerFile = None
        if banner:
            if not (banner.content_type or "").startswith("image/") or banner.size > BANNER_MAX:
                return await interaction.response.send_message("❌ El banner tiene que ser una imagen de menos de 8 MB.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        if banner:
            Ext = (banner.filename.rsplit(".", 1)[-1] or "png").lower()[:4]
            BannerFile = (f"tarea.{Ext}", await banner.read())  # sent with the task: it doesn't expire like a link
        Decision = {
            "by": interaction.user.id, "title": titulo.strip(), "text": descripcion.strip(), "priority": prioridad,
            "owner": "dept", "department": Dep, "assignees": People, "deadline": Deadline, "banner_file": BannerFile,
        }
        Task = await CreateTask(interaction.guild, None, Decision, Config)
        Who = f" · 👥 {' '.join(f'<@{P}>' for P in People)}" if People else ""
        When = f" · ⏰ {discord.utils.format_dt(Deadline, 'R')}" if Deadline else ""
        await interaction.followup.send(f"📋 Creada la **tarea #{Task['number']}** · {OwnerText(Task, Config)}{Who}{When}.{PostedText(Task)}", ephemeral=True)

    @tasks.loop(minutes=10)
    async def Deadlines(self):
        """24 h before the deadline the people on it are reminded; when it passes, the task is marked overdue."""
        Now_ = datetime.now(timezone.utc)
        try:
            Due = await Store().Due(Now_)
        except Exception as e:
            return logger.warning(f"[Mail] Deadline check failed: {e!r}")
        for T in Due:
            Guild = self.client.get_guild(T["guild_id"])
            if not Guild:
                continue
            Deadline = T["deadline"] if T["deadline"].tzinfo else T["deadline"].replace(tzinfo=timezone.utc)
            Stage = "overdue" if Deadline <= Now_ else "soon"
            if T.get("deadline_warned") == Stage:
                continue
            await Store().col.update_one({"_id": T["_id"]}, {"$set": {"deadline_warned": Stage}})
            T["deadline_warned"] = Stage
            Config = await Mail().Get(Guild.id)
            await RefreshTask(Guild, T, Config)
            Ref = T.get("message")
            Channel = Guild.get_channel(Ref["channel"]) if Ref else None
            if not Channel:
                continue
            People = T.get("assignees") or ([T["claimed_by"]] if T.get("claimed_by") else [])
            Ping = " ".join(f"<@{P}>" for P in People)
            Text = (f"⏰ {Ping} la **tarea #{T['number']} · {T['title']}** vence {discord.utils.format_dt(Deadline, 'R')}."
                    if Stage == "soon" else f"⌛ {Ping} la **tarea #{T['number']} · {T['title']}** ha **vencido** sin marcarse como hecha.")
            try:
                await Channel.send(Text.replace("  ", " "), reference=Channel.get_partial_message(Ref["id"]),
                                   allowed_mentions=discord.AllowedMentions(users=True))
            except discord.HTTPException:
                pass

    @Deadlines.before_loop
    async def BeforeDeadlines(self):
        await self.client.wait_until_ready()


async def setup(client: commands.Bot) -> None:
    await client.add_cog(TasksCog(client))
