#!/bin/bash
# -b msdos or gpt
# -d device name
# -m mount point
# -f filesystem's type
# -v volgroup's name
# -l logic volume's name
# -D default action
## # # # # # # # # # # # # # # # # # #
# WARNING !!!
## # # # # # # # # # # # # # # # # # #
# if -f /dev/xvdb && echo "Error",exit
/sbin/parted /dev/$1 -s mklabel msdos
/sbin/parted /dev/$1 -s -- mkpart primary 0 -1
/sbin/pvcreate /dev/${1}1
/sbin/vgcreate  vg_data01 /dev/${1}1
/sbin/lvcreate -n lv_data01 --extents +100%FREE vg_data01
/sbin/mkfs.ext4 /dev/mapper/vg_data01-lv_data01
##########################################################
mkdir $2
echo "/dev/mapper/vg_data01-lv_data01	$2	ext4   defaults        0 0" >> /etc/fstab
mount -a
