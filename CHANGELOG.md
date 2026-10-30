# changelog

все заметные изменения проекта. формат по keep a changelog, версии по
semantic versioning.

## [1.0.0] - 2026-10-31

### added

* установщик sysblink.py с интерактивным меню и флагами для скриптов
* шаблон демона engine.c на c99 strict
* десять патчей: cpu, mem, swap, disk, net, thermal, battery, loadavg,
  heartbeat, breathe
* пять бэкендов инициализации плюс режим без установки: systemd, openrc,
  runit, s6, sysvinit
* несколько диодов на один демон, масштабирование по каждому
* sysblink.conf с дефолтами и закреплением диска и интерфейса
* preview.py для просмотра патча на фейковом диоде
* man страница, сборка deb, pkgbuild для aur
* 25 автоматических проверок, ci на каждый push, релиз deb по тегу

### fixed

* mem.c возвращал ноль процентов из за затирания memtotal
* disk и net давали ложный пик на первом тике
* игнорирование результата write и ftruncate ломало сборку с fortify

### known issues

* на живом железе установка не проверялась
* pkgbuild для arch не проверялся
* поддержка s6 rc раскладок отсутствует
