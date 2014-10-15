part /boot --fstype=ext4 --size=500
part pv.system --grow --size=1
volgroup system --pesize=4096 pv.system
logvol swap --name=lv_swap --vgname=system --size=32768
logvol / --fstype=ext4 --name=lv_root --vgname=system --size=1 --grow
