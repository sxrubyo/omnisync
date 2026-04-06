# Omni Core - Guía simple desde GitHub

Esta guía es para hacerlo sin enredos.

La regla nueva es simple:

- instala `omni-core`
- ejecuta `omni`
- deja que el CLI te pregunte si quieres `bridge`, `capture`, `restore`, `migrate` o `doctor`
- si quieres llevarte todo `/home/ubuntu`, primero corre `omni init --profile full-home`

## Qué significa `full-home` de verdad

Si activas:

```bash
omni init --profile full-home
```

entonces Omni considera `/home/ubuntu` entero como estado. Eso incluye también:

- `.codex`
- `.agents`
- `.nova`
- `.n8n`
- `melissa-backups`
- y cualquier otra carpeta real que viva dentro de `/home/ubuntu`

`melissa-backups` importa si quieres poder reconstruir “todo”. No es código; son respaldos históricos de Melissa, y normalmente es de las carpetas más pesadas.

## Poner el repo público: qué sí resuelve

Si alguna vez quieres hacer el bootstrap mucho más fácil, sí: volver el repo público por unos segundos puede simplificar el `git clone` inicial.

Pero eso solo te facilita bajar `omni-core`. No reemplaza:

- el bundle de estado
- el pack de secretos
- `.env`
- credenciales
- sesiones
- dumps de PM2
- el estado completo de `/home/ubuntu`

O sea: GitHub público ayuda con el código del instalador. La migración real sigue necesitando `omni capture` y luego `omni restore` o `omni migrate`.

## Lo automático que ya hace Omni

Si ya existe `capture summary`, Omni puede detectar y corregir mucho más sin pedirte la IP:

- `omni start` y `omni doctor` detectan drift del host
- `omni detect-ip` te dice si siguen quedando referencias al host viejo
- `omni migrate` reescribe esas referencias automáticamente
- `omni rewrite-ip --apply` sigue existiendo como comando manual

Y además:

- `omni init`, `omni restore`, `omni migrate` y `omni rewrite-ip --apply` dejan backup automático en `backups/auto-bundles`
- el timer diario ejecuta `omni backup`, luego `omni fix` y `omni sync`
- `omni timer-install` deja también `omni-watch.service` para vigilar cambios del scope y disparar backup automático
- `omni agent` abre el selector visual de proveedor para Claude, OpenAI, Azure OpenAI, Gemini, Bedrock, OpenRouter, xAI, Groq, Qwen, DeepSeek, Mistral, Cohere, Together, Perplexity o endpoint compatible
- `omni agent list` te deja ver todo el catálogo sin entrar al wizard
- `omni chat` abre la interfaz conversacional normal de Omni usando el provider principal que elegiste
- dentro de `omni chat`, `/permissions smart|ask|auto|all` controla cuándo te pide permiso antes de ejecutar
- `omni packages` enumera APT, Python, npm global y PM2 del host
- `omni examples` imprime playbooks listos para copiar
- `omni auto --p` imprime el comando PowerShell de auto-actualización listo para pegar

Tu caso correcto es este:

1. abres PowerShell en tu PC
2. usas PowerShell solo para entrar a Ubuntu
3. una vez estés dentro de Ubuntu, ahí sí ejecutas `sudo`, `apt`, `chmod`, `./install.sh` y `omni`

No intentes correr comandos Linux directamente en PowerShell de Windows, porque por eso te salió:

- `sudo: The term 'sudo' is not recognized`
- `gh: The term 'gh' is not recognized`
- `chmod: The term 'chmod' is not recognized`
- `./install.sh: The term './install.sh' is not recognized`

Eso pasa porque esos comandos no son de Windows. Son de Ubuntu/Linux.

## Variables que vas a usar

En tu PowerShell, pega esto primero:

```powershell
$UBUNTU_HOST = "IP_DE_TU_SERVIDOR"
$UBUNTU_USER = "ubuntu"
$OMNI_DIR = "/home/ubuntu/omni-core"
```

Usamos `/home/ubuntu/omni-core` porque es el camino más simple para la primera instalación.

## Paso 1. Desde PowerShell, entra al Ubuntu

En PowerShell pega esto:

