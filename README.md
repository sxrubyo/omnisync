# Omni Core v2.1 - The Supreme Coordinator

Omni Core es un runtime de migración, reconstrucción y mantenimiento de hosts Linux. Su objetivo es dejar una máquina nueva en estado útil sin restauraciones manuales una por una, separando código, estado y secretos.

La entrada recomendada ya no es memorizar comandos bajos. La puerta principal es:

```bash
omni
```

o:

```bash
omni start
```

Eso abre el flujo guiado para elegir entre `bridge`, `capture`, `restore`, `migrate`, `doctor` o `agent`.

Para hablar normal con Omni una vez configurada la IA:

```bash
omni chat
```

Si quieres ver playbooks listos o sacar un comando PowerShell de auto-actualización:

```bash
omni examples
omni auto --p
```

## Qué resuelve

Omni sirve para:

- capturar el estado real del host
- exportar secretos aparte y cifrados
- restaurar o migrar a otro servidor
- corregir referencias viejas de IP y hostname
- dejar backups automáticos
- dejar mantenimiento diario con `systemd`
- usar una terminal Windows/PowerShell solo como puente hacia Linux
- hablar con Omni Agent en una interfaz conversacional real

No intenta mezclar todo en Git. El código viaja por Git; el estado y los secretos viajan por `bundles`.

## Modelo mental

Omni trabaja con tres bloques:

1. `state bundle`
   Contiene estado restaurable del host según el manifest activo.

2. `secrets bundle`
   Contiene `.env`, claves, tokens, sesiones y material sensible cifrado.

3. `manifest profile`
   Decide qué se captura y cómo se reconstruye.

## Perfiles

### `production-clean`

Perfil productivo liviano. Mantiene lo importante sin arrastrar ruido innecesario.

Úsalo cuando quieres:

- una migración limpia
- reconstrucción portable
- menor tamaño de bundle

### `full-home`

Captura literalmente todo `/home/ubuntu` como raíz de estado y deja secretos aparte.

Úsalo cuando quieres:

- llevarte todo el host
- clonar un entorno completo
- no perder `.codex`, `.agents`, `.nova`, `.n8n`, `melissa`, `nova-os`, `Workflows-n8n`, `whatsapp-bridge`, `xus-https`, `melissa-backups` y similares

Activación:

```bash
omni init --profile full-home
```

## Qué entra en `full-home`

Con `full-home`, Omni trata `/home/ubuntu` entero como estado.

Eso incluye, entre otros:

- `.codex`
- `.agents`
- `.nova`
- `.n8n`
- `melissa`
- `melissa-instances`
- `whatsapp-bridge`
- `nova-os`
- `Workflows-n8n`
- `xus-https`
- `melissa-backups`
- `omni-core`

`melissa-backups` importa si quieres reconstrucción real con histórico. Suele ser una de las carpetas más pesadas.

## Qué no reemplaza GitHub

Poner el repo público o clonar desde GitHub ayuda solo con el código de `omni-core`.

No reemplaza:

- `state bundle`
- `secrets bundle`
- `.env`
- claves SSH
- sesiones
- datos de `n8n`
- dumps de PM2
- estado vivo del host

La regla correcta es:

1. clonar `omni-core`
2. inicializar perfil
3. capturar estado
4. exportar secretos
5. mover bundles
6. restaurar o migrar

## Inicio rápido

### Camino recomendado

```bash
omni
```

Flujos que verás:

- `Bridge`: usar la terminal actual como puente
- `Capture`: crear recovery pack
- `Restore`: restaurar desde bundle + secretos
- `Migrate`: reconstruir host end-to-end
- `Doctor`: auditar salud, disco, timers, drift y cleanup
- `Agent`: configurar la IA operativa de Omni

### Si ya sabes lo que necesitas

```bash
omni doctor
omni capture --profile full-home
omni migrate --profile full-home --accept-all
```

## Flujos recomendados

### 1. Capturar un host actual

```bash
omni init --profile full-home
export OMNI_SECRET_PASSPHRASE='tu-clave-fuerte'
omni inventory --profile full-home
omni capture --profile full-home
```

Qué produce:

