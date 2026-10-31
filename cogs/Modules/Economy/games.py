"""/juegos: a friendly guide to every casino game, with live limits from the server's config."""

import random

import discord
from discord.ext import commands

from cogs.Modules.Economy.marcha_game import MarchaView

from core.bot.Module import ModuleIsEnabled
from core.economy import marcha as M
from core.economy.casino import GameSettings
from core.economy.config import EcoConfig
from core.economy.constants import MODULE

GUIDE_TIMEOUT = 300
LOJI_RED = discord.Color.from_rgb(150, 12, 18)

# key -> (emoji, name, command, hook, how to play, prizes, tip)
GAMES_GUIDE = {
    "marcha": (
        "🃏", "La Larga Marcha", "/casino marcha",
        "Póker por etapas al estilo Balatro: arma combinaciones, compra comodines y desafía a los jefes hasta LOJI.",
        "Tienes 8 cartas. Elige hasta 5 y juega la mejor combinación: **fichas × multi** suma *señal*. Llega a la señal "
        "de cada ciega con 4 manos y 3 descartes. Entre ciegas, gasta tus **◈ Datos** en comodines y mejoras. "
        "La tercera ciega de cada ante es un **jefe** con una regla que te complica la vida.",
        "Tras vencer a cada jefe eliges: **cobrar** o **seguir**. Ante 1 ×0,6 → 3 ×1,1 → 4 ×2 → 5 ×5 → 6 ×12 → 7 ×30 → **LOJI ×75**.",
        "Ahorra ◈: cada 5 te dan +1 de interés. Y fíjate en qué jefe viene antes de llegar.",
    ),
    "coinflip": (
        "🪙", "Moneda", "/casino moneda",
        "Cara o cruz. Simple, rápido y con la ventaja de la casa más baja.",
        "Eliges cara o cruz y apuestas. Si aciertas, casi doblas.",
        "Ganas ×{coinflip_x}.",
        "Ideal para apuestas rápidas sin complicarte.",
    ),
    "blackjack": (
        "🃏", "Blackjack", "/casino blackjack",
        "El clásico: llega a 21 sin pasarte y gánale al crupier.",
        "Pide cartas o plántate. Puedes **doblar** tu apuesta y recibir una sola carta más. El crupier se planta en 17.",
        "Ganar paga ×2 · Blackjack natural ×2,5 · Empate te devuelve la apuesta.",
        "Plántate con 12-16 si el crupier muestra 2-6: es él quien suele pasarse.",
    ),
    "slots": (
        "🎰", "Slots", "/casino slots",
        "Tres rodillos, cero complicaciones. Una de cada tres tiradas gana.",
        "Apuesta y gira. Paga con parejas y tríos.",
        "Parejas desde ×1,28 · Tríos hasta **7️⃣7️⃣7️⃣ ×832**.",
        "La tabla completa está en `/casino info`.",
    ),
    "deluxe": (
        "🎰", "Tragamonedas de lujo", "/casino tragamonedas",
        "La versión animada: mira girar los rodillos y frenar uno por uno.",
        "Igual que Slots, pero con animación y un poco mejor para ti.",
        "Mismos premios que Slots: hasta **×832**.",
        "Tarda un poco más en cada tirada, pero la casa se queda menos.",
    ),
    "crash": (
        "🚀", "Crash", "/casino crash",
        "El cohete sube y el multiplicador con él... ¿te retiras a tiempo?",
        "El multiplicador crece hasta que el cohete explota. Pulsa **retirarse** antes, o pon un retiro automático.",
        "Cobras tu apuesta × el multiplicador al que te retiraste (hasta ×{crash_cap}).",
        "A veces explota al instante. No persigas el ×20: retirarse a tiempo también es ganar.",
    ),
    "roulette": (
        "🎡", "Ruleta", "/casino ruleta",
        "Ruleta europea de un solo cero. Elige tu suerte.",
        "Apuesta a rojo/negro, par/impar, mitades, docenas o a un número exacto.",
        "Colores, par/impar y mitades ×2 · Docenas ×3 · Número ×36.",
        "Un número paga mucho pero sale 1 de cada 37 veces.",
    ),
    "mines": (
        "💣", "Mines", "/casino mines",
        "Un tablero, minas escondidas y diamantes que multiplican.",
        "Abre casillas: cada 💎 sube el multiplicador. Si tocas una 💣, pierdes. Retírate cuando quieras.",
        "Con más minas, cada diamante paga más (hasta ×{mines_cap}). Al terminar: 🔁 jugar de nuevo.",
        "Con pocas minas puedes avanzar tranquilo; con muchas, cada casilla es un salto al vacío.",
    ),
    "hilo": (
        "🔼", "Mayor o menor", "/casino mayormenor",
        "¿La siguiente carta será mayor o menor? Cada acierto multiplica.",
        "Adivina y sigue la racha. Si empata, pierdes. Retírate cuando quieras.",
        "Cada acierto multiplica según lo difícil que era (hasta ×{hilo_cap}).",
        "Con un 2 o una K en la mesa, la jugada está casi regalada.",
    ),
    "race": (
        "🏇", "Carrera", "/casino carrera",
        "Cinco caballos, una meta. ¿Favorito o tapado?",
        "Elige un caballo y mira la carrera.",
        "El favorito paga poco (×2,7) y el tapado mucho (×12).",
        "¿Te sientes con suerte? Turbo Burro nunca miente... casi nunca.",
    ),
}


