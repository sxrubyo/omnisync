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

## Paso 2. Ya dentro de Ubuntu, instala Git y GitHub CLI

Ahora sí, ya dentro del Ubuntu, pega esto:

```bash
sudo apt update
sudo apt install -y git gh
```

## Paso 3. Ya dentro de Ubuntu, inicia sesión en GitHub

Pega esto:

```bash
gh auth login
```

Cuando te pregunte:

- `Where do you use GitHub?` -> `GitHub.com`
- `What is your preferred protocol for Git operations?` -> `HTTPS`
- `Authenticate Git with your GitHub credentials?` -> `Yes`
- `How would you like to authenticate GitHub CLI?` -> `Login with a web browser`

Como estás dentro de Ubuntu por SSH, normalmente te mostrará:

- un enlace
- un código

Entonces haces esto:

1. copias el código que te muestre
2. abres el enlace en tu navegador normal
3. pegas el código
4. autorizas

Luego valida:

```bash
gh auth status
```

## Paso 4. Clona Omni Core

Todavía dentro de Ubuntu, pega esto:

```bash
gh repo clone sxrubyo/omni-core "$OMNI_DIR"
cd "$OMNI_DIR"
```

## Paso 5. Ejecuta la instalación

Todavía dentro de Ubuntu, pega esto:

```bash
chmod +x install.sh bin/omni bootstrap.sh
./install.sh --compose --sync --timer
```

Eso hace esto:

- prepara archivos base si faltan
- instala `omni`
- levanta Docker Compose
- ejecuta `sync`
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

## Paso 6. Verifica que quedó bien

Todavía dentro de Ubuntu, pega esto:

```bash
cd "$OMNI_DIR"
omni
omni doctor
omni inventory
docker compose ps
sudo systemctl status omni-update.timer --no-pager
```

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
sudo apt install -y git gh
gh auth login
gh repo clone sxrubyo/omni-core "$OMNI_DIR"
cd "$OMNI_DIR"
chmod +x install.sh bin/omni bootstrap.sh
./install.sh --compose --sync --timer
omni
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