- `state bundle`
- `secrets bundle`
- `capture summary`

Luego saca `backups/host-bundles` fuera del host actual.

### 2. Restaurar en un host nuevo

```bash
omni init --profile full-home
export OMNI_SECRET_PASSPHRASE='la-misma-clave-fuerte'
omni restore --profile full-home --accept-all
```

Úsalo cuando ya tienes los bundles en el host nuevo.

### 3. Migrar host completo

```bash
omni init --profile full-home
export OMNI_SECRET_PASSPHRASE='la-misma-clave-fuerte'
omni migrate --profile full-home --accept-all
```

`migrate` hace más que `restore`: también aplica lógica de reconstrucción y reescritura automática de referencias de host.

### 4. Usar PowerShell como puente

PowerShell no ejecuta Omni nativamente como si fuera Linux. Lo usa como lanzador hacia Ubuntu remoto.

Guía dedicada:

- [GUIA_POWERSHELL_WINDOWS.md](/home/ubuntu/omni-core/GUIA_POWERSHELL_WINDOWS.md)

Bootstrap:

```powershell
pwsh .\bootstrap.ps1 -TargetHost 1.2.3.4 -User ubuntu -RepoUrl git@github.com:sxrubyo/omni-core.git -Branch main -InstallTimer
```

Si no pasas `-Destination`, `bootstrap.ps1`:

- escanea el host remoto
- recomienda rutas
- te deja elegir una sugerida
- o te deja marcar una personalizada

### 5. Instalación simple desde GitHub

Si no quieres pelear con wrappers:

- [GUIA_INSTALACION_SIMPLE_GITHUB.md](/home/ubuntu/omni-core/GUIA_INSTALACION_SIMPLE_GITHUB.md)

## Instalación

### Linux local

```bash
bash bootstrap.sh https://github.com/sxrubyo/omni-core.git /opt/omni-core main
```

Si el clon local ya existe y tiene cambios o archivos sueltos, `bootstrap.sh` los guarda en un `git stash` antes de actualizar.

### GitHub publico o privado

```bash
git clone https://github.com/sxrubyo/omni-core.git /opt/omni-core
cd /opt/omni-core
chmod +x install.sh bin/omni bootstrap.sh
./install.sh --compose --sync --timer
```

### Carpeta copiada por SCP

```bash
scp -r omni-core ubuntu@tu-servidor:/opt/omni-core
ssh ubuntu@tu-servidor
cd /opt/omni-core
chmod +x install.sh bin/omni bootstrap.sh
./install.sh --compose --sync --timer
```

## Arquitectura operativa

### Inventory

Clasifica el host en:

- estado
- secretos
- ruido

Comando:

```bash
omni inventory
```

### Bundles

Estado:

```bash
omni bundle-create
omni bundle-restore
```

Secretos:

```bash
omni secrets-export
omni secrets-import
```

### Reconcile

Reconstruye el host desde manifest + bundles:

```bash
omni reconcile --bundle-latest --secrets-latest
```

### Drift de host

Omni detecta si el host nuevo sigue teniendo referencias del host viejo.

Comandos:

```bash
omni detect-ip
omni rewrite-ip
omni rewrite-ip --apply
```

`migrate` hace esto automáticamente por defecto.

Si no quieres que lo haga:

```bash
omni migrate --skip-rewrite
```

## Backups automáticos

Omni ya deja respaldo automático en varios puntos críticos:

- `omni init`
- `omni restore`
- `omni migrate`
- `omni rewrite-ip --apply`

Esos backups quedan en:

```text
backups/auto-bundles
```

### Backup por cambios

`omni timer-install` instala también:

- `omni-watch.service`

Ese watcher:

- vigila cambios en el scope del manifest
- detecta add/modify/remove
- dispara backup automático con cooldown

### Backup diario

`omni-update.timer` corre cada 24 horas y ejecuta:

1. `omni backup`
2. `omni fix`
3. `omni sync`

Instalación:

```bash
omni timer-install
```

## Omni Agent

`omni agent` configura la IA operativa del host con selector visual estilo Melissa/OpenClaw.

Comandos:

```bash
omni agent
omni agent status
omni agent list
```

