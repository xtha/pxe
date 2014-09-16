#!/bin/bash
wget -O /boot/vmlinuz-rhel63-64-pxe http://192.168.11.9/os/linux/rhel/6.3/x86_64/images/pxeboot/vmlinuz
wget -O /boot/initrd.img-rhel63-64-pxe http://192.168.11.9/os/linux/rhel/6.3/x86_64/images/pxeboot/initrd.img

# don't use in vm
# get EFI DATA ERROR
#kexec -l /boot/vmlinuz-pxe –initrd=/boot/initrd.img-pxe –append=”ks=http://192.168.11.9/pxe/ks/linux/rhel/6.3/x86_64/lvm-swap4g.cfg ksdevice=eth0”

cat << EOF >> /boot/grub/grub.conf
title Install RHEL 6.3 x86_64 minimal-desktop with ks
	root (hd0,0)
	kernel /vmlinuz-rhel63-64-pxe ks=http://192.168.11.9/pxe/ks/linux/rhel/6.3/x86_64/lvm-swap4g.cfg ksdevice=eth0
	initrd /initrd.img-rhel63-64-pxe
EOF

sed -i '/default=0/s/0/1/' /boot/grub/grub.conf
