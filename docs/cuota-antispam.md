# 🛡️ Anti-spam de la cuota de mensajes
`/config` → Cuota (Quota) → **Anti-spam**. Activado por defecto.

| Nivel | Cuándo (por defecto) | Qué pasa |
|---|---|---|
| ⚠️ 1 · escribir rápido | más de **6** mensajes en **10 s** | Los que sobran **no cuentan**. Aviso suave en el canal (se borra a los 15 s, como mucho uno por minuto). |
| 🚨 2 · spam | **30** mensajes en **60 s** | Se **descuentan** esos mensajes, no le cuenta nada durante **10 min** y sale el aviso con el banner de LOJI enfadada, mencionando a quien elijas. |

En los dos niveles, alerta en el **canal de alertas** para administración (quién, dónde, cuántos se descontaron).

- **Niveles:** `mensajes/segundos` de cada nivel y minutos de pausa.
- **A quién llamar:** una persona o un rol (en el texto es `{aviso}`; si no hay nadie, «la administración»).
- **Textos:** nivel 1 (`{user}`, `{nombre}`) y título y texto del nivel 2 (`{user}`, `{aviso}`, `{cantidad}`).
- **Banner:** LOJI descarga y **guarda su propia copia** de la imagen, así que funciona aunque el enlace caduque (los de Discord caducan).
- **Probar:** te enseña los dos avisos solo a ti.
- LOJI recuerda los mensajes recientes en memoria: al reiniciar empieza de cero.