Los prompts de `omni agent` para API keys, base URL y modelos personalizados están optimizados para pegar texto sin pelear con PowerShell, SSH ni terminales mixtos.

### Proveedores soportados hoy

- Claude Direct
- OpenAI Direct
- Azure OpenAI
- Gemini Direct
- Gemini OpenAI-compatible
- OpenRouter
- AWS Bedrock
- xAI Grok
- Groq
- Qwen Model Studio
- DeepSeek
- Mistral
- Cohere
- Together AI
- Perplexity
- Custom OpenAI-compatible

### Qué hace `omni agent list`

Imprime:

- proveedor
- protocolo
- variable de entorno
- base URL
- modelo por defecto
- modelos sugeridos
- documentación oficial

### Prompt de activación

Omni separa el proveedor principal de la identidad conversacional.

- El proveedor principal lo eliges en `omni agent`
- La identidad y propósito persistente viajan en `config/omni_agent_activation.txt`

Ese archivo se crea automáticamente con `omni init` si no existe, viaja con `full-home` y sirve para que Omni/Codex conozca el propósito del workspace sin reemplazar el modelo elegido por el usuario.

## Omni Chat

`omni chat` abre una interfaz conversacional de terminal usando el provider elegido en `omni agent`.

Comandos:

```bash
omni chat
omni chat status
omni chat "hazme un diagnóstico rápido del host"
```

Qué hace:

- carga el provider principal configurado
- aplica el prompt de activación persistente
- guarda historial en `data/agent-chat`
- soporta slash commands
- puede sugerir comandos o listas de tareas por una capa de acciones separada
- puede interceptar intents operativos como migración, capture, rewrite e inventario del stack
- pide permiso según el perfil activo del chat antes de ejecutar acciones sensibles

Slash commands principales:

- `/help`
- `/status`
- `/new`
- `/clear`
- `/save`
- `/run`
- `/todo`
- `/exec on|off`
- `/permissions`
- `/quit`

La respuesta visible es conversacional normal. Si Omni necesita sugerir un comando o un plan, lo hace por debajo con acciones estructuradas para que el chat no suene a JSON ni a código.

Perfiles de permisos:

- `smart`: auto solo para acciones seguras; pregunta en installs, rewrite o shell
- `ask`: pregunta antes de cada acción ejecutable
- `auto`: auto para casi todo; solo frena acciones peligrosas
- `all`: auto para todo

Ejemplos:

```bash
omni chat
# dentro del chat:
/permissions smart
/permissions all
```

### Nota sobre Claude 4.6

En Omni:

- Anthropic directo usa el catálogo oficial directo de Anthropic
- Claude 4.6 quedó modelado por `AWS Bedrock`

## Omni Examples

`omni examples` imprime playbooks listos para copiar.

Incluye:

- arranque guiado
- captura `full-home`
- migración completa
- diagnóstico rápido
- rewrite de IP y hostname
- configuración de `omni agent`
- `omni chat`
- `omni packages`
- bridge send
- purge

Uso:

```bash
omni examples
```

## Omni Auto

`omni auto` resume la automatización activa del host.

Uso básico:

```bash
omni auto
```

Para sacar el one-liner de PowerShell listo para pegar:

```bash
omni auto --p
```

Si además quieres que Omni te genere el archivo `.ps1`:

```bash
omni auto --p --ps1-out ./omni-auto.ps1
```

Si quieres que Omni además te deje el bloque para crear el archivo directamente dentro de una carpeta Windows:

```bash
omni auto --p --windows-dir "C:\Users\santi\Downloads\Projects\Ubuntu"
```

Con valores reales:

```bash
omni auto --p \
  --target-host ec2-54-160-79-60.compute-1.amazonaws.com \
  --identity-file "C:\\Users\\santi\\Downloads\\materia oscura\\llave_maestra_aws.pem" \
  --dest /home/ubuntu/omni-core \
  --ps1-out ./omni-auto.ps1 \
  --windows-dir "C:\\Users\\santi\\Downloads\\Projects\\Ubuntu"
```

Qué hace:

