part /boot --fstype=ext4 --size=500
#
part pv.system --grow --size=1
#
volgroup system --pesize=4096 pv.system
#head -n 1 /proc/meminfo | sed -n 's/\s\+/ /p' | awk '{ print int(($2/1024/1024))}'
#pykickstart
logvol swap --name=lv_swap --vgname=system --size=4096
logvol / --fstype=ext4 --name=lv_root --vgname=system --size=1 --grow
