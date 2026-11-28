# 🚩 Autoreporte (reporte rápido)
`/config` → Mando Central → 📚 Guía de sanciones → **🚩 Autoreporte**. Usa la misma key de IA que `/guia` (DeepSeek o Groq).

1. Un mensaje de uno de los **canales vigilados** (hasta 25) recibe **2× 🚩** de personas distintas (sin contar al autor ni bots).
2. LOJI envía a la IA **solo ese mensaje** y los 6 anteriores (para entender el contexto), con vuestras **normas** (`.txt`/`.docx`, como la guía).
3. Al **canal del staff** llega una ficha, sea sancionable o no:
   veredicto (⚠️ parece sancionable / ✅ no parece sancionable), norma, motivo, sugerencia, quién reportó,
   historial (reportes previos del autor y falsas alarmas de quienes reportan) y la confianza de la IA.
4. Botones **✅ Falsa alarma** y **⚖️ Se actuará** (solo staff; el primero que pulsa resuelve y queda apuntado).

- Cada mensaje se reporta una sola vez. Mensajes sin texto (solo imágenes) llegan sin la opinión de la IA.
- **Límite diario** de revisiones con IA (por defecto 60): pasado, las fichas siguen llegando sin la opinión de la IA.
- **🚨 Abuso:** alerta si alguien participa en 5 reportes en 24 h o reporta 3 veces al mismo usuario (configurable).
- **⚙️ Ajustes:** emoji, reacciones necesarias, límite diario y umbrales de abuso. Rol opcional al que avisar con cada ficha.
- El texto del mensaje reportado solo queda en la ficha (Discord), no en la base de datos. Está explicado en `PRIVACIDAD.md`.