- imprime un `pwsh .\bootstrap.ps1 ...` listo para usar
- si omites `--dest`, `bootstrap.ps1` escanea el host remoto y recomienda la ruta
- deja `-InstallTimer` activo para que la actualización remota quede automatizada
- si pasas `--ps1-out`, también escribe el script PowerShell listo en disco
- si pasas `--windows-dir`, además imprime el bloque listo para crear `omni-auto.ps1` dentro de esa carpeta Windows

## Mapa de comandos

### Entrada y flujos

| Comando | Para qué sirve | Cuándo usarlo |
|---|---|---|
| `omni` | abre el asistente guiado | casi siempre |
| `omni start` | igual que `omni` | cuando quieres ser explícito |
| `omni commands` | muestra la superficie completa de comandos | cuando quieres recordar todo el mapa |
| `omni examples` | imprime playbooks listos para copiar | cuando quieres guía rápida sin abrir todo el README |
| `omni auto` | muestra automatización o genera el one-liner PowerShell | cuando quieres mantener o actualizar el host con un solo carril |
| `omni doctor` | auditoría guiada del host | antes de migrar o después de restaurar |
| `omni capture` | crea recovery pack del perfil activo | antes de apagar o mover un host |
| `omni restore` | restaura estado + secretos | cuando ya tienes bundles en el host nuevo |
| `omni migrate` | reconstruye host completo | cuando quieres mover o recrear servidor |
| `omni bridge` | modo puente para crear/enviar/recibir packs | desde terminal intermedia o PowerShell |

### Operación core

| Comando | Para qué sirve | Nota |
|---|---|---|
| `omni check` | health check simple | revisión rápida |
| `omni fix` | fix completo del sistema | mantenimiento correctivo |
| `omni watch` | watcher de cambios + auto-backup | normalmente como servicio |
| `omni status` | estado general | visión rápida |
| `omni logs` | logs de Omni | soporte y diagnóstico |
| `omni monitor` | monitoreo continuo | observación en vivo |

### Estado y reconstrucción

| Comando | Para qué sirve | Nota |
|---|---|---|
| `omni init` | crea config/runtime faltante | primer paso en host nuevo |
| `omni inventory` | clasifica estado, secretos y ruido | previo a capture |
| `omni packages` | enumera el stack instalado del host | APT, Python, npm global y PM2 |
| `omni bundle-create` | exporta bundle de estado | modo experto |
| `omni bundle-restore` | restaura bundle de estado | modo experto |
| `omni secrets-export` | exporta pack cifrado de secretos | requiere passphrase |
| `omni secrets-import` | importa pack cifrado de secretos | mismo passphrase |
| `omni reconcile` | reconstruye desde manifest + bundles | base del restore experto |

### Red, host y transferencias

| Comando | Para qué sirve | Nota |
|---|---|---|
| `omni sync` | trae snapshots desde `servers.json` | rsync/scp |
| `omni transfer` | transfiere archivos/directorios | uso manual |
| `omni detect-ip` | detecta identidad actual del host | ve drift |
| `omni rewrite-ip` | reescribe referencias viejas | usa `--apply` para ejecutar |
| `omni chat` | abre el chat operativo de Omni Agent | usa el provider configurado |
| `omni bridge send` | envía bundles a destino remoto | puente |
| `omni bridge receive` | restaura desde bundles recibidos | puente |

### Sistema, procesos y housekeeping

| Comando | Para qué sirve | Nota |
|---|---|---|
| `omni restart` | reinicia servicios PM2 | operación rápida |
| `omni backup` | crea backup manual | además existe auto-backup |
| `omni clean` | limpia temporales y cachés | mantenimiento |
| `omni purge` | libera disco borrando estado transferido y artefactos | usa `--yes` para ejecutar |
| `omni repos` | muestra estado de repos | Git y rutas |
| `omni processes` | muestra procesos PM2 | runtime |
| `omni config` | muestra configuración actual | inspección |
| `omni version` | versión de Omni | soporte |
| `omni install` | guía portable de instalación | onboarding |
| `omni timer-install` | instala timer diario + watcher | automatización |

## Banderas importantes