def Limits(config: dict, key: str) -> str:
    S = GameSettings(config, key)
    Line = f"{S['min']:,} – {S['max']:,}".replace(",", ".")
    if key == "marcha":
        return f"Entrada {Line} · {S['daily_limit']} al día"
    Edge = f"{S['edge']:.1%}".replace(".", ",")
    return f"Apuesta {Line} · Casa {Edge}" if S["edge"] else f"Apuesta {Line}"


def Fill(text: str, config: dict) -> str:
    C = config["casino"]
    return text.format(
        coinflip_x=f"{2 * (1 - C['coinflip']['edge']):.2f}".replace(".", ","),
        crash_cap=C["crash"]["max_multiplier"], mines_cap=C["mines"]["max_multiplier"], hilo_cap=C["hilo"]["max_multiplier"],
    )


def Overview(config: dict) -> discord.Embed:
    embed = discord.Embed(
        title="🎲 Casino de LOJI",
        description=(
            "Todos los juegos con **tus créditos**. Elige uno en el menú para ver cómo se juega y qué paga.\n"
            "-# Las apuestas aceptan `500`, `1.5k`, `todo` o `mitad`. La casa siempre gana un poquito: juega por diversión."
        ),
        color=LOJI_RED,
    )
    for Key, (Emoji, Name, Command, Hook, *_) in GAMES_GUIDE.items():
        Star = " ⭐ NUEVO" if Key == "marcha" else ""
        embed.add_field(name=f"{Emoji} {Name}{Star}", value=f"{Hook}\n-# `{Command}` · {Limits(config, Key)}", inline=False)
    Cap = config["casino_limit"]
    if Cap["enabled"]:
        embed.set_footer(text=f"Límite de apuesta en todo el casino: {Cap['max']:,}".replace(",", ".") + " · Tus estadísticas: /casino info")
    return embed


def Detail(config: dict, key: str) -> discord.Embed:
    Emoji, Name, Command, Hook, How, Prizes, Tip = GAMES_GUIDE[key]
    embed = discord.Embed(title=f"{Emoji} {Name}", description=f"*{Hook}*", color=LOJI_RED)
    embed.add_field(name="🎮 Cómo se juega", value=How, inline=False)
    embed.add_field(name="💰 Premios", value=Fill(Prizes, config), inline=False)
    embed.add_field(name="💡 Consejo", value=Tip, inline=False)
    embed.add_field(name="▶️ Para jugar", value=f"`{Command}` · {Limits(config, key)}", inline=False)
    if key == "marcha":
        Bosses = " · ".join(N for B, (N, _, _) in M.BOSSES.items() if B != M.FINAL_BOSS)
        embed.add_field(name="👹 Jefes", value=f"{Bosses}\n🔴 **Jefe final: LOJI**", inline=False)
    return embed


