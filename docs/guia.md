# Guía de sanciones (`/guia`)

El staff le pregunta dudas a la guía de sanciones. La responde la IA configurada: **DeepSeek** (`deepseek-chat`, key `sk-…`) o **Groq** (`openai/gpt-oss-120b`, key `gsk_…`), según la key, **usando solo lo que dice la guía**.

## Configurar (`/config` → Mando Central → 📚 Guía de sanciones)
- **📤 Subir guía:** Word (`.docx`), `.txt` o `.md`. Reemplaza a la anterior y se aplica al momento.
- **📥 Descargar guía actual:** el texto exacto que lee el bot. Sirve para comprobar cómo quedaron las tablas.
- **🎭 Rol:** quién puede preguntar.
- **🔑 Key de la IA:** DeepSeek (`sk-…`) o Groq (`gsk_…`); LOJI reconoce cuál es. Se guarda en la base de datos; si la dejas vacía, se usa `DEEPSEEK_API_KEY` o `GROQ_API_KEY` del `.env`. La misma key la usan el autoreporte y LOJI (chat).

## Uso
- `/guia pregunta:...`: la respuesta solo la ve quien pregunta y cita la sección de la guía. Si la guía no cubre la duda, lo dice.
- **2 preguntas por persona cada 24 horas**, contadas desde cada pregunta.
- Si falla la IA (límite de uso, sin saldo, sin conexión…), **no se descuenta** la pregunta.
- **Sin memoria:** cada pregunta es independiente. Solo se guarda la hora de cada pregunta, para el límite.

## Consejo
Los títulos numerados (por ejemplo, "3.2 Spam reincidente") hacen que las respuestas citen bien. Los títulos de Word se conservan.
