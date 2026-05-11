# Changelog

## 2.4.0 - 2026-05-11

- integrado `full-home` real sobre GitHub privado: `omni push`, `omni pull` y `omni gh restore` ya mueven briefcase más snapshot completo del home
- añadido `home_snapshot_ops.py` para empaquetar, subir, descargar y restaurar snapshots privados completos desde GitHub
- endurecido el flujo `connect -> GitHub` para archivos binarios y rutas de recovery consistentes
- actualizado el briefcase para reflejar que GitHub ya soporta snapshot privado completo del home
- incluido `scripts/refresh_home_snapshot.sh` y `scripts/restore_home_private_snapshot.sh` en la distribución npm