class GameMenu(discord.ui.View):
    def __init__(self, author: discord.abc.User, config: dict):
        super().__init__(timeout=GUIDE_TIMEOUT)
        self.author = author
        self.config = config
        Select = discord.ui.Select(
            placeholder="Ver un juego en detalle",
            options=[discord.SelectOption(label="Todos los juegos", value="all", emoji="🎲")]
            + [discord.SelectOption(label=Name, value=Key, emoji=Emoji, description=Hook[:100]) for Key, (Emoji, Name, _, Hook, *_) in GAMES_GUIDE.items()],
        )
        Select.callback = self.Pick
        self.add_item(Select)

    async def Pick(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("Usa `/juegos` para abrir tu propia guía 😉", ephemeral=True)
        Key = interaction.data["values"][0]
        embed = Overview(self.config) if Key == "all" else Detail(self.config, Key)
        await interaction.response.edit_message(embed=embed, view=self)


PRACTICE_JOKERS = ["camarada", "doble"]  # so the practice shows what jokers do
PRACTICE_MONEY = 8


def TutorialEmbed() -> discord.Embed:
    embed = discord.Embed(
        title="🎓 Tutorial · La Larga Marcha",
        description=(
            "Un póker por etapas donde **armas combinaciones**, compras **comodines** y desafías a **jefes** "
            "hasta llegar a **LOJI**. Lee esto en un minuto y luego juega una **práctica gratis**."
        ),
        color=LOJI_RED,
    )
    embed.add_field(name="1️⃣ El objetivo", value=(
        "Cada ronda (*ciega*) pide una cantidad de **señal**. Tienes **4 manos** para conseguirla y **3 descartes** "
        "para cambiar cartas malas."
    ), inline=False)
    embed.add_field(name="2️⃣ Cómo se puntúa", value=(
        "Eliges hasta 5 de tus 8 cartas y juegas la mejor combinación.\n"
        "**Señal = fichas × multi**. La combinación da una base y las cartas que puntúan suman sus fichas "
        "(A = 11, figuras = 10).\n-# Pareja 10×2 · Doble 20×2 · Trío 30×3 · Escalera 30×4 · Color 35×4 · Full 40×4 · Póker 60×7"
    ), inline=False)
    embed.add_field(name="3️⃣ Comodines y tienda", value=(
        "Al ganar una ciega recibes **◈ Datos**: la recompensa, +1 por cada mano que te sobre y **+1 de interés por cada 5 que guardes**. "
        "En la tienda compras **comodines** (+multi, ×multi, fichas extra...) y **actualizaciones** que suben de nivel una jugada. "
        "Máximo 5 comodines."
    ), inline=False)
    embed.add_field(name="4️⃣ Antes y jefes", value=(
        "Cada **ante** tiene 3 ciegas: 🛡️ Patrulla, 🧱 Muralla y 👹 **Jefe**. Cada jefe tiene una **regla especial** "
        "(por ejemplo, que los ♥ no puntúen). Sabes cuál viene antes de llegar. El jefe del ante 8 es **LOJI**."
    ), inline=False)
    embed.add_field(name="5️⃣ Cobrar o seguir", value=(
        "En la partida de verdad pagas una entrada. Tras vencer a cada jefe eliges **cobrar** o **seguir**: "
        "×0,6 → ×1,1 → ×2 → ×5 → ×12 → ×30 → **×75 si vences a LOJI**. Si caes, lo pierdes todo."
    ), inline=False)
    embed.set_footer(text="La práctica es gratis, dura un ante y no cuenta para el límite diario.")
    return embed


class TutorialStart(discord.ui.View):
    def __init__(self, author: discord.abc.User, config: dict):
        super().__init__(timeout=GUIDE_TIMEOUT)
        self.author = author
        self.config = config

    @discord.ui.button(label="Empezar práctica", emoji="🎓", style=discord.ButtonStyle.red)
    async def Start(self, interaction: discord.Interaction, _):
        Game = M.NewGame(0, random.SystemRandom(), antes=1)
        Game["jokers"], Game["money"] = list(PRACTICE_JOKERS), PRACTICE_MONEY
        View = MarchaView(interaction.user, Game, self.config, practice=True)
        embed, Files = await View.Render()
        await interaction.response.send_message(embed=embed, files=Files, view=View, ephemeral=True)


class EconomyGames(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    @commands.hybrid_command(name="juegos", description="Todos los juegos del casino, explicados")
    @commands.guild_only()
    @ModuleIsEnabled(MODULE)
    async def juegos(self, ctx: commands.Context):
        Config = await EcoConfig().Get(ctx.guild.id)
        await ctx.send(embed=Overview(Config), view=GameMenu(ctx.author, Config))


    @commands.hybrid_group(name="tutorial", description="Aprende a jugar")
    @commands.guild_only()
    async def tutorial(self, ctx: commands.Context):
        pass

    @tutorial.command(name="marcha", description="Aprende La Larga Marcha con una partida de práctica gratis")
    @ModuleIsEnabled(MODULE)
    async def tutorial_marcha(self, ctx: commands.Context):
        Config = await EcoConfig().Get(ctx.guild.id)
        await ctx.send(embed=TutorialEmbed(), view=TutorialStart(ctx.author, Config), ephemeral=True)


async def setup(client: commands.Bot) -> None:
    await client.add_cog(EconomyGames(client))
