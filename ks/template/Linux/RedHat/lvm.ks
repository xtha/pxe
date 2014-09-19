part /boot --fstype=ext4 --size=500
part pv.202002 --grow --size=1
volgroup vg00 --pesize=4096 pv.202002
logvol swap --name=lv_swap --vgname=vg00 --size=4096
logvol / --fstype=ext4 --name=lv_root --vgname=vg00 --size=1 --grow