```powershell
ssh "$UBUNTU_USER@$UBUNTU_HOST"
```

Si todo va bien, verás algo parecido a esto:

```bash
ubuntu@ip-xxx:~$
```

Cuando veas eso, ya no estás en Windows: ya estás dentro del Ubuntu.

## Paso 2. Ya dentro de Ubuntu, instala Git

Ahora sí, ya dentro del Ubuntu, pega esto:

```bash
sudo apt update
sudo apt install -y git
```

## Paso 3. Clona Omni Core sin login

Si el repo está público, no necesitas iniciar sesión en GitHub. Pega esto:

```bash
bash -c 'cd /home/ubuntu && git clone https://github.com/sxrubyo/omni-core.git "$OMNI_DIR"'
```

Si `"$OMNI_DIR"` ya existe y quieres actualizarlo aunque esté sucio, usa esto en vez de `git pull`:

```bash
bash "$OMNI_DIR/bootstrap.sh" https://github.com/sxrubyo/omni-core.git "$OMNI_DIR" main
```

## Paso 4. Ejecuta la instalación

Todavía dentro de Ubuntu, pega esto:

```bash
cd "$OMNI_DIR"
chmod +x install.sh bin/omni bootstrap.sh
./install.sh --compose --timer
```

Eso hace esto:

- prepara archivos base si faltan
- instala `omni`
- levanta Docker Compose
- no fuerza `sync` si todavía no hay SSH remoto listo
- instala el timer diario
- si antes corriste `omni init --profile full-home`, el manifest ya quedará listo para capturar el home completo manteniendo secretos aparte

## Si después quieres capturar absolutamente todo

Todavía dentro de Ubuntu:

```bash
cd "$OMNI_DIR"
omni init --profile full-home
export OMNI_SECRET_PASSPHRASE='TU_CLAVE_FUERTE'
omni capture
```

El preflight de `omni capture` ahora te va a mostrar antes de confirmar:

- perfil activo
- raíz real de captura
- tamaño total del estado
- secretos separados
- directorios más pesados dentro del scope

Ahí vas a ver explícitamente si entran `.codex` y `melissa-backups`.

## Paso 5. Verifica que quedó bien

Todavía dentro de Ubuntu, pega esto:

```bash
cd "$OMNI_DIR"
omni
omni agent
omni chat
omni packages
omni doctor
omni inventory
docker compose ps
sudo systemctl status omni-update.timer --no-pager
```

`omni chat` usa el provider principal que dejaste en `omni agent`.

La identidad persistente del chat vive en:

```text
config/omni_agent_activation.txt
```

Ese archivo se crea con `omni init` si no existe y viaja con `full-home`.

## Resumen ultra corto

En PowerShell:

```powershell
$UBUNTU_HOST = "IP_DE_TU_SERVIDOR"
$UBUNTU_USER = "ubuntu"
$OMNI_DIR = "/home/ubuntu/omni-core"
ssh "$UBUNTU_USER@$UBUNTU_HOST"
```

Luego, ya dentro de Ubuntu:

```bash
sudo apt update
bash /home/ubuntu/omni-core/bootstrap.sh https://github.com/sxrubyo/omni-core.git "$OMNI_DIR" main
omni
omni agent
omni chat
omni packages
omni doctor
omni inventory
```

## Si después quieres restaurar todo

Eso no se hace en el primer minuto.

Primero deja funcionando la base.
Después ya haces, según el caso:

- `omni capture`
- `omni restore`
- `omni migrate`
- `omni detect-ip`
- `omni rewrite-ip`

## Si después quieres liberar espacio

Primero mira qué borraría:

```bash
omni purge
```

Si sí quieres borrar:

```bash
omni purge --yes
```

Si además quieres incluir secretos restaurados:

```bash
omni purge --include-secrets --yes
```

## Si algo falla

Pega esto dentro de Ubuntu:

```bash
cd "$OMNI_DIR"
omni logs
docker compose logs -f omni-core
```

## La regla más importante

Hazlo así:

- PowerShell solo para entrar al servidor
- Ubuntu para correr la instalación real

No mezcles comandos Linux en Windows, porque ahí es donde se rompe todo.
