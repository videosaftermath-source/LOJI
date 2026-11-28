# 🎉 Eventos
`/config` → **🎉 Crecimiento y Entretenimiento** → Eventos: rol del equipo de eventos, canal de anuncios, rol a avisar
(opcional), canal de registro (opcional), minutos de aviso previo y color.

## `/evento crear` (equipo de eventos o administración)
1. Formulario: **título**, **descripción**, **cuándo** (`05/12 18:00`, o `2d`, `3h`…), **premios** (opcional) y **banner** (opcional).
   Premios, un puesto por línea: `1: 5000 monedas, @Campeón, Nitro Basic`. Las monedas y los roles se entregan solos;
   lo demás (Nitro…) queda apuntado para entregarlo a mano. Los `@Rol` se reconocen por su nombre.
2. Borrador con opciones: **✋ Inscripción** (sí/no), **🔢 Plazas** (vacío = sin límite), **📅 Evento de Discord**
   (el de arriba del servidor, con canal de voz o escenario opcional), **📄 Diseño JSON** propio, **👁️ Vista previa**,
   **📤 Publicar** o **🗑️ Descartar**.
3. Diseño JSON: variables `{titulo}` `{descripcion}` `{fecha}` `{premios}` `{inscritos}` `{organiza}`; los botones van
   en `{botones}` o al final.

## Después
- **✋ Me apunto** (pulsar otra vez = desapuntarse) y **👥 Inscritos**. Con plazas, nadie se cuela en la última.
- Aviso **X minutos antes** (a los inscritos, o al rol a avisar si no hay inscripción) y otro al empezar.
- `/evento finalizar evento ganadores:@1º @2º @3º`: reparte los premios por orden, publica los resultados, cierra la
  inscripción, termina el evento de Discord y te lista lo que hay que entregar a mano.
- `/evento cancelar` y `/evento historial` (últimos eventos, ganadores y eventos por organizador en 30 días).