| Flag | Uso |
|---|---|
| `--profile production-clean|full-home` | elige alcance del manifest |
| `--accept-all` | omite prompts de Omni |
| `--yes` | confirma operaciones destructivas |
| `--manifest` | path del manifest |
| `--output` | archivo o directorio de salida |
| `--bundle` | bundle de estado explícito |
| `--secrets` | bundle de secretos explícito |
| `--bundle-latest` | usa último bundle de estado |
| `--secrets-latest` | usa último bundle de secretos |
| `--target-root` | raíz de restauración |
| `--passphrase-env` | variable con passphrase |
| `--target-public-ip` | IP pública objetivo para rewrite |
| `--target-private-ip` | IP privada objetivo para rewrite |
| `--target-hostname` | hostname objetivo para rewrite |
| `--apply` | aplica cambios en comandos de rewrite |
| `--skip-rewrite` | desactiva rewrite automático en migrate |
| `--protocol scp|rsync` | protocolo de transferencia |

## Escenarios rápidos

### Quiero llevarme todo `/home/ubuntu`

```bash
omni init --profile full-home
omni capture --profile full-home
```

### Quiero reconstruir un servidor nuevo

```bash
omni init --profile full-home
omni migrate --profile full-home --accept-all
```

### Quiero ver qué pesa antes de capturar

```bash
omni inventory --profile full-home
```

### Quiero ver el stack instalado real del host

```bash
omni packages
omni packages --output /tmp/host-packages.json
```

### Quiero arreglar referencias viejas de IP

```bash
omni detect-ip
omni rewrite-ip /home/ubuntu --apply --accept-all
```

### Quiero liberar espacio sin tocar repos base

```bash
omni purge
omni purge --yes
```

### Quiero incluir secretos en purge

```bash
omni purge --include-secrets --yes
```

### Quiero ver el catálogo de IA soportada

```bash
omni agent list
```

### Quiero hablar con Omni normal

```bash
omni chat
omni chat "revisa el host y dime los riesgos"
# dentro del chat:
/permissions smart
```

## Inventario de servidores remotos

Plantilla:

```text
config/servers.example.json
```

Ejemplo:

```json
{
  "servers": [
    {
      "name": "main-ubuntu",
      "host": "1.2.3.4",
      "user": "ubuntu",
      "port": 22,
      "protocol": "rsync",
      "paths": [
        "/home/ubuntu/melissa",
        "/home/ubuntu/nova-os",
        "/home/ubuntu/.nova",
        "/home/ubuntu/omni-core"
      ],
      "excludes": [".git", "__pycache__", "*.pyc", "node_modules"]
    }
  ]
}
```

Los snapshots quedan en:

```text
data/servers/<server>/<ruta-remota-normalizada>/
```

## Instalación automática recomendada

```bash
cd /opt/omni-core
omni init --profile full-home
nano .env
nano config/repos.json
nano config/servers.json
./install.sh --compose --sync --timer
omni
```

## Simulación local

```bash
rsync -av --delete /opt/omni-core/ /opt/omni-core-test/
cd /opt/omni-core-test
mkdir -p data-test backups-test logs-test
docker compose -p omni-core-test -f docker-compose.test.yml up -d --build
docker compose -p omni-core-test -f docker-compose.test.yml ps
docker compose -p omni-core-test -f docker-compose.test.yml logs -f omni-core-test
```

Parar simulación:

```bash
docker compose -p omni-core-test -f docker-compose.test.yml down
```

## Notas operativas

- `omni sync` usa `rsync` o `scp`
- GitHub privado requiere credenciales válidas en el host
- el `state bundle` y el `secrets bundle` deben viajar por rutas separadas
- PowerShell es lanzador/puente; la operación real sigue ocurriendo en Linux
- el repo puede ser público para facilitar clone, pero la reconstrucción real sigue dependiendo de bundles + secretos

## Documentación complementaria

- [GUIA_INSTALACION_SIMPLE_GITHUB.md](/home/ubuntu/omni-core/GUIA_INSTALACION_SIMPLE_GITHUB.md)
- [GUIA_POWERSHELL_WINDOWS.md](/home/ubuntu/omni-core/GUIA_POWERSHELL_WINDOWS.md)
