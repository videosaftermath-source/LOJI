# 🤖 LOJI (chat)
`/config` → **🎉 Crecimiento y Entretenimiento** → **🤖 LOJI (chat)**. Usa la key de IA de `/guia` (DeepSeek o Groq).

- **Canal** donde conversa (uno) y **canal de alertas** del staff (opcional).
- **📤 Subir personalidad:** el `.txt` / `.md` / `.docx` con quién es LOJI y cómo habla (hasta ~10.000 tokens).
- **Cuándo entra:** menos de **4 personas** y menos de **10 mensajes** en **5 min**, durante **2 min** seguidos, y al menos
  **20 min** después de su última salida. **Cuándo se va:** con 4+ personas en 5 min, dice la **despedida** y se duerme.
  Todo en **⚙️ Umbrales**.
- Mientras está: **junta los mensajes antes de contestar** y responde a todos en **una sola petición**. Con el primer
  mensaje abre una ventana: si alguien más escribe en los primeros **4 s**, contesta en cuanto haya **3 s** sin mensajes
  nuevos; si no, espera **7–10 s**. Nunca más de **20 s**. Luego "está escribiendo…" y responde con la función de
  *responder* de Discord (le llega la notificación): la última que le habló (mención, respuesta
  o "loji"). Si nadie le habló, ella elige: contestar a alguien (como respuesta de Discord) o comentar al chat en general,
  siguiendo el hilo (sabe quién responde a quién). Si DeepSeek devuelve una respuesta vacía, lo reintenta solo (hasta 3 veces).
  Si la etiquetaron varios, responde a **entre 4 y 6** (al azar; los más recientes), cada uno como respuesta de Discord,
  y al resto le dice **una frase al azar** de su lista de 110 (nunca una de las últimas que usó). Un **33 %** de las veces
  simplemente ignora al resto. Todo se cambia en **👋 Textos fijos**: frases propias (una por línea; vacío = las de LOJI;
  «nada» = no decir nada), a cuántos responde por tanda (por ejemplo `4-6`) y el % de veces que ignora. Nunca dos veces seguidas sin respuesta.
  Cuando la mandas a hablar con el chat activo, solo contesta a quien se dirige a ella.
- **🧠 Límites y memoria:** mensajes al día (150), tokens de contexto (10.000), días que recuerda las conversaciones (7)
  y las cosas de la gente (14).
- **👀 Modo observación:** no habla; el panel muestra cuándo habría entrado en los últimos 7 días, para ajustar los umbrales.
- **Seguridad** (por encima de la personalidad): nada sexual ni de ligar, nada de política real, no pide datos personales,
  ignora a quien intenta cambiarle las reglas, y si alguien parece estar muy mal le responde con cariño y avisa al staff (💗).
- **Interruptor** (`/loji interruptor` o el botón ⏯️ del panel), **solo con la credencial del Tenno**:
  🗣️ **Que hable ya** (aunque el chat esté activo; se queda hasta que la calles, y
  respetando el límite diario), 😴 **Que se calle ya** (se despide), ⏯️ **Encender / apagar el modo automático**.
- **Privacidad:** `/loji olvidame` borra lo de esa persona y deja de guardarlo (otra vez = deshacer).
