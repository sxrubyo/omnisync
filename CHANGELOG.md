# Changelog

## 2.5.0 - 2026-05-18

- `omni briefcase --full` ahora fuerza `full-home` aunque no se pase `--profile` y exporta snapshot completo del `home` junto al briefcase
- `omni connect`, `omni pull` y `omni gh restore` ya reconcilián el host después del bootstrap y usan un restore launcher exacto para el `home`
- el snapshot privado dejó de depender de listas fijas: ahora captura entradas reales del `home`, evita recursión dentro de `omnisync` y no sube la passphrase al repo privado de GitHub
- endurecido el installer offline y la recolección de inventario para que briefcase/pack/install sean más rápidos y estables en entornos restringidos

## 2.4.1 - 2026-05-11

- corregido `refresh_home_snapshot.sh` para tolerar archivos vivos que cambian durante el tar del overlay privado sin abortar el snapshot completo
- verificado el snapshot privado real de `/home/ubuntu` sobre un host activo antes de repetir el `omni push`

## 2.4.0 - 2026-05-11

- integrado `full-home` real sobre GitHub privado: `omni push`, `omni pull` y `omni gh restore` ya mueven briefcase más snapshot completo del home
- añadido `home_snapshot_ops.py` para empaquetar, subir, descargar y restaurar snapshots privados completos desde GitHub
- endurecido el flujo `connect -> GitHub` para archivos binarios y rutas de recovery consistentes
- actualizado el briefcase para reflejar que GitHub ya soporta snapshot privado completo del home
- incluido `scripts/refresh_home_snapshot.sh` y `scripts/restore_home_private_snapshot.sh` en la distribución npm
